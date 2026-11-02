"""Static evidence must not silently become runtime device identity."""
import hashlib
import struct
import unittest

from project_paths import PROJECT_ROOT
from tools.research.mount_evidence import (checked_input, terminated_ascii, mount_rows,
                                           device_rows, unsupplied_mount_roots)


class MountEvidenceTests(unittest.TestCase):
    def test_mount_options_and_candidate_overlays(self):
        strings = {1: '/dev/dnflasha15', 2: '/usr', 3: 'ext2', 4: '/dev/nflasha10',
                   5: '/etc', 6: 'vfat', 7: 'posix_attr'}
        raw = struct.pack('<10I', 1, 2, 3, 0xc0ed0001, 0, 4, 5, 6, 0xc0ed0490, 7)
        rows = mount_rows(raw, strings.__getitem__)
        self.assertEqual(rows[0]['options'], None)
        self.assertEqual(rows[1]['options'], 'posix_attr')
        self.assertEqual(rows[1]['record_offset'], 20)
        self.assertEqual(unsupplied_mount_roots(rows), ['/etc'])
        self.assertEqual(unsupplied_mount_roots(rows, supplied=()), ['/etc', '/usr'])

    def test_bad_mount_record_and_target_rejected(self):
        with self.assertRaises(ValueError):
            mount_rows(bytes(19), lambda pointer: '')
        for target in ('relative', '/x/../etc'):
            with self.assertRaises(ValueError):
                unsupplied_mount_roots([{'target': target}])

    def test_device_ranges_remain_distinct_inferences(self):
        raw = struct.pack('<I4HI4H', 0, 1, 252, 0, 32, 8, 1, 252, 128, 32)
        rows = device_rows(raw, {0: 'nflasha', 12: 'dnflasha'})
        self.assertEqual(rows[0]['raw_halfwords'], [1, 252, 0, 32])
        self.assertEqual(rows[1]['inferred_first_minor'], 128)
        self.assertNotIn('st_dev', rows[1])

    def test_incomplete_relocations_and_invalid_ranges_rejected(self):
        for raw, names in ((bytes(12), {}), (bytes(13), {0: 'name'}),
                           (struct.pack('<I4H', 0, 1, 252, 65535, 2), {0: 'name'})):
            with self.assertRaises(ValueError):
                device_rows(raw, names)

    def test_evidence_strings_are_bounded(self):
        self.assertEqual(terminated_ascii(b'\0nflasha\0', 1), 'nflasha')
        for data, offset in ((b'no-null', 0), (b'x\0', 3), (b'\xff\0', 0)):
            with self.assertRaises(ValueError):
                terminated_ascii(data, offset)

    def test_preserved_input_identity_and_confinement(self):
        # A constructed directory called firmware keeps the fixture independent
        # of proprietary inputs, while exercising the same confinement boundary.
        root = PROJECT_ROOT / 'artifacts/tests/mount-inputs'
        folder = root / 'firmware'
        folder.mkdir(parents=True, exist_ok=True)
        (folder / 'fixture').write_bytes(b'original')
        expected = hashlib.sha256(b'original').hexdigest()
        self.assertEqual(checked_input(root, 'firmware/fixture', expected), b'original')
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            checked_input(root, 'firmware/fixture', '0' * 64)
        with self.assertRaisesRegex(ValueError, 'escapes'):
            checked_input(root, '../fixture', expected)
