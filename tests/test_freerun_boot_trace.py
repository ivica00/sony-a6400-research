"""Constructed freerun setup preserves an already active timer."""
import struct
import unittest

from tools.research.freerun_boot_trace import ENTRY, KERNEL_BASE, REGISTER, execute


def fixture():
    raw = bytearray(0x19000)
    code = [0xe59f0028, 0xe5901000, 0xe59f2024, 0xe1510002,
            0x0a000005, 0xe3a01000, 0xe5801000, 0xe3a01011,
            0xe5801004, 0xe59f1008, 0xe5801000, 0xe1a0f00e,
            REGISTER, 0x1031]
    struct.pack_into('<14I', raw, ENTRY - KERNEL_BASE, *code)
    return bytes(raw)


class FreerunSetupTests(unittest.TestCase):
    def test_unknown_control_never_consumes_mapped_zeroes(self):
        result = execute(fixture())
        self.assertEqual(result['status'], 'unsupplied_runtime_read')
        self.assertEqual(result['boundary']['address'], REGISTER)
        self.assertEqual(result['writes'], [])

    def test_explicit_different_mode_observes_programming_without_counter_response(self):
        for value in (0, 0x1032):
            result = execute(fixture(), value)
            self.assertEqual(result['status'], 'isolated_function_return')
            self.assertEqual([(w['address'], w['value']) for w in result['writes']],
                             [(REGISTER, 0), (REGISTER + 4, 0x11), (REGISTER, 0x1031)])
            self.assertEqual(result['counter_values_supplied'], 0)

    def test_existing_selected_mode_is_preserved_without_stores(self):
        result = execute(fixture(), 0x1031)
        self.assertEqual(result['status'], 'isolated_function_return')
        self.assertEqual(result['writes'], [])
        with self.assertRaises(ValueError):
            execute(b'bad')


if __name__ == '__main__':
    unittest.main()
