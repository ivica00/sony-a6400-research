import hashlib
import struct
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from tools.research.bionzx_machine_map import (
    KERNEL_BASE, call_arguments, checked_bytes, checked_path, mmio_contract,
    mount_configuration, partition_configuration, prefix_replay,
)

ROOT = Path(__file__).resolve().parents[1]


class PackageGeometryTests(unittest.TestCase):
    def test_partition_and_mount_names_preserve_distinct_roles(self):
        mounts = mount_configuration("/dev/nflasha2 /setting vfat 4096 512\n")
        partitions = partition_configuration("# /dev/nflasha2\n0x1000,0x1000,1,0xffffffff\n")
        self.assertEqual(mounts[0]["bytes"], partitions[0]["bytes"])
        self.assertEqual(mounts[0]["mount"], "/setting")
        self.assertEqual(partitions[0]["start"], 4096)

    def test_overlapping_partitions_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "Overlapping"):
            partition_configuration(
                "# /dev/nflasha1\n0x1000,0x2000,1,0\n"
                "# /dev/nflasha2\n0x2000,0x1000,1,0\n")

    def test_unlabeled_partition_and_duplicate_mount_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "device label"):
            partition_configuration("0,4096,1,0")
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            mount_configuration("/dev/nflasha1 none vfat 4096 512\n" * 2)


class StaticMmioTests(unittest.TestCase):
    def image(self):
        raw = bytearray(0x200)
        struct.pack_into("<4I", raw, 0,
                         0xE59F0018,   # ldr r0, [pc, #24]: map table
                         0xE3A01001,   # mov r1, #1
                         0xEB00003C,   # bl iotable_init at +0x100
                         0xE12FFF1E)
        struct.pack_into("<I", raw, 0x20, KERNEL_BASE + 0x80)
        struct.pack_into("<4I", raw, 0x80, 0xF8800000, 0xBF800, 0x100000, 0)
        struct.pack_into("<7I", raw, 0x40,
                         0xE3A00000, 0xE3A0101D, 0xE59F2010, 0xE59F3010,
                         0xEB000032, 0xE12FFF1E, 0)
        struct.pack_into("<2I", raw, 0x60, 0xF8001000, 0xF8000100)
        symbols = {"cxd900x0_map_io": KERNEL_BASE,
                   "cxd900x0_init_irq": KERNEL_BASE + 0x40,
                   "iotable_init": KERNEL_BASE + 0x100,
                   "gic_init": KERNEL_BASE + 0x120}
        return raw, symbols

    def test_nonidentity_io_mapping_and_gic_arguments_are_preserved(self):
        raw, symbols = self.image()
        report = mmio_contract(bytes(raw), symbols)
        self.assertEqual(report["mappings"][0]["virtual"], 0xF8800000)
        self.assertEqual(report["mappings"][0]["physical"], 0xBF800000)
        self.assertEqual(report["gic_setup"]["registers"]["r2"], 0xF8001000)
        self.assertEqual(report["gic_setup"]["registers"]["r3"], 0xF8000100)

    def test_branch_dependent_arguments_are_not_treated_as_constants(self):
        raw, symbols = self.image()
        struct.pack_into("<I", raw, 0, 0x0A000001)
        with self.assertRaisesRegex(ValueError, "Nonlinear"):
            call_arguments(bytes(raw), symbols, "cxd900x0_map_io", "iotable_init")


class InputIdentityTests(unittest.TestCase):
    def test_changed_hash_and_escaped_path_are_rejected(self):
        directory = ROOT / "artifacts" / "tests"
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="machine-map-", dir=directory) as tmp:
            root = Path(tmp)
            path = root / "input.bin"
            path.write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                checked_bytes(path, hashlib.sha256(b"original").hexdigest())
            with self.assertRaisesRegex(ValueError, "escapes"):
                checked_path(root, Path("..") / "undeclared")


class KernelPrefixTests(unittest.TestCase):
    def fixture(self):
        from tests.emulator.test_unicorn_machine import synthetic_kernel_program
        return SimpleNamespace(
            banks=[(0, 0x40000000)], raw_kernel=synthetic_kernel_program(),
            initrd=b"\0" * 64, sony_payload=b"kemco\0",
            machine=SimpleNamespace(machine_id=0xDA9),
            load_addresses={"kernel_load": 0x8000, "initrd_load": 0x700000,
                            "boot_params": 0x103000})

    def test_strict_prefix_stops_before_replying_to_mmio(self):
        report = prefix_replay(self.fixture(), limit=100)
        self.assertEqual(report["stop"]["reason"], "unmapped_access")
        self.assertEqual(report["stop"]["address"], 0xF2000018)
        self.assertEqual(report["serial_hex"], "")

    def test_explicit_uart_allows_serial_but_other_mmio_still_stops(self):
        report = prefix_replay(self.fixture(), limit=100, uart_base=0xF2000000)
        self.assertEqual(bytes.fromhex(report["serial_hex"]), b"AB")
        self.assertEqual(report["stop"]["address"], 0xDEAD0000)
        self.assertEqual(report["stop"]["reason"], "unmapped_access")

    def test_unknown_uart_read_is_not_returned_as_zero(self):
        contract = self.fixture()
        raw = bytearray(contract.raw_kernel)
        struct.pack_into("<I", raw, 8, 0xE5904050)  # UART +0x50 is not served.
        contract.raw_kernel = bytes(raw)
        report = prefix_replay(contract, limit=100, uart_base=0xF2000000)
        self.assertEqual(report["stop"]["reason"], "unsupported_uart_register")
        self.assertEqual(report["stop"]["address"], 0xF2000050)
        self.assertEqual(report["serial_hex"], "")

    def test_error_clear_write_does_not_hide_the_next_unknown_register(self):
        contract = self.fixture()
        raw = bytearray(contract.raw_kernel)
        struct.pack_into("<I", raw, 8, 0xE5804004)  # ECR write, no pending RX errors.
        struct.pack_into("<I", raw, 12, 0xE5904050)
        contract.raw_kernel = bytes(raw)
        report = prefix_replay(contract, limit=100, uart_base=0xF2000000)
        self.assertTrue(report["mmio"][0]["supported"])
        self.assertEqual(report["stop"]["address"], 0xF2000050)
