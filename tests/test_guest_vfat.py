"""Constructed FAT12 image checks for the read-only nflasha1 mount contract."""
import hashlib
import struct
import unittest

from src.a6400.execution.guest_filesystem import GuestFilesystem
from src.a6400.execution.guest_vfat import VfatEntry, VfatError, VfatImage


def dir_entry(name, ext, attr, cluster, size):
    raw = bytearray(32)
    raw[0:8] = name.ljust(8).encode('ascii')
    raw[8:11] = ext.ljust(3).encode('ascii')
    raw[11] = attr
    struct.pack_into('<H', raw, 26, cluster)
    struct.pack_into('<I', raw, 28, size)
    return bytes(raw)


def fat12_image():
    sector = 512
    total_sectors = 10
    reserved, fats, root_entries, fat_sectors, spc = 1, 1, 16, 1, 1
    root_start = (reserved + fats * fat_sectors) * sector
    data_start = root_start + root_entries * 32
    image = bytearray(total_sectors * sector)
    # Boot sector BPB.
    image[0:3] = b'\xeb\x3c\x90'
    image[3:11] = b'MSDOS5.0'
    struct.pack_into('<H', image, 0x0b, sector)
    image[0x0d] = spc
    struct.pack_into('<H', image, 0x0e, reserved)
    image[0x10] = fats
    struct.pack_into('<H', image, 0x11, root_entries)
    struct.pack_into('<H', image, 0x13, total_sectors)
    struct.pack_into('<H', image, 0x16, fat_sectors)
    image[0x36:0x3e] = b'FAT12   '
    image[0x1fe:0x200] = b'\x55\xaa'
    # FAT entries: reserved 0xFF8/0xFFF, clusters 2,3,4 end-of-chain.
    entries = {0: 0xFF8, 1: 0xFFF, 2: 0xFFF, 3: 0xFFF, 4: 0xFFF}
    fat = bytearray(fat_sectors * sector)
    for index, value in entries.items():
        offset = index + index // 2
        if index & 1:
            fat[offset] = (fat[offset] & 0x0f) | ((value & 0x0f) << 4)
            fat[offset + 1] = (value >> 4) & 0xff
        else:
            fat[offset] = value & 0xff
            fat[offset + 1] = (fat[offset + 1] & 0xf0) | ((value >> 8) & 0x0f)
    image[reserved * sector:(reserved + fat_sectors) * sector] = fat
    # Root directory: HELLO.TXT, SUB directory, end marker.
    root = bytearray(root_entries * 32)
    root[0:32] = dir_entry('HELLO', 'TXT', 0x20, 2, 5)
    root[32:64] = dir_entry('SUB', '', 0x10, 3, 0)
    image[root_start:root_start + len(root)] = root
    # Cluster 2: HELLO data. Cluster 3: SUB directory. Cluster 4: A.BIN.
    cluster = lambda number: data_start + (number - 2) * sector
    image[cluster(2):cluster(2) + 5] = b'hello'
    sub = bytearray(32 * 3)
    sub[0:32] = dir_entry('.', '', 0x10, 3, 0)
    sub[32:64] = dir_entry('..', '', 0x10, 0, 0)
    sub[64:96] = dir_entry('A', 'BIN', 0x20, 4, 3)
    image[cluster(3):cluster(3) + len(sub)] = sub
    image[cluster(4):cluster(4) + 3] = b'abc'
    return bytes(image)


class VfatReaderTests(unittest.TestCase):
    def test_parses_fat12_tree_and_reads_files(self):
        image = VfatImage(fat12_image(), expected_size=10 * 512)
        self.assertEqual(image.fat_type, 12)
        root = image.list_dir()
        names = sorted(entry.display_name for entry in root)
        self.assertEqual(names, ['HELLO.TXT', 'SUB'])
        entries = dict(image.walk())
        self.assertEqual(sorted(entries), ['HELLO.TXT', 'SUB', 'SUB/A.BIN'])
        self.assertEqual(image.read_file(entries['HELLO.TXT']), b'hello')
        self.assertEqual(image.read_file(entries['SUB/A.BIN']), b'abc')
        self.assertEqual(image.read_file(entries['SUB/A.BIN'])[:2], b'ab')

    def test_rejects_invalid_identity_and_boot_sector(self):
        raw = fat12_image()
        broken = bytearray(raw)
        broken[0x1fe] = 0
        with self.assertRaises(VfatError):
            VfatImage(bytes(broken), expected_size=len(raw))
        digest = hashlib.sha256(raw).hexdigest()
        VfatImage(raw, expected_size=len(raw), image_sha256=digest)
        with self.assertRaises(ValueError):
            VfatImage(raw, expected_size=len(raw), image_sha256='0' * 64)
        with self.assertRaises(ValueError):
            VfatImage(raw + b'\x00', expected_size=len(raw))
        with self.assertRaises(ValueError):
            VfatImage(raw[:-1], expected_size=len(raw))

    def test_directory_entries_expose_expected_flags(self):
        image = VfatImage(fat12_image(), expected_size=10 * 512)
        root = {entry.display_name: entry for entry in image.list_dir()}
        self.assertFalse(root['HELLO.TXT'].is_dir)
        self.assertTrue(root['SUB'].is_dir)
        self.assertIsInstance(root['SUB'], VfatEntry)


