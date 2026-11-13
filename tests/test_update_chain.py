"""Contract tests for the update-chain analysis (E0489).

The point of this module is a claim the whole ecosystem repeats: that the camera image is
AES-encrypted with per-model keys and several integrity layers. Those tests pin the measured
answer and, just as importantly, keep the distinction that the wrong claim blurred: a checksum
is not a signature.

Every case runs without a camera or a firmware image. The cases that need a real unpacked body
are opt-in through ``A6400_UNPACKED_ROOT`` and skip otherwise, so CI stays camera-free.
"""
from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "research"))

import update_chain  # noqa: E402


class CryptoSurfaceTests(unittest.TestCase):
    """A checksum tool must never be read as a signature."""

    def test_a_plain_script_reports_no_crypto_at_all(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "plain.elf"
            path.write_bytes(b"#!/bin/sh\necho hello\n")
            surface = update_chain.crypto_surface(path)
            self.assertFalse(surface["has_aes"])
            self.assertFalse(surface["has_signature"])
            self.assertFalse(surface["has_md5"])
            self.assertFalse(surface["has_crc32"])

    def test_md5sum_is_a_checksum_and_never_a_signature(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "checker.elf"
            path.write_bytes(b"\x7fELF" + b"\x00" * 60 + b"md5sum\x00")
            surface = update_chain.crypto_surface(path)
            self.assertTrue(surface["has_md5"])
            self.assertFalse(surface["has_signature"])

    def test_crc32_tool_is_a_checksum_and_never_a_signature(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "crc.elf"
            path.write_bytes(b"\x7fELF" + b"\x00" * 60 + b"uc_crc32sum\x00")
            surface = update_chain.crypto_surface(path)
            self.assertTrue(surface["has_crc32"])
            self.assertFalse(surface["has_signature"])

    def test_an_rsa_string_is_read_as_a_signature_surface(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "signed.elf"
            path.write_bytes(b"\x7fELF" + b"\x00" * 60 + b"rsa_verify\x00")
            surface = update_chain.crypto_surface(path)
            self.assertTrue(surface["has_signature"])

    def test_aes_is_detected_from_the_named_symbol(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "aes.elf"
            path.write_bytes(b"\x7fELF" + b"\x00" * 60 + b"AES_set_decrypt_key\x00")
            surface = update_chain.crypto_surface(path)
            self.assertTrue(surface["has_aes"])


class UpdaterScriptTests(unittest.TestCase):
    def test_md5sum_dash_c_counts_as_a_checksum(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "loader_writer.sh").write_text(
                "#!/bin/sh\n$MD5SUM_COMMAND -c $SUM_FILE\n")
            rows = update_chain.updater_scripts(root)
            self.assertEqual(len(rows), 1)
            self.assertTrue(rows[0]["verifies_checksum"])
            self.assertFalse(rows[0]["verifies_signature"])

    def test_a_script_that_only_checks_existence_verifies_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "filecheck.sh").write_text("#!/bin/sh\n[ -f $FILE_NAME ] && exit 0\n")
            rows = update_chain.updater_scripts(root)
            self.assertFalse(rows[0]["verifies_checksum"])
            self.assertFalse(rows[0]["verifies_signature"])

    def test_a_signature_word_in_a_script_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "signed.sh").write_text("#!/bin/sh\nopenssl dgst -verify signature\n")
            rows = update_chain.updater_scripts(root)
            self.assertTrue(rows[0]["verifies_signature"])


class PlainElfCountTests(unittest.TestCase):
    def test_counts_only_files_that_start_with_an_elf_magic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.elf").write_bytes(b"\x7fELF" + b"\x00" * 20)
            (root / "b.bin").write_bytes(b"\x7fELF" + b"\x00" * 20)
            (root / "c.txt").write_bytes(b"not an elf")
            (root / "sub").mkdir()
            (root / "sub" / "d.elf").write_bytes(b"\x7fELF" + b"\x00" * 20)
            self.assertEqual(update_chain.plain_elfs(root), 3)


class RealImageTests(unittest.TestCase):
    """Opt-in cases that assert the published numbers against a real unpacked body."""

    def setUp(self) -> None:
        import os
        raw = os.environ.get("A6400_UNPACKED_ROOT")
        if not raw:
            self.skipTest("A6400_UNPACKED_ROOT not set; no unpacked body available")
        self.root = Path(raw)
        libs = sorted(self.root.glob(
            "*/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/lib/libupdatertalk.so"))
        updaters = sorted(self.root.glob("*/updater.img_unpacked"))
        if not libs or not updaters:
            self.skipTest("no libupdatertalk.so or updater tree under A6400_UNPACKED_ROOT")
        self.lib = libs[0]
        self.updater = updaters[0]

    def test_the_key_is_the_sha256_of_the_empty_string(self) -> None:
        key = update_chain.aes_key_block(self.lib)
        self.assertIsNotNone(key, "the AES wrapper must be found in libupdatertalk.so")
        self.assertEqual(len(key), 16)
        self.assertEqual(key, hashlib.sha256(b"").digest()[:16])

    def test_the_checksum_tool_carries_no_crypto(self) -> None:
        tool = self.updater / "bin" / "uc_crc32sum.elf"
        if not tool.is_file():
            self.skipTest("uc_crc32sum.elf not present in this tree")
        surface = update_chain.crypto_surface(tool)
        self.assertFalse(surface["has_aes"], "the CRC32 tool must not carry AES")
        self.assertFalse(surface["has_signature"], "the CRC32 tool must not verify a signature")

    def test_no_updater_script_verifies_a_signature(self) -> None:
        rows = update_chain.updater_scripts(self.updater / "bin")
        self.assertTrue(rows, "the updater tree must contain scripts")
        signers = [r["name"] for r in rows if r["verifies_signature"]]
        self.assertEqual(signers, [], f"scripts verifying a signature: {signers}")
        self.assertTrue(any(r["verifies_checksum"] for r in rows),
                        "at least one script must check a checksum")


if __name__ == "__main__":
    unittest.main()
