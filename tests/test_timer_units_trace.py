"""Original-style argument construction stops before invoking division."""
import struct
import unittest

from tools.research.timer_units_trace import divisor_window


class TimerUnitsTests(unittest.TestCase):
    def test_immediate_divisor_is_constructed_without_calling_helper(self):
        code = struct.pack('<3I', 0xe30023e8, 0xe3a03000, 0xeafffffe)
        result = divisor_window(code, 0, 8)
        self.assertEqual(result['status'], 'division_call_boundary')
        self.assertEqual(result['divisor_argument'], 1000)
        self.assertFalse(result['division_executed'])

    def test_literal_divisor_uses_only_supplied_bytes(self):
        code = struct.pack('<4I', 0xe59f2004, 0xe3a03000, 0xeafffffe, 1000000)
        result = divisor_window(code, 0, 8)
        self.assertEqual(result['status'], 'division_call_boundary')
        self.assertEqual(result['divisor_argument'], 1000000)
        self.assertEqual(result['r3'], 0)

    def test_mapped_padding_and_unaligned_ranges_are_not_accepted(self):
        code = struct.pack('<4I', 0xe59f2008, 0xe3a03000, 0xeafffffe, 1000000)
        result = divisor_window(code, 0, 8)
        self.assertEqual(result['status'], 'unsupplied_data_read')
        self.assertFalse(result['division_executed'])
        with self.assertRaises(ValueError):
            divisor_window(code, 1, 8)


if __name__ == '__main__':
    unittest.main()
