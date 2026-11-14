"""Constructed fixture tests for backup boot arguments, address conversion, and write path."""
import struct
import unittest

import unicorn
from unicorn import arm_const as arm

from tools.research.liro_startup_trace import BASE, run_slice
from tools.research.backup_boot_trace import (
    execute_arch_phys_to_cache,
    execute_backupfile_unpack,
    extract_init_backup_options,
)


def make_header_fixture(pa: int, cookie: int = 0xAAAAAAAA, magic: bytes = b"BK4\0") -> bytes:
    raw = bytearray(0x100)
    struct.pack_into("<I", raw, 0, pa)
    struct.pack_into("<I", raw, 4, cookie)
    raw[12:16] = magic
    return bytes(raw)


def _require_checked_input(
    test_case: unittest.TestCase, inventory_file: str, collection_key: str, rel_path: str
) -> bytes:
    import json
    from project_paths import PROJECT_ROOT
    from tools.research.mount_evidence import checked_input

    inv_path = PROJECT_ROOT / "artifacts/inventory" / inventory_file
    if not inv_path.is_file() or not (PROJECT_ROOT / rel_path).is_file():
        test_case.skipTest(f"Local firmware input not present: {rel_path}")
    rows = json.loads(inv_path.read_text(encoding="utf-8"))[collection_key]
    hashes = {row["path"]: row["sha256"] for row in rows}
    return checked_input(PROJECT_ROOT, rel_path, hashes[rel_path])


def _require_baseline_input(test_case: unittest.TestCase, rel_path: str) -> bytes:
    return _require_checked_input(test_case, "baseline.json", "inputs", rel_path)


def _require_elf_inventory_input(test_case: unittest.TestCase, rel_path: str) -> bytes:
    return _require_checked_input(test_case, "elf-inventory.json", "entries", rel_path)


class BackupBootOptionsTests(unittest.TestCase):
    def test_extract_init_backup_options(self):
        opts = extract_init_backup_options()
        self.assertEqual(opts["module"], "/usr/kmod/backup.ko")
        self.assertIn("Backup_load=0", opts["options"])
        self.assertEqual(opts["backup_load_parsed"], 0)


class ArchPhysToCacheTests(unittest.TestCase):
    def setUp(self):
        # Synthetic minimal arch_phys_to_cache ARM routine matching original vmlinux.bin:
        # 0x00: mov ip, sp
        # 0x04: push {r3, r4, fp, ip, lr, pc}
        # 0x08: sub fp, ip, #4
        # 0x0c: subs r2, r0, #0
        # 0x10: bne +0x14 (to 0x2c)
        # 0x14: b +0x18
        # 0x18: ...
        # 0x2c: ldr r3, [pc, #0x18]  (loads pointer from 0x4c)
        # 0x30: ldr r1, [r3]          (loads limit 0x40000000)
        # 0x34: cmp r2, r1
        # 0x38: addlo r2, r2, #0x60000000
        # 0x3c: blo +0x04 (to 0x44)
        # 0x40: b error_path
        # 0x44: mov r0, r2
        # 0x48: ldm sp, {r3, r4, fp, sp, pc}
        # 0x4c: literal pointer
        pass

    def test_preset_pa_conversion(self):
        kernel_raw = _require_baseline_input(
            self,
            "firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked/vmlinux.bin",
        )

        # Test preset PA: 0x02e80000 -> 0x62e80000
        result = execute_arch_phys_to_cache(kernel_raw, 0x02E80000)
        self.assertEqual(result["status"], "normal_return_boundary")
        self.assertEqual(result["output_va"], "0x62e80000")
        self.assertEqual(result["instructions_executed"], 11)

    def test_liro_pa_conversion(self):
        kernel_raw = _require_baseline_input(
            self,
            "firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked/vmlinux.bin",
        )

        # Test LIRO PA: 0x035c6000 -> 0x635c6000
        result = execute_arch_phys_to_cache(kernel_raw, 0x035C6000)
        self.assertEqual(result["status"], "normal_return_boundary")
        self.assertEqual(result["output_va"], "0x635c6000")


class BackupfileInitSliceTests(unittest.TestCase):
    def test_load_flag_0_skips_reload_and_reaches_data_init(self):
        module_raw = _require_elf_inventory_input(
            self,
            "firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/kmod/backup.ko",
        )

        hdr = make_header_fixture(0x02E80000)
        result = execute_backupfile_unpack(module_raw, hdr, load_flag=0)
        self.assertEqual(result["status"], "reached_data_init_boundary")
        self.assertEqual(result["unpacked_r0_r4"], "0x62e80000")

    def test_load_flag_1_branches_to_reload_path(self):
        module_raw = _require_elf_inventory_input(
            self,
            "firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/kmod/backup.ko",
        )

        hdr = make_header_fixture(0x02E80000)
        result = execute_backupfile_unpack(module_raw, hdr, load_flag=1)
        self.assertEqual(result["status"], "reached_load_file_reload_boundary")
        self.assertEqual(result["unpacked_r0_r4"], "0x62e80000")

    def test_bad_cookie_rejects_header(self):
        module_raw = _require_elf_inventory_input(
            self,
            "firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/kmod/backup.ko",
        )

        # Wrong cookie
        hdr = make_header_fixture(0x02E80000, cookie=0x12345678)
        result = execute_backupfile_unpack(module_raw, hdr, load_flag=0)
        # Bad cookie branches to exit, r4 remains 0
        self.assertEqual(result["unpacked_r0_r4"], "0x0")


class BackupWriteCoreParameterTests(unittest.TestCase):
    def test_subsystem_mismatch_rejected_with_error(self):
        # Slice from Backup_write_core:
        # 0x00: cmp r0, r1, lsr #16
        # 0x04: beq valid
        # 0x08: mvn r0, #3  (returns -4 = 0xfffffffc)
        # 0x0c: bx lr
        # 0x10: valid: mov r0, #0; bx lr
        code = bytes.fromhex("210850e1 0100000a 0300e0e3 1eff2fe1 0000a0e3 1eff2fe1")
        report, _ = run_slice(
            code,
            0,
            [(0, len(code))],
            {0x0C: "error_return", 0x14: "valid_return"},
            {arm.UC_ARM_REG_R0: 0x3E, arm.UC_ARM_REG_R1: 0x0040000B},  # mismatch: 0x3e != 0x40
        )
        self.assertEqual(report["status"], "error_return")
        self.assertEqual(report["registers"]["r0"], 0xFFFFFFFC)

    def test_subsystem_match_accepted(self):
        code = bytes.fromhex("210850e1 0100000a 0300e0e3 1eff2fe1 0000a0e3 1eff2fe1")
        report, _ = run_slice(
            code,
            0,
            [(0, len(code))],
            {0x0C: "error_return", 0x14: "valid_return"},
            {arm.UC_ARM_REG_R0: 0x3E, arm.UC_ARM_REG_R1: 0x003E000B},  # match: 0x3e == 0x3e
        )
        self.assertEqual(report["status"], "valid_return")
        self.assertEqual(report["registers"]["r0"], 0)


if __name__ == "__main__":
    unittest.main()
