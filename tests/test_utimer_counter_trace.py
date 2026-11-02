"""Constructed ARM controls validate rollover and unknown-MMIO handling."""
import struct
import unittest

from tools.research.utimer_counter_trace import execute


class CounterTraceTests(unittest.TestCase):
    def test_phase_changes_increment_only_on_high_to_low_transition(self):
        # Constructed ARM implementation of a phase bit and lower wrap count.
        words = [0xe1a0c00d, 0xe92dd800, 0xe24cb004, 0xe5913000,
                 0xe2000102, 0xe2032102, 0xe1500002, 0x0a000004,
                 0xe3520000, 0x13c33102, 0x03833102, 0x12833001,
                 0xe5813000, 0xe5910000, 0xe3c00102, 0xe89da800]
        code = struct.pack('<16I', *words)
        for counter, old, expected_count, expected_state in (
                (0, 0, 0, 0), (0x80000000, 0, 0, 0x80000000),
                (0xffffffff, 0x80000000, 0, 0x80000000),
                (0, 0x80000000, 1, 1), (0x80000000, 1, 1, 0x80000001),
                (0, 0x80000001, 2, 2)):
            with self.subTest(counter=counter, old=old):
                result = execute(code, counter, old)
                self.assertEqual(result['status'], 'isolated_function_return')
                self.assertEqual((result['r0'], result['state_after']), (expected_count, expected_state))

    def test_freerun_memory_is_not_mapped_or_zero_filled(self):
        code = struct.pack('<4I', 0xe59f3004, 0xe593010c, 0xe12fff1e, 0xf2403000)
        result = execute(code)
        self.assertEqual(result['status'], 'unsupplied_memory_boundary')
        self.assertEqual(result['boundary']['address'], 0xf240310c)
        self.assertEqual(result['hardware_values_supplied'], 0)
        with self.assertRaises(ValueError):
            execute(b'bad')


if __name__ == '__main__':
    unittest.main()
