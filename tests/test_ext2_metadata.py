"""Constructed ext2 fixtures: no original firmware required."""
import hashlib
import struct
import unittest

from project_paths import PROJECT_ROOT
from src.a6400.images.ext2_metadata import Ext2Metadata


def fixture():
    data = bytearray(32 * 1024)
    for offset, value in {1024: 16, 1028: 32, 1044: 1, 1048: 0,
                          1056: 32, 1064: 16, 1096: 0, 1100: 1,
                          1120: 2, 1124: 3, 2056: 3}.items():
        struct.pack_into('<I', data, offset, value)
    struct.pack_into('<H', data, 1080, 0xef53)
    struct.pack_into('<H', data, 1112, 128)
    for number, mode, size, block, links in ((2, 0o40755, 1024, 5, 2),
                                            (12, 0o100644, 4, 6, 2)):
        offset = 3072 + (number - 1) * 128
        struct.pack_into('<HH5IHHII', data, offset, mode, 42, size,
                         100, 101, 102, 0, 43, links, 2, 0)
        struct.pack_into('<I', data, offset + 40, block)
        struct.pack_into('<HH', data, offset + 120, 1, 2)
    offset = 5120
    for number, name, length in ((2, b'.', 12), (2, b'..', 12),
                                  (12, b'file', 12), (12, b'hard', 988)):
        struct.pack_into('<IHBB', data, offset, number, length, len(name), 0)
        data[offset + 8:offset + 8 + len(name)] = name
        offset += length
    data[6144:6148] = b'DATA'
    return data


class Ext2MetadataTests(unittest.TestCase):
    def load(self, data, expected=None):
        path = PROJECT_ROOT / 'artifacts/tests/ext2-metadata-fixture.bin'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return Ext2Metadata(path, expected or hashlib.sha256(data).hexdigest())

    def test_inode_identity_hardlinks_and_directory_size(self):
        indexed = self.load(fixture()).index()
        self.assertEqual(set(indexed), {'/', '/file', '/hard'})
        self.assertEqual(indexed['/']['size'], 1024)
        file = indexed['/file']
        self.assertEqual(file, indexed['/hard'])
        self.assertEqual((file['inode'], file['inode_file_offset']), (12, 4480))
        self.assertEqual((file['uid'], file['gid']), (65578, 131115))
        self.assertEqual((file['size'], file['nlink'], file['blocks_512']), (4, 2, 2))
        self.assertEqual(file['image_times'], {'atime': 100, 'ctime': 101, 'mtime': 102})

    def test_source_hash_must_match(self):
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            self.load(fixture(), '0' * 64)

    def test_invalid_block_stops(self):
        data = fixture()
        struct.pack_into('<I', data, 3072 + 128 + 40, 32)
        with self.assertRaisesRegex(ValueError, 'block reference'):
            self.load(data).index()

    def test_directory_cycle_stops(self):
        data = fixture()
        struct.pack_into('<I', data, 5120 + 24, 2)
        with self.assertRaisesRegex(ValueError, 'cycle'):
            self.load(data).index()

    def test_bad_directory_record_stops(self):
        data = fixture()
        struct.pack_into('<H', data, 5120 + 4, 0)
        with self.assertRaisesRegex(ValueError, 'directory entry'):
            self.load(data).index()

    def test_unsupported_feature_and_truncation(self):
        data = fixture()
        struct.pack_into('<I', data, 1120, 0x40)
        with self.assertRaises(ValueError):
            self.load(data)
        with self.assertRaisesRegex(ValueError, 'Truncated'):
            self.load(fixture()[:-1024])


class Ext2DeviceTests(unittest.TestCase):
    load = Ext2MetadataTests.load
    def test_special_inode_old_and_new_device_encoding(self):
        for words, expected in (((0x109, 0), (1, 9)),
                                ((0, (0x123 << 8) | 0x45 | (0xabc << 20)), (0x123, 0xabc45))):
            data = fixture()
            offset = 3072 + 11 * 128
            struct.pack_into('<H', data, offset, 0o20444)
            struct.pack_into('<II', data, offset + 40, *words)
            node = self.load(data).inode(12)
            self.assertEqual(node['device_number'], dict(zip(('major', 'minor'), expected)))
            self.assertEqual(node['device_encoding'], 'old' if words[0] else 'new')
