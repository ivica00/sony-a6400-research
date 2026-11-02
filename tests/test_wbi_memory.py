"""Constructed WBI/LZ77 fixtures check bounds, references and sparse memory."""
import struct
import unittest

from tools.research.wbi_memory import inflate_block, parse_sections, decode_section
from tools.research.wbi_logging_trace import PackageMemory, records, cached_physical


def fixture(segments):
    blocks, entries = [], []
    for address, content in segments:
        block = b'\x0f\0' + struct.pack('<H', len(content)) + content
        virtual = address + 0x60000000
        entries.append(struct.pack('<8I', address, len(block), 0x0f0f0f0f, 0,
                       len(content), virtual, 0, address ^ len(block) ^ len(content) ^ virtual))
        blocks.append(block)
    payload = b''.join(blocks)
    head = struct.pack('<4s10I', b'WBI1', len(segments), 9, 0x1000, 0x20060224, 512,
                       len(payload), 0, 0, 0x0f0f0f0f, sum(len(c) for _, c in segments))
    return head + bytes(512 - len(head)) + payload + b''.join(entries)


class WbiMemoryTests(unittest.TestCase):
    def test_raw_and_overlapping_lz77_references_decode_with_exact_consumption(self):
        self.assertEqual(inflate_block(b'\x0f\0\x03\0abc', 0, 3), (b'abc', 7))
        self.assertEqual(inflate_block(b'\xf0\x06A\0\x01\0\0', 0, 4), (b'AAAA', 7))

    def test_truncation_invalid_backrefs_and_output_overflow_stop(self):
        for data, maximum in ((b'\x0f\0\x03\0ab', 3), (b'\x0f\0\x03\0abc', 2),
                              (b'\xf0\x01\0\x01', 10), (b'\xf0\0abcdefgh', 100)):
            with self.subTest(data=data):
                with self.assertRaises(ValueError):
                    inflate_block(data, 0, maximum)
        for position, maximum in ((-1, 4), (99, 4), (0, 0), (0, 4 * 1024 * 1024 + 1)):
            with self.assertRaises(ValueError):
                inflate_block(b'\x0f\0\x01\0A', position, maximum)

    def test_section_lengths_and_original_aggregate_must_agree(self):
        raw = fixture([(0x1000, b'abcd')])
        header, sections = parse_sections(raw)
        self.assertEqual(header['expanded_size'], 4)
        self.assertTrue(sections[0]['metadata_xor_matches'])
        self.assertEqual(decode_section(raw, sections[0]), (b'abcd', 1, 8))
        changed = bytearray(raw)
        struct.pack_into('<I', changed, 40, 5)
        with self.assertRaisesRegex(ValueError, 'aggregate'):
            parse_sections(bytes(changed))
        with self.assertRaises(ValueError):
            parse_sections(raw[:40])

    def test_adjacent_sections_are_stitched_but_gaps_never_supply_zeroes(self):
        memory = PackageMemory(fixture([(0x1000, b'abcd'), (0x1004, b'ef')]))
        self.assertEqual(memory.read(0x1001, 4), b'bcde')
        memory = PackageMemory(fixture([(0x1000, b'ab'), (0x1004, b'cd')]))
        with self.assertRaisesRegex(ValueError, 'Unsupplied'):
            memory.read(0x1000, 6)
        with self.assertRaisesRegex(ValueError, 'overlapping'):
            PackageMemory(fixture([(0x1000, b'ab'), (0x1001, b'cd')]))

    def test_logging_tags_require_complete_ranges_and_supported_pointer_mapping(self):
        data = struct.pack('<I4sII', 16, b'LOGB', 0x3000000, 0x10000)
        self.assertEqual(records(data)[0]['tag'], 'LOGB')
        self.assertEqual(cached_physical(0x63000000), 0x03000000)
        for invalid in (data[:-1], struct.pack('<I4s', 4, b'LOGB')):
            with self.assertRaises(ValueError):
                records(invalid)
        with self.assertRaises(ValueError):
            cached_physical(0x1234)


if __name__ == '__main__':
    unittest.main()
