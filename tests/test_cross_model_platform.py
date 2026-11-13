"""Contract tests for the cross-model BIONZ X tooling (E0431–E0434).

These run without a camera and without any firmware: every case is either a synthetic image
whose shape is constructed by the test, or a real image the caller points at through an
environment variable. That keeps CI honest — the tests exercise the parsers' refusal
behaviour even on a machine that has never unpacked a Sony updater.

What is worth testing here, and what is not:

* worth testing — the container parser refuses a truncated or unknown chunk instead of
  guessing; the command-table locator refuses an image with no table; the field scanner
  reports a known-good reference exactly; the sharing verdict is derived from symbol equality
  rather than from a hard-coded list.
* not worth testing — the exact address of any one body's symbol (that is data, recorded in
  the evidence records, and it changes per build), or the byte content of a real updater.
"""
from __future__ import annotations

import json
import struct
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "research"))

import sony_updater_payload as payload  # noqa: E402
import av_command_table as cmdtable  # noqa: E402


def _updater_with_ufu(chunks: list[tuple[bytes, bytes]]) -> bytes:
    """Build a minimal UFU-shaped executable: header, junk, magic, chunks."""
    body = bytearray(payload.UFU_MAGIC)
    for tag, data in chunks:
        body += struct.pack(">I", len(data)) + tag + data
    return bytes(b"MZ" + b"\x00" * 62 + b"junk" + body)


def _record(command_id: int, handler: int, flag: int = 0, checker: int = 0) -> bytes:
    return struct.pack("<IIII", command_id, handler, flag, checker)


