"""Constructed timer code must stop before unsupplied runtime pointers."""
import struct
import unittest

from tools.research.dmm_runtime_trace import KERNEL_BASE, TIMER_NAME, export_address, timer_window


def fixture():
    data = bytearray(4096)
    words = [0xe1a0c00d, 0xe92dd800, 0xe24cb004, 0xe3500003,
             0x9a000002, 0xeb000017, 0, 0, 0xe3a03014, 0xe0000093,
             0xe59f3008, 0xe7933000, 0xe593000c, 0xe89da800, KERNEL_BASE + 0x200]
    struct.pack_into('<15I', data, 0x40, *words)
    data[0x300:0x300 + len(TIMER_NAME)] = TIMER_NAME
    struct.pack_into('<II', data, 0x380, KERNEL_BASE + 0x40, KERNEL_BASE + 0x300)
    return bytes(data)


class TimerRuntimeTests(unittest.TestCase):
    def test_export_requires_unique_aligned_pair(self):
        raw = fixture()
        self.assertEqual(export_address(raw, TIMER_NAME)['address'], KERNEL_BASE + 0x40)
        changed = bytearray(raw)
        struct.pack_into('<II', changed, 0x390, KERNEL_BASE + 0x80, KERNEL_BASE + 0x300)
        with self.assertRaisesRegex(ValueError, 'ambiguous'):
            export_address(bytes(changed), TIMER_NAME)
        with self.assertRaisesRegex(ValueError, 'missing'):
            export_address(raw, b'absent\0')

    def test_static_zero_table_is_not_initialized_runtime_pointer(self):
        result = timer_window(fixture(), KERNEL_BASE + 0x40)
        self.assertEqual(result['status'], 'unsupplied_timer_runtime_read')
        self.assertEqual(result['boundary']['address'], KERNEL_BASE + 0x200)
        self.assertEqual(result['responses_supplied'], 0)
        self.assertEqual(result['boundary']['pc'], KERNEL_BASE + 0x40 + 44)

    def test_export_name_does_not_match_suffix_of_another_symbol(self):
        raw = bytearray(fixture())
        other = b'prefix_' + TIMER_NAME
        raw[0x500:0x500 + len(other)] = other
        self.assertEqual(export_address(bytes(raw), TIMER_NAME)['address'], KERNEL_BASE + 0x40)

    def test_cpu_selects_twenty_byte_slot_without_supplying_it(self):
        result = timer_window(fixture(), KERNEL_BASE + 0x40, cpu=3)
        self.assertEqual(result['boundary']['address'], KERNEL_BASE + 0x200 + 60)
        self.assertEqual(result['status'], 'unsupplied_timer_runtime_read')

    def test_invalid_cpu_leaves_window_instead_of_fabricating_error_return(self):
        result = timer_window(fixture(), KERNEL_BASE + 0x40, cpu=4)
        self.assertEqual(result['status'], 'unsupported_control_flow')
        with self.assertRaises(ValueError):
            timer_window(b'bad', KERNEL_BASE)

    def test_selected_pointer_never_maps_or_supplies_hardware_register(self):
        # A full-size constructed image contains the explicitly selected slot.
        raw = fixture() + bytes(0x3b7000 - len(fixture()))
        result = timer_window(raw, KERNEL_BASE + 0x40, selected_pointer=0xf2403500)
        # This fixture's literal intentionally names a different table, so
        # the explicit selection must not relax other unknown-data reads.
        self.assertEqual(result['status'], 'unsupplied_timer_runtime_read')
        changed = bytearray(raw)
        struct.pack_into('<I', changed, 0x40 + 56, 0x604be020)
        result = timer_window(bytes(changed), KERNEL_BASE + 0x40, selected_pointer=0xf2403500)
        self.assertEqual(result['status'], 'unmapped_memory_boundary')
        self.assertEqual(result['boundary']['address'], 0xf240350c)
        self.assertEqual(result['responses_supplied'], 0)


if __name__ == '__main__':
    unittest.main()
