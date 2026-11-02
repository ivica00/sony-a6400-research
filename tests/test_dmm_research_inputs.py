"""Input identity and cross-chunk scanning checks use constructed files only."""
import hashlib
import struct
import unittest

from project_paths import PROJECT_ROOT
from tools.research.rea_wsl_batch import checked_input
from tools.research.ulogio_input_scan import scan_file


class ResearchInputTests(unittest.TestCase):
    def setUp(self):
        self.root = PROJECT_ROOT / 'artifacts/tests/dmm-research-inputs'
        (self.root / 'firmware').mkdir(parents=True, exist_ok=True)

    def test_launcher_requires_hash_and_declared_firmware_namespace(self):
        path = self.root / 'firmware/launcher-fixture.bin'
        path.write_bytes(b'constructed')
        digest = hashlib.sha256(b'constructed').hexdigest()
        self.assertEqual(checked_input(self.root, 'firmware/launcher-fixture.bin', digest), b'constructed')
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            checked_input(self.root, 'firmware/launcher-fixture.bin', '0' * 64)
        with self.assertRaisesRegex(ValueError, 'escapes'):
            checked_input(self.root, '../outside.bin', digest)

    def test_scan_finds_record_across_chunk_boundary_once(self):
        record = struct.pack('<I4sII', 16, b'LOGB', 0x12340000, 0x10000)
        data = b'\0' * (1024 * 1024 - 7) + record + bytes(32)
        path = self.root / 'firmware/scan-fixture.bin'
        path.write_bytes(data)
        result = scan_file(path, hashlib.sha256(data).hexdigest(), len(data))
        self.assertEqual(result, [{'offset': 1024 * 1024 - 7, 'record_size': 16,
                                   'physical_base': 0x12340000, 'memory_size': 0x10000}])

    def test_scan_rejects_truncated_records_and_changed_identity(self):
        data = struct.pack('<I4sII', 1000, b'LOGB', 1, 2)
        path = self.root / 'firmware/truncated-fixture.bin'
        path.write_bytes(data)
        digest = hashlib.sha256(data).hexdigest()
        self.assertEqual(scan_file(path, digest, len(data)), [])
        with self.assertRaisesRegex(ValueError, 'length/hash mismatch'):
            scan_file(path, digest, len(data) + 1)
        with self.assertRaisesRegex(ValueError, 'length/hash mismatch'):
            scan_file(path, '0' * 64, len(data))


if __name__ == '__main__':
    unittest.main()
