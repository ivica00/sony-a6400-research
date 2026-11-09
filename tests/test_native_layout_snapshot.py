import struct
import unittest
from tools.research.decode_native_layout_snapshot import decode

class NativeLayoutSnapshotTests(unittest.TestCase):
    def test_extended_record_limit_round_trip(self):
        count = 4096
        raw = b''.join(struct.pack('<I', i) for i in range(count))
        records = b''.join(struct.pack('<3I', 0x20000 + 4*i, 4, 4*i) for i in range(count))
        result = decode(struct.pack('<4I', 0x534c4159, 2, count, len(raw)) + records + raw)
        self.assertTrue(result['complete_binary'])
        self.assertEqual(len(result['records']), count)
        self.assertEqual(result['records'][-1]['data'], struct.pack('<I', count-1).hex())

    def test_rejects_count_above_bound(self):
        with self.assertRaises(ValueError):
            decode(struct.pack('<4I', 0x534c4159, 2, 4097, 0))

    def test_rejects_conflicting_overlaps(self):
        records = struct.pack('<6I', 0x20000, 4, 0, 0x20000, 4, 4)
        with self.assertRaisesRegex(ValueError, 'Conflicting'):
            decode(struct.pack('<4I', 0x534c4159, 2, 2, 8) + records + b'abcdABCD')

    def test_rejects_partial_payload(self):
        with self.assertRaisesRegex(ValueError, 'length'):
            decode(struct.pack('<4I', 0x534c4159, 2, 1, 4) + struct.pack('<3I', 0x20000, 4, 0) + b'abc')

    def test_rejects_record_outside_user_range(self):
        with self.assertRaisesRegex(ValueError, 'range'):
            decode(struct.pack('<4I', 0x534c4159, 2, 1, 4) + struct.pack('<3I', 0xffff0000, 4, 0) + b'abcd')