class VfatMountMaterializationTests(unittest.TestCase):
    def test_mount_materializes_nodes_and_content_cache(self):
        image = VfatImage(fat12_image(), expected_size=10 * 512)
        nodes = {'/': {'kind': 'directory', 'mode': 0o040755, 'uid': 0, 'gid': 0, 'size': 0},
                 '/mnt': {'kind': 'directory', 'mode': 0o040755, 'uid': 0, 'gid': 0, 'size': 0}}

        def unexpected_loader(path, node):
            raise AssertionError('vfat files must come from the materialized cache')

        filesystem = GuestFilesystem(None, nodes, unexpected_loader)
        mounted = filesystem.mount_vfat('/mnt', image)
        self.assertEqual(mounted['files'], 2)
        self.assertEqual(mounted['directories'], 2)  # /mnt itself + /mnt/SUB
        self.assertEqual(nodes['/mnt/HELLO.TXT']['kind'], 'file')
        self.assertEqual(nodes['/mnt/HELLO.TXT']['size'], 5)
        self.assertEqual(filesystem.cache['/mnt/HELLO.TXT'], b'hello')
        self.assertEqual(filesystem.cache['/mnt/SUB/A.BIN'], b'abc')
        # Mounted target is no longer an unknown runtime namespace.
        filesystem._scope('/mnt/HELLO.TXT')
        filesystem._scope('/mnt/SUB')
        with self.assertRaises(Exception):
            filesystem._scope('/proc/modules')
        with self.assertRaises(Exception):
            filesystem.mount_vfat('/mnt', image)

    def test_umount_restores_the_original_mountpoint_node(self):
        image = VfatImage(fat12_image(), expected_size=10 * 512)
        original = {'kind': 'directory', 'mode': 0o040755, 'uid': 57285, 'gid': 1000,
                    'size': 0, 'image': 'nflasha7'}
        nodes = {'/': {'kind': 'directory', 'mode': 0o040755, 'uid': 0, 'gid': 0, 'size': 0},
                 '/mnt': dict(original)}
        filesystem = GuestFilesystem(None, nodes, lambda path, node: b'')
        filesystem.mount_vfat('/mnt', image)
        self.assertIn('/mnt/HELLO.TXT', nodes)
        unmounted = filesystem.umount_vfat('/mnt')
        self.assertEqual(unmounted['files'], 2)
        self.assertEqual(nodes['/mnt'], original)
        self.assertNotIn('/mnt/HELLO.TXT', nodes)
        self.assertNotIn('/mnt/HELLO.TXT', filesystem.cache)
        with self.assertRaises(Exception):
            filesystem.umount_vfat('/mnt')


class VfatDirectoryContractTests(unittest.TestCase):
    def setUp(self):
        import unicorn
        self.mu = unicorn.Uc(unicorn.UC_ARCH_ARM, unicorn.UC_MODE_ARM)
        self.mu.mem_map(0x1000, 0x4000)
        nodes = {'/': {'kind': 'directory', 'mode': 0o040755, 'uid': 0, 'gid': 0, 'size': 0},
                 '/setting': {'kind': 'directory', 'mode': 0o040755, 'uid': 0, 'gid': 0, 'size': 0}}
        self.fs = GuestFilesystem(self.mu, nodes, lambda path, node: b'')
        self.fs.mount_vfat('/setting', VfatImage(fat12_image(), expected_size=10 * 512))

    def write_path(self, address, value):
        self.mu.mem_write(address, value.encode('ascii') + b'\x00')

    def test_open_directory_and_getdents64(self):
        self.write_path(0x1000, '/setting')
        opened = self.fs.request(5, [0x1000, 0, 0])
        self.assertEqual(opened['returned'], 3)
        self.assertEqual(opened['reason'], 'opened_readonly_directory')
        listing = self.fs.request(217, [opened['returned'], 0x2000, 4096])
        self.assertGreater(listing['returned'], 0)
        self.assertEqual(listing['entries'], ['.', '..', 'HELLO.TXT', 'SUB'])
        raw = bytes(self.mu.mem_read(0x2000, listing['returned']))
        names = []
        offset = 0
        while offset < len(raw):
            ino, off, reclen, dtype = struct.unpack_from('<QqHB', raw, offset)
            name = raw[offset + 19:offset + reclen].split(b'\x00')[0].decode('ascii')
            names.append(name)
            offset += reclen
        self.assertEqual(names, ['.', '..', 'HELLO.TXT', 'SUB'])
        empty = self.fs.request(217, [opened['returned'], 0x2000, 4096])
        self.assertEqual(empty['returned'], 0)
        self.assertEqual(empty['entries'], [])

    def test_open_file_under_materialized_setting_and_read(self):
        self.write_path(0x1100, '/setting/HELLO.TXT')
        opened = self.fs.request(5, [0x1100, 0, 0])
        fd = opened['returned']
        self.assertGreaterEqual(fd, 3)
        read = self.fs.request(3, [fd, 0x2000, 8])
        self.assertEqual(read['returned'], 5)
        self.assertEqual(bytes(self.mu.mem_read(0x2000, 5)), b'hello')
        self.fs.request(6, [fd, 0, 0])

    def test_getdents_rejects_non_directory_fd(self):
        self.write_path(0x1200, '/setting/HELLO.TXT')
        fd = self.fs.request(5, [0x1200, 0, 0])['returned']
        with self.assertRaises(Exception):
            self.fs.request(217, [fd, 0x2000, 4096])


if __name__ == '__main__':
    unittest.main()
