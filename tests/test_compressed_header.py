"""Constructed ARM comparison and honest limits on header observations."""
import struct
import unittest

import unicorn

from tools.research.compressed_header import header_observation, execute_magic_comparison


def comparison_fixture():
    # ldr r3,literal; ldr r2,[r6]; cmp; mvnne r4,#21; bne rejection.
    return struct.pack('<9I', 0xe59f3018, 0xe5962000, 0xe1520003,
                       0x13e04015, 0x1a000000, 0xe12fff1e, 0xe12fff1e,
                       0xe1a00000, int.from_bytes(b'TPZL', 'little'))


class CompressedHeaderTests(unittest.TestCase):
    def execute(self, header, code=None):
        return execute_magic_comparison(code or comparison_fixture(), header,
                                         start=0, accepted=20, rejected=24)

    def test_comparison_takes_real_conditional_branches(self):
        for magic, expected, r4 in ((b'TPZL', 'magic_matches', 0),
                                    (bytes(4), 'magic_mismatch', 0xffffffea),
                                    (b'LZPT', 'magic_mismatch', 0xffffffea)):
            result = self.execute(magic + bytes(508))
            self.assertEqual(result['branch'], expected)
            self.assertEqual(result['r4'], r4)
            self.assertEqual(result['instructions_executed'], 5)
            self.assertEqual(result['kernel_responses_supplied'], 0)

    def test_magic_only_control_does_not_validate_image(self):
        data = b'TPZL' + bytes(508)
        observation = header_observation(data)
        self.assertTrue(observation['magic_matches_TPZL'])
        self.assertFalse(observation['complete_image_validated'])
        self.assertFalse(self.execute(data)['complete_image_validated'])

    def test_header_words_are_observations_not_allocations(self):
        data = struct.pack('<4s3I', b'TPZL', 0xffffffff, 0xfffffff0, 0xfffffffe)
        result = header_observation(data)
        self.assertEqual(result['block_shift_word'], 0xffffffff)
        self.assertEqual(result['table_offset_word'], 0xfffffff0)
        self.assertFalse(result['complete_image_validated'])

    def test_short_sector_and_bad_endpoints_rejected(self):
        with self.assertRaises(ValueError):
            self.execute(bytes(511))
        with self.assertRaises(ValueError):
            header_observation(bytes(15))
        for start, accepted, rejected in ((1, 20, 24), (0, 16, 24), (0, 20, 40)):
            with self.assertRaises(ValueError):
                execute_magic_comparison(comparison_fixture(), bytes(512), start, accepted, rejected)

    def test_loop_and_undeclared_branch_are_not_comparison_results(self):
        for opcode, message in ((0xeafffffe, 'exactly one declared boundary'),
                                 (0xea000005, 'left its declared instruction window')):
            code = bytearray(comparison_fixture())
            struct.pack_into('<I', code, 0, opcode)
            with self.assertRaisesRegex(ValueError, message):
                self.execute(bytes(512), bytes(code))

    def test_read_only_header_cannot_be_modified(self):
        code = bytearray(comparison_fixture())
        struct.pack_into('<I', code, 0, 0xe5862000)  # str r2,[r6]
        with self.assertRaises(unicorn.UcError):
            self.execute(bytes(512), bytes(code))