class SonyUpdaterPayloadTests(unittest.TestCase):
    def test_ufu_container_is_cut_exactly_at_dend(self) -> None:
        raw = _updater_with_ufu([
            (b"DATV", b"\x01\x00\x00\x00"),
            (b"FDAT", b"\xaa" * 32),
            (b"DEND", b"\xde\xad\xbe\xef"),
        ])
        end = payload.ufu_extent(raw, raw.index(payload.UFU_MAGIC))
        self.assertEqual(raw[end - 4:end], b"\xde\xad\xbe\xef")
        self.assertEqual(end, len(raw), "the container must consume the whole file here")

    def test_dend_bytes_inside_fdat_do_not_truncate_the_container(self) -> None:
        # A payload that itself contains the ASCII tag 'DEND' must not end the container.
        tricky = b"DEND" + b"\x00" * 28
        raw = _updater_with_ufu([(b"FDAT", tricky), (b"DEND", b"\x00" * 4)])
        end = payload.ufu_extent(raw, raw.index(payload.UFU_MAGIC))
        self.assertEqual(end, len(raw))

    def test_unknown_chunk_tag_is_refused(self) -> None:
        raw = _updater_with_ufu([(b"ZZZZ", b"\x00" * 4), (b"DEND", b"")])
        with self.assertRaises(ValueError):
            payload.ufu_extent(raw, raw.index(payload.UFU_MAGIC))

    def test_container_without_dend_is_refused(self) -> None:
        raw = _updater_with_ufu([(b"FDAT", b"\x00" * 8)])
        with self.assertRaises(ValueError):
            payload.ufu_extent(raw, raw.index(payload.UFU_MAGIC))

    def test_packman_cabinet_is_inverted_and_length_checked(self) -> None:
        cabinet = bytearray(b"MSCF" + b"\x00\x00\x00\x00" + struct.pack("<I", 40) + b"\x00" * 28)
        inverted = bytes(b ^ 0xFF for b in cabinet) + b"trailing"
        raw = b"MZ" + b"\x00" * 30 + inverted
        start = raw.index(payload.INVERTED_MSCF)
        restored = payload.packman_extent(raw, start)
        self.assertEqual(restored[:4], b"MSCF")
        self.assertEqual(len(restored), 40)

    def test_impossible_cabinet_size_is_refused(self) -> None:
        cabinet = bytearray(b"MSCF" + b"\x00\x00\x00\x00" + struct.pack("<I", 10) + b"\x00" * 28)
        raw = bytes(b ^ 0xFF for b in cabinet)
        with self.assertRaises(ValueError):
            payload.packman_extent(raw, 0)

    def test_a_file_with_neither_shape_is_refused_rather_than_guessed(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / "not-an-updater.exe"
            exe.write_bytes(b"MZ" + b"\x00" * 100)
            with self.assertRaises(ValueError):
                payload.extract(exe, Path(tmp) / "out")


class CommandTableTests(unittest.TestCase):
    def _image(self, count: int, start_id: int = 0x4000, prefix: bytes = b"\x00" * 16) -> bytes:
        records = b"".join(
            _record(start_id + i, 0x635C6000 + 0x1000 + i * 4) for i in range(count))
        return prefix + records + b"\x00" * 64

    def test_table_is_located_by_shape(self) -> None:
        table = cmdtable.find_table(self._image(300))
        self.assertEqual(len(table), 300)
        self.assertEqual(table.ids[0], 0x4000)
        self.assertEqual(table.zero_handlers, 0)

    def test_table_offset_is_not_assumed_to_be_aligned(self) -> None:
        # 4-byte prefix: the locator must still find it, which is what real images need.
        table = cmdtable.find_table(self._image(120, prefix=b"\x11\x22\x33\x44"))
        self.assertEqual(table.offset, 4)

    def test_image_without_a_table_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            cmdtable.find_table(b"\x00" * 4096)

    def test_short_run_is_not_accepted_as_a_table(self) -> None:
        with self.assertRaises(ValueError):
            cmdtable.find_table(self._image(cmdtable.MIN_RECORDS - 1))

    def test_ids_outside_the_command_range_break_the_run(self) -> None:
        good = self._image(200)
        # splice one record whose id is out of range in the middle
        broken = good[:16 * 100] + _record(0x9999, 0x635C7000) + good[16 * 101:]
        table = cmdtable.find_table(broken)
        self.assertEqual(len(table), 100, "the run must stop at the out-of-range record")


class SharingVerdictTests(unittest.TestCase):
    """The 'one code object' verdict must follow from symbol equality, not from a list."""

    def _body(self, name: str, symbols: dict[str, int]):
        import cross_model_report as report
        body = report.Body(name)
        body.symbols = dict(symbols)
        body.command_ids = (0x4000,)
        body.build = "test"
        return body

    def test_identical_maps_are_one_code_object(self) -> None:
        import cross_model_report as report
        syms = {f"sym_{i}": 0x60200000 + i * 4 for i in range(500)}
        a = self._body("a", syms)
        b = self._body("b", syms)
        result = report.compare([a, b], "a")
        group = next(g for g in result["kernel_groups"] if len(g["bodies"]) == 2)
        self.assertEqual(group["verdict"], "one code object")
        self.assertEqual(group["identical_addresses"], group["shared_symbols"])

    def test_a_few_differing_addresses_are_reported_as_data(self) -> None:
        """Nine addresses differing between two real bodies are data, and the verdict says so."""
        import cross_model_report as report
        syms = {f"sym_{i}": 0x60200000 + i * 4 for i in range(500)}
        moved = dict(syms)
        for name in list(moved)[:3]:
            moved[name] += 1
        a = self._body("a", syms)
        b = self._body("b", moved)
        a.types = {n: "R" for n in syms}
        b.types = dict(a.types)
        result = report.compare([a, b], "a")
        group = next(g for g in result["kernel_groups"] if len(g["bodies"]) == 2)
        self.assertIn("all 3 differing addresses are data", group["verdict"])

    def test_a_differing_function_symbol_is_not_called_data(self) -> None:
        """A moved function must not be described as string data: that would overstate sharing."""
        import cross_model_report as report
        syms = {f"sym_{i}": 0x60200000 + i * 4 for i in range(500)}
        moved = dict(syms)
        moved["sym_7"] += 4
        a = self._body("a", syms)
        b = self._body("b", moved)
        a.types = {n: ("T" if n == "sym_7" else "R") for n in syms}
        b.types = dict(a.types)
        result = report.compare([a, b], "a")
        group = next(g for g in result["kernel_groups"] if len(g["bodies"]) == 2)
        self.assertIn("function symbols", group["verdict"])
        self.assertNotIn("all 1 differing addresses are data", group["verdict"])

    def test_many_differing_addresses_are_reported_as_shifted(self) -> None:
        import cross_model_report as report
        syms = {f"sym_{i}": 0x60200000 + i * 4 for i in range(500)}
        moved = {k: v + 0x60 for k, v in syms.items()}
        result = report.compare([self._body("a", syms), self._body("b", moved)], "a")
        group = next(g for g in result["kernel_groups"] if len(g["bodies"]) == 2)
        self.assertIn("shifted", group["verdict"])

    def test_a_unique_body_is_reported_as_unique(self) -> None:
        import cross_model_report as report
        syms = {f"sym_{i}": 0x60200000 + i * 4 for i in range(500)}
        other = {f"other_{i}": 0x60200000 + i * 4 for i in range(500)}
        result = report.compare([self._body("a", syms), self._body("b", other)], "a")
        verdicts = [g["verdict"] for g in result["kernel_groups"]]
        self.assertEqual(verdicts, ["unique build", "unique build"])


class RealImageTests(unittest.TestCase):
    """Opt-in checks against a real unpacked body, skipped when none is supplied.

    Set ``A6400_UNPACKED_ROOT`` to a directory of unpacked bodies to run these. They assert the
    calibration the evidence records rely on, so a regression in the parsers is caught on a
    machine that does have the images.

    The ``0x413b`` calibration needs a body that actually carries the command (the a6400 and
    a6100A do not), so it looks for the first body that has one instead of assuming the first
    directory alphabetically is suitable.
    """

    def setUp(self) -> None:
        raw = __import__("os").environ.get("A6400_UNPACKED_ROOT")
        if not raw:
            self.skipTest("A6400_UNPACKED_ROOT not set; no unpacked body available")
        self.root = Path(raw)
        self.avcams = sorted(
            self.root.glob("*/firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked/av-cam.bin"))
        if not self.avcams:
            self.skipTest("no av-cam.bin under A6400_UNPACKED_ROOT")

    def test_command_table_of_a_real_image_has_no_zero_handlers(self) -> None:
        table = cmdtable.read_table(self.avcams[0])
        self.assertGreater(len(table), 200)
        self.assertEqual(table.zero_handlers, 0)
        self.assertEqual(len(set(table.ids)), len(table), "command ids must be unique")

    def test_eyeaf_reference_calibration(self) -> None:
        import av_eyeaf_field as eyeaf
        for image in self.avcams:
            result = eyeaf.analyse(image, 0x413B)
            if not result["present"]:
                continue
            self.assertEqual(result["reads"], 0,
                             f"{image.parts[-6]}: this record's claim is zero readers")
            self.assertGreaterEqual(result["writes"], 1,
                                    f"{image.parts[-6]}: the handler must store the value")
            return
        self.skipTest("no unpacked body carries command 0x413b")


if __name__ == "__main__":
    unittest.main()
