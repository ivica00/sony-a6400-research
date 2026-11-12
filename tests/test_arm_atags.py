"""Constructed checks for the ARM ATAGS boot contract (E0416)."""
import struct
import unittest

from src.a6400.execution.arm_atags import (
    ATAG_CMDLINE,
    ATAG_CORE,
    ATAG_MEM,
    ATAG_NONE,
    AtagsError,
    atags_receipt,
    build_atags,
    parse_atags,
    parse_mem_parameters,
    parse_size,
)

OBSERVED_CMDLINE = (
    'kemco ip=off initrd=0x00700000,0x00800000 root=/dev/ram0 rw noatime noalign '
    'init=/sbin/init console=ttyAM0,115200n8 mem=1G@0 memrsv=1M@0 '
    'memrsv=0x75e000@0x02E68000 memrsv=0x20000000@0x20000000:uc '
    'mem=1016M@0x80000000@1')


class SizeAndMemoryTests(unittest.TestCase):
    def test_parse_size_units(self):
        self.assertEqual(parse_size('1G'), 0x40000000)
        self.assertEqual(parse_size('1016M'), 1016 * 1024 * 1024)
        self.assertEqual(parse_size('0x1000'), 0x1000)
        self.assertEqual(parse_size('16K'), 16 * 1024)
        with self.assertRaises(AtagsError):
            parse_size('')
        with self.assertRaises(AtagsError):
            parse_size('-1M')

    def test_observed_mem_options(self):
        records = parse_mem_parameters(OBSERVED_CMDLINE)
        banks = [record for record in records if not record.get('reserved')]
        reserved = [record for record in records if record.get('reserved')]
        self.assertEqual([(bank['start'], bank['size']) for bank in banks],
                         [(0, 0x40000000), (0x80000000, 1016 * 1024 * 1024)])
        self.assertEqual(len(reserved), 3)
        self.assertEqual(reserved[2]['attributes'], ['uc'])

    def test_malformed_mem_option_is_an_error(self):
        with self.assertRaises(AtagsError):
            parse_mem_parameters('mem=1G')
        with self.assertRaises(AtagsError):
            parse_mem_parameters('mem=zz@0')


class AtagsBuildParseTests(unittest.TestCase):
    def test_round_trip_with_observed_banks(self):
        blob = build_atags('console=ttyAM0 mem=1G@0 mem=1016M@0x80000000@1',
                           [(0, 0x40000000), (0x80000000, 1016 * 1024 * 1024)])
        self.assertEqual(len(blob) % 4, 0)
        tags = parse_atags(blob)
        self.assertEqual([tag['tag'] for tag in tags],
                         [ATAG_CORE, ATAG_MEM, ATAG_MEM, ATAG_CMDLINE, ATAG_NONE])
        self.assertEqual([(tag['start'], tag['bytes'])
                          for tag in tags if tag['tag'] == ATAG_MEM],
                         [(0, 0x40000000), (0x80000000, 1016 * 1024 * 1024)])
        self.assertEqual(tags[3]['cmdline'],
                         'console=ttyAM0 mem=1G@0 mem=1016M@0x80000000@1')
        receipt = atags_receipt(blob)
        self.assertEqual(receipt['address'], 0x00103000)
        self.assertEqual(len(receipt['memory_banks']), 2)
        self.assertEqual(receipt['tags'][-1]['tag'], ATAG_NONE)

    def test_cmdline_padding_is_included_in_the_tag_size(self):
        blob = build_atags('abcd', [(0, 0x1000)])
        receipt = atags_receipt(blob)
        cmdline = [tag for tag in receipt['tags'] if tag['tag'] == ATAG_CMDLINE][0]
        # 5 bytes payload -> padded to 8 -> 2 header words + 2 payload words.
        self.assertEqual(cmdline['size'], 4)

    def test_invalid_contract_is_rejected(self):
        with self.assertRaises(AtagsError):
            build_atags('x', [])
        with self.assertRaises(AtagsError):
            build_atags('x', [(0, 0)])
        with self.assertRaises(AtagsError):
            build_atags('x', [(0xFFFFFFFF, 0x1000)])
        with self.assertRaises(AtagsError):
            parse_atags(struct.pack('<2I', 1, ATAG_CORE))

    def test_missing_terminator_is_an_error(self):
        blob = build_atags('x', [(0, 0x1000)])
        with self.assertRaises(AtagsError):
            parse_atags(blob[:-8])

    def test_oversized_tag_list_is_rejected(self):
        blob = build_atags('x' * 64, [(0, 0x1000)])
        with self.assertRaises(AtagsError):
            parse_atags(blob, limit=16)


if __name__ == '__main__':
    unittest.main()
