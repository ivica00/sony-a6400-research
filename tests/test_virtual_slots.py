"""Static vtable candidates must have explicit bounds and relocation support."""
import unittest

from tools.research.updater_trace import virtual_slot


class VirtualSlotTests(unittest.TestCase):
    def table(self, **changes):
        row = {'offset': 44, 'relocation_type': 2, 'addend': 0,
               'symbol': 'read_without_copy', 'symbol_value': 0x1001, **changes}
        return {'size': 60, 'relocations': [row]}

    def test_dispatch_uses_address_point_plus_offset(self):
        result = virtual_slot(self.table(), 8, 0x24)
        self.assertEqual(result['table_offset'], 44)
        self.assertEqual(result['candidate_symbol'], 'read_without_copy')
        self.assertFalse(result['runtime_dispatch_observed'])

    def test_missing_duplicate_adjusted_and_wrong_relocations_rejected(self):
        for table in (self.table(offset=48), self.table(relocation_type=21), self.table(addend=4)):
            with self.assertRaises(ValueError):
                virtual_slot(table, 8, 0x24)
        table = self.table()
        table['relocations'] *= 2
        with self.assertRaises(ValueError):
            virtual_slot(table, 8, 0x24)

    def test_dispatch_cannot_escape_or_misalign_table(self):
        for point, offset in ((-4, 40), (8, -4), (8, 53), (8, 52)):
            with self.assertRaises(ValueError):
                virtual_slot(self.table(), point, offset)
