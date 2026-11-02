"""A mapped register page never supplies hardware values implicitly."""
import struct
import unittest

from tools.research.dmm_timer_program import observe_programming, ENTRY, KERNEL_BASE


POINTERS = [0xf2403500 + index * 0x100 for index in range(4)]


def fixture(instructions):
    raw = bytearray(0x3b7000)
    struct.pack_into('<' + 'I' * len(instructions), raw, ENTRY - KERNEL_BASE, *instructions)
    struct.pack_into('<I', raw, 0x60124d74 - KERNEL_BASE, POINTERS[0])
    return bytes(raw)


class TimerProgrammingTests(unittest.TestCase):
    def test_written_register_read_still_requires_device_semantics(self):
        raw = fixture([0xe59f1080, 0xe3a00032, 0xe5810000, 0xe5910000])
        result = observe_programming(raw, POINTERS)
        self.assertEqual(result['status'], 'unsupplied_data_read')
        self.assertEqual(result['boundary']['address'], POINTERS[0])
        self.assertEqual([w['value'] for w in result['register_writes']], [0x32])
        self.assertEqual(result['hardware_reads_supplied'], 0)

    def test_other_register_store_is_not_accepted(self):
        raw = fixture([0xe59f1080, 0xe3a00032, 0xe5810008])
        result = observe_programming(raw, POINTERS)
        self.assertEqual(result['status'], 'unsupported_data_write')
        self.assertEqual(result['boundary']['address'], POINTERS[0] + 8)
        self.assertEqual(result['register_writes'], [])

    def test_bad_channel_set_and_truncated_code_are_rejected(self):
        for pointers in (POINTERS[:3], [POINTERS[0]] * 4, [1, 2, 3, 4]):
            with self.assertRaises(ValueError):
                observe_programming(fixture([]), pointers)
        with self.assertRaises(ValueError):
            observe_programming(b'bad', POINTERS)


if __name__ == '__main__':
    unittest.main()
