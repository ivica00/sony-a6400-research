"""EXBL (nflashaB0) early-boot Unicorn harness tests (E0415).

Two layers:

* constructed: a synthetic EXBL container whose ARM program writes the
  boot-parameter block at 0x00103000 and reads one MMIO register.  This pins the
  harness mechanics (policy, hooks, stop reasons) without any device input.
* real dump: the read-only 2026-11-12 nflashaB0 image, skipped when the local
  dump is absent.  The strict policy must stop at the first MMIO write
  (0xf800000c, loader PC 0xfe04733c) and the opt-in observe-zero policy must
  collect the register map; neither run claims a booted loader.
"""
import struct
import unittest
from pathlib import Path

from src.a6400.execution.exbl_boot_harness import ExblBootHarness
from src.a6400.execution.exbl_image import (
    FIELD_OFFSETS,
    NFLASHA_B0_SHA256,
    NFLASHA_B0_SIZE,
    RECORD_SIZE,
    ExblImage,
)

ROOT = Path(__file__).resolve().parents[2]
DUMP = ROOT / 'artifacts/dumps/a6400-nflasha-readonly/nflashaB0-4194304.bin'

ENTRY = 0xFE040800
BOOT_PARAM = 0x00103000


def synthetic_exbl():
    """EXBL container with one segment holding a tiny ARM test program."""
    image = bytearray(0x1000)
    image[0:4] = b'EXBL'
    record = {
        'start': 4, 'size': 4,
        'load': 0xFE040800, 'entry': 0xFE040800,
        'awake_memaddr': 0xFE040000,
    }
    base = RECORD_SIZE
    for name, value in record.items():
        struct.pack_into('<I', image, base + FIELD_OFFSETS[name], value)
    # ARM program at file offset 0x800 (sector 4), load/entry 0xFE040800.
    program = struct.pack(
        '<6I',
        0xE59F0020,  # ldr r0, [pc, #0x20]  -> 0x28: 0x00103000
        0xE59F1020,  # ldr r1, [pc, #0x20]  -> 0x2c: 0x12345678
        0xE5801000,  # str r1, [r0]          boot-parameter write
        0xE59F201C,  # ldr r2, [pc, #0x1c]  -> 0x30: 0xF2000000
        0xE5923000,  # ldr r3, [r2]          MMIO read
        0xEAFFFFFE,  # b .                   (bounded by the instruction limit)
    )
    image[0x800:0x800 + len(program)] = program
    struct.pack_into('<3I', image, 0x828, BOOT_PARAM, 0x12345678, 0xF2000000)
    return ExblImage(bytes(image))


SMALL_MMIO = ((0xF2000000, 0xF2000FFF),)
SMALL_SRAM = (0xFE040000, 0xFE050000)


class SyntheticHarnessTests(unittest.TestCase):
    def test_strict_policy_stops_at_the_first_mmio_access(self):
        harness = ExblBootHarness(
            synthetic_exbl(), mmio_policy='stop', instruction_limit=1000,
            sram_window=SMALL_SRAM, mmio_ranges=SMALL_MMIO,
            low_ram=(0x00100000, 0x00110000),
            boot_param_window=(BOOT_PARAM, BOOT_PARAM + 0x100))
        report = harness.run()
        self.assertEqual(report['stop_reason'], 'mmio_access')
        self.assertEqual(report['stop_pc'], ENTRY + 0x10)
        self.assertEqual(report['counters']['mmio_reads'], 1)
        self.assertEqual(report['events']['boot_param_writes'][0]['address'], BOOT_PARAM)
        self.assertEqual(len(report['events']['boot_param_writes']), 1)
        self.assertEqual(report['events']['boot_param_writes'][0]['value'], 0x12345678)

    def test_observe_zero_policy_continues_until_the_instruction_limit(self):
        harness = ExblBootHarness(
            synthetic_exbl(), mmio_policy='observe-zero', instruction_limit=500,
            sram_window=SMALL_SRAM, mmio_ranges=SMALL_MMIO,
            low_ram=(0x00100000, 0x00110000),
            boot_param_window=(BOOT_PARAM, BOOT_PARAM + 0x100))
        report = harness.run()
        self.assertEqual(report['stop_reason'], 'instruction_limit')
        self.assertEqual(report['counters']['mmio_reads'], 1)
        self.assertEqual(report['counters']['boot_param_writes'], 1)
        self.assertEqual(report['mmio_addresses'][0]['address'], 0xF2000000)

    def test_unknown_policy_is_rejected(self):
        with self.assertRaises(ValueError):
            ExblBootHarness(synthetic_exbl(), mmio_policy='fabricate',
                            sram_window=SMALL_SRAM, mmio_ranges=SMALL_MMIO)


@unittest.skipUnless(DUMP.is_file(), 'nflashaB0 read-only dump not present')
class RealLoaderHarnessTests(unittest.TestCase):
    def setUp(self):
        self.exbl = ExblImage.from_path(DUMP, expected_size=NFLASHA_B0_SIZE,
                                        expected_sha256=NFLASHA_B0_SHA256)

    def test_strict_stop_at_first_mmio_register_access(self):
        report = ExblBootHarness(self.exbl, mmio_policy='stop').run()
        self.assertEqual(report['stop_reason'], 'mmio_access')
        self.assertEqual(report['stop_pc'], 0xFE04733C)
        self.assertEqual(report['counters']['mmio_writes'], 1)
        self.assertEqual(report['mmio_addresses'][0]['address'], 0xF800000C)
        self.assertEqual(report['mmio_addresses'][0]['last_value'], 0xFFFF)
        self.assertEqual(report['counters']['boot_param_writes'], 0)

    def test_observe_zero_collects_the_register_map_bounded(self):
        report = ExblBootHarness(self.exbl, mmio_policy='observe-zero',
                                 instruction_limit=100_000).run()
        self.assertIn(report['stop_reason'], ('instruction_limit', 'unmapped_access'))
        self.assertGreater(report['counters']['mmio_reads'], 500)
        self.assertGreater(report['counters']['mmio_writes'], 100)
        self.assertGreater(report['mmio_address_count'], 100)
        addresses = {entry['address'] for entry in report['mmio_addresses']}
        self.assertIn(0xF2000000, addresses)      # UART0 data/status
        self.assertIn(0xF200001C, addresses)      # UART0 control
        self.assertIn(0xF800000C, addresses)
        # The prefix does not reach the kernel boot-parameter block.
        self.assertEqual(report['counters']['boot_param_writes'], 0)
        self.assertEqual(report['boot_contract_references']
                         ['boot_mode_backup_record_0x0051000F'], [0x8E28])


if __name__ == '__main__':
    unittest.main()
