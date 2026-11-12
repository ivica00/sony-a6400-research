"""Constructed checks for the EXBL boot-container parser (E0415)."""
import struct
import unittest
from pathlib import Path

from src.a6400.execution.exbl_image import (
    BLOCK_SIZE,
    DEFAULT_LOAD_BASE,
    EXBL_MAGIC,
    FIELD_OFFSETS,
    NFLASHA_B0_SHA256,
    NFLASHA_B0_SIZE,
    RECORD_SIZE,
    ExblError,
    ExblImage,
)

ROOT = Path(__file__).resolve().parents[1]
DUMP = ROOT / 'artifacts/dumps/a6400-nflasha-readonly/nflashaB0-4194304.bin'


def make_block(records, image_size=0x2000):
    image = bytearray(image_size)
    image[0:4] = b'EXBL'
    for index, fields in enumerate(records):
        base = RECORD_SIZE * (index + 1)
        for name, value in fields.items():
            struct.pack_into('<I', image, base + FIELD_OFFSETS[name], value)
    return bytes(image)


class ExblParserTests(unittest.TestCase):
    def test_parses_records_segments_and_mapping(self):
        image = make_block([
            {'start': 4, 'size': 8, 'load': DEFAULT_LOAD_BASE + 0x800,
             'entry': DEFAULT_LOAD_BASE + 0x800, 'awake_memaddr': DEFAULT_LOAD_BASE},
            {'start': 12, 'size': 4, 'load': DEFAULT_LOAD_BASE + 0x1800},
        ])
        exbl = ExblImage(image)
        self.assertEqual(exbl.load_base, DEFAULT_LOAD_BASE)
        self.assertEqual(exbl.entry, DEFAULT_LOAD_BASE + 0x800)
        self.assertEqual([record.index for record in exbl.segments], [0, 1])
        self.assertEqual(exbl.records[0].flash_offset, 0x800)
        self.assertEqual(exbl.extent_bytes, 0x2000)
        self.assertEqual(exbl.payload_bytes, (8 + 4) * 512)
        self.assertTrue(exbl.mapping_consistent())
        self.assertEqual(exbl.segment_data(0), image[0x800:0x1800])

    def test_magic_is_required(self):
        image = bytearray(make_block([{'start': 4, 'size': 1}]))
        image[1] = 0
        with self.assertRaises(ExblError):
            ExblImage(bytes(image))

    def test_record_must_fit_the_partition(self):
        image = make_block([{'start': 12, 'size': 8}], image_size=0x2000)
        with self.assertRaises(ExblError):
            ExblImage(image)

    def test_short_image_is_rejected(self):
        with self.assertRaises(ExblError):
            ExblImage(bytes(BLOCK_SIZE - 4))

    def test_identity_mismatch_is_rejected(self):
        image = make_block([{'start': 4, 'size': 1}], image_size=0x1000)
        with self.assertRaises(ExblError):
            ExblImage.from_path(__file__)  # not an EXBL dump at all

    def test_inconsistent_load_mapping_is_reported_not_hidden(self):
        image = make_block([{'start': 4, 'size': 2, 'load': 0xFE040000 + 0x1000}])
        exbl = ExblImage(image)
        self.assertFalse(exbl.mapping_consistent())
        self.assertFalse(exbl.records[0].mapping_consistent)

    def test_boot_contract_tokens(self):
        image = bytearray(make_block([{'start': 4, 'size': 1}]))
        image[0x1200:0x1204] = struct.pack('<I', 0x0051000F)
        image[0x1210:0x121E] = b'BOM:<<BootMode:'
        tokens = ExblImage(bytes(image)).boot_contract_references()
        self.assertEqual(tokens['boot_mode_backup_record_0x0051000F'], [0x1200])
        self.assertEqual(tokens['boot_mode_log_string'], [0x1210])


@unittest.skipUnless(DUMP.is_file(), 'nflashaB0 read-only dump not present')
class ExblRealDumpTests(unittest.TestCase):
    def setUp(self):
        self.exbl = ExblImage.from_path(DUMP, expected_size=NFLASHA_B0_SIZE,
                                        expected_sha256=NFLASHA_B0_SHA256)

    def test_observed_container_layout(self):
        self.assertEqual(self.exbl.load_base, 0xFE040000)
        self.assertEqual(self.exbl.entry, 0xFE047000)
        self.assertEqual(self.exbl.extent_bytes, 0x2C000)
        self.assertEqual([record.index for record in self.exbl.segments],
                         [0, 1, 2, 3, 4, 5])
        self.assertTrue(self.exbl.mapping_consistent())

    def test_observed_record_zero_fields(self):
        record = self.exbl.records[0]
        self.assertEqual(record.start, 0x38)
        self.assertEqual(record.size, 0x100)
        self.assertEqual(record.load, 0xFE047000)
        self.assertEqual(record.awake_memaddr, 0xFE040000)
        self.assertEqual(record.awake_loadsize, 0x27800)
        self.assertEqual(record.bp_entry, 0xFE047000)
        self.assertEqual(record.awake_cmd0disable, 1)

    def test_boot_contract_references_are_present_in_the_payload(self):
        tokens = self.exbl.boot_contract_references()
        self.assertEqual(tokens['boot_mode_backup_record_0x0051000F'], [0x8E28])
        self.assertEqual(tokens['boot_mode_log_string'], [0x8E34])
        self.assertIn(0x8E7C, tokens['updater_mode_path'])
        self.assertIn(0x8E60, tokens['fat_mount_string'])
        self.assertNotIn(b'LDR_BOOT', self.exbl.image[:0x27800])


if __name__ == '__main__':
    unittest.main()
