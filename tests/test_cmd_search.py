"""Contract tests for corroborating an absence claim with two independent scans.

This module exists because of a real correction in this project. A claim that a field had "no
readers anywhere" was published from a single linear disassembly sweep, and the sweep misses
code whenever it desynchronises — one stray byte ahead of a Thumb instruction is enough. The
rule this enforces: an absence is only stated when a decoding-independent search agrees.

Offline only.
"""
from __future__ import annotations

import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "research"))

from cmd_search import corroborate, scan_encoding, scan_linear, sweep_coverage  # noqa: E402


def thumb_str_imm(base_reg: int, value_reg: int, imm12: int) -> bytes:
    """A 32-bit Thumb ``str.w rT,[rB,#imm12]`` with ``imm12`` in the second halfword."""
    first = 0xF8C0 | base_reg
    second = (value_reg << 12) | imm12
    return struct.pack("<HH", first, second)


def thumb_ldr_imm(base_reg: int, value_reg: int, imm12: int) -> bytes:
    """A 32-bit Thumb ``ldr.w rT,[rB,#imm12]``."""
    first = 0xF8D0 | base_reg
    second = (value_reg << 12) | imm12
    return struct.pack("<HH", first, second)


class EncodingScanTests(unittest.TestCase):
    def test_finds_a_store_by_its_immediate(self) -> None:
        blob = thumb_str_imm(3, 1, 0x5D0)
        self.assertEqual(scan_encoding(blob, 0x5D0), [0])

    def test_finds_a_load_by_its_immediate(self) -> None:
        blob = thumb_ldr_imm(3, 1, 0x5D0)
        self.assertEqual(scan_encoding(blob, 0x5D0), [0])

    def test_ignores_a_different_immediate(self) -> None:
        blob = thumb_str_imm(3, 1, 0x5D1)
        self.assertEqual(scan_encoding(blob, 0x5D0), [])

    def test_finds_a_site_a_linear_sweep_desynchronises_past(self) -> None:
        # A single stray byte ahead of the instruction breaks a linear decode, which is how a
        # wrong "no readers" claim gets published. The encoding scan is alignment-independent,
        # so it must still see the site.
        blob = b"\x00" + thumb_str_imm(3, 1, 0x5D0)
        self.assertEqual(scan_encoding(blob, 0x5D0), [1])
        self.assertEqual(scan_linear(blob, 0x1000, ("str",), 0x5D0), [],
                         "a linear sweep from an odd offset must miss the instruction")


class CorroborateTests(unittest.TestCase):
    def test_disagreement_is_reported_with_the_sites_only_one_method_found(self) -> None:
        blob = b"\x00" + thumb_str_imm(3, 1, 0x5D0)
        result = corroborate(blob, 0x1000, 0x5D0, ("str",))
        self.assertFalse(result["agrees"])
        self.assertEqual(result["encoding_only"], [0x1001])

    def test_agreement_is_reported_when_both_see_the_same_sites(self) -> None:
        blob = thumb_str_imm(3, 1, 0x5D0) * 2
        result = corroborate(blob, 0x1000, 0x5D0, ("str",))
        self.assertTrue(result["agrees"])
        self.assertEqual(result["encoding_hits"], 2)
        self.assertEqual(result["linear_hits"], 2)

    def test_absence_is_agreement_when_neither_method_finds_anything(self) -> None:
        blob = thumb_str_imm(3, 1, 0x111)
        result = corroborate(blob, 0x1000, 0x5D0, ("str",))
        self.assertTrue(result["agrees"])
        self.assertEqual(result["encoding_hits"], 0)


class CoverageTests(unittest.TestCase):
    """A linear sweep that stops early must not be read as "absent"."""

    def test_coverage_reports_where_the_sweep_stopped(self) -> None:
        blob = thumb_str_imm(3, 1, 0x5D0) + b"\xff\xff\xff\xff" * 4
        coverage = sweep_coverage(blob, 0x1000)
        self.assertGreater(coverage["instructions"], 0)
        self.assertLess(coverage["fraction"], 1.0,
                        "an undecodable tail means the sweep did not cover the input")

    def test_an_early_stop_is_not_agreement(self) -> None:
        # A real image's linear sweep can stop after a few dozen instructions; silence from that
        # sweep must never be reported as corroboration.
        blob = b"\xff\xff\xff\xff" * 8 + thumb_str_imm(3, 1, 0x5D0)
        result = corroborate(blob, 0x1000, 0x5D0, ("str",))
        self.assertFalse(result["agrees"])
        self.assertLess(result["linear_coverage"]["fraction"], 0.5)


class RealImageTests(unittest.TestCase):
    """Opt-in: assert the calibration that the published absence claim rests on."""

    def setUp(self) -> None:
        import os
        raw = os.environ.get("A6400_UNPACKED_ROOT")
        if not raw:
            self.skipTest("A6400_UNPACKED_ROOT not set; no unpacked body available")
        hits = sorted(Path(raw).glob(
            "*/firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked/av-cam.bin"))
        if not hits:
            self.skipTest("no av-cam.bin under A6400_UNPACKED_ROOT")
        self.image = hits[0]

    def test_the_reference_field_is_seen_by_both_methods(self) -> None:
        # The a6600 handler stores into +0x5d0, so a corroborated search must find at least one
        # site and the two methods must agree on what they found.
        result = corroborate(self.image.read_bytes(), 0x635C6000, 0x5D0, ("str",))
        self.assertGreater(result["encoding_hits"], 0,
                           "the encoding scan must see the store the handler performs")
        self.assertTrue(result["agrees"] or result["encoding_only"],
                        "disagreement is acceptable only when the encoding-only sites are named")


if __name__ == "__main__":
    unittest.main()
