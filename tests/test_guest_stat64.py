"""ARM metadata layout, bounded copies and unknown-value consumption."""
import struct
import stat
import unittest

import unicorn
from unicorn import arm_const as arm
from src.a6400.execution.guest_stat64 import GuestStat64, SIZE
from src.a6400.execution.guarded_bytes import UnverifiedGuestData
from src.a6400.execution.guest_filesystem import GuestFilesystem


class Stat64Tests(unittest.TestCase):
    def setUp(self):
        self.mu = unicorn.Uc(unicorn.UC_ARCH_ARM, unicorn.UC_MODE_ARM)
        self.mu.mem_map(0x1000, 4096)
        self.mu.mem_map(0x3000, 4096)
        self.stops, self.writes = [], []
        def stop(details):
            self.stops.append(details)
            self.mu.emu_stop()
        self.contract = GuestStat64(self.mu, stop, lambda a, n: self.writes.append((a, n)))
        self.metadata = {'image_sha256': 'constructed', 'inode_file_offset': 4480,
                         'inode': 12, 'mode': 0o100644, 'uid': 42, 'gid': 43,
                         'size': 0x100000004, 'block_size': 1024, 'blocks_512': 7,
                         'nlink': 2}
        self.mu.mem_write(0x3000, b'Z' * 105)

    def instruction(self, opcode, address):
        self.mu.mem_write(0x1000, opcode.to_bytes(4, 'little'))
        self.mu.ctl_remove_cache(0x1000, 0x1004)
        self.mu.reg_write(arm.UC_ARM_REG_R1, address)
        self.mu.emu_start(0x1000, 0x1004)

    def test_layout_and_unknown_bytes_not_fabricated(self):
        result = self.contract.request(self.metadata, 0x3000)
        self.assertTrue(result['partial_contract'])
        data = bytes(self.mu.mem_read(0x3000, 105))
        self.assertEqual(data[:8], b'Z' * 8)
        self.assertEqual(data[32:40], b'Z' * 8)
        self.assertEqual(data[72:96], b'Z' * 24)
        self.assertEqual(data[104:], b'Z')
        self.assertEqual(struct.unpack_from('<4I', data, 16), (0o100644, 2, 42, 43))
        self.assertEqual(struct.unpack_from('<q', data, 48)[0], 0x100000004)
        self.assertEqual(struct.unpack_from('<Q', data, 64)[0], 7)
        self.assertEqual(struct.unpack_from('<Q', data, 96)[0], 12)
        self.assertEqual(self.writes, [(0x3000, SIZE)])

    def test_known_cpu_read_allowed_unknown_read_stops(self):
        self.contract.request(self.metadata, 0x3000)
        self.instruction(0xe5910000, 0x3010)
        self.assertEqual(self.mu.reg_read(arm.UC_ARM_REG_R0), 0o100644)
        self.assertFalse(self.stops)
        self.instruction(0xe5910000, 0x3000)
        self.assertEqual(self.stops[0]['fields'], ['st_dev'])
        self.assertEqual(self.stops[0]['domain'], 'stat64')

    def test_host_read_cannot_bypass_guard(self):
        self.contract.request(self.metadata, 0x3000)
        with self.assertRaises(UnverifiedGuestData):
            self.contract.assert_known_host_read(0x3004, 8)
        self.contract.assert_known_host_read(0x3010, 16)

    def test_guest_overwrite_releases_only_written_bytes(self):
        self.contract.request(self.metadata, 0x3000)
        self.instruction(0xe5810000, 0x3000)
        self.contract.assert_known_host_read(0x3000, 4)
        with self.assertRaises(UnverifiedGuestData):
            self.contract.assert_known_host_read(0x3004, 4)

    def test_cross_page_preflight_atomic(self):
        self.mu.mem_write(0x3ff0, b'X' * 16)
        self.assertEqual(self.contract.request(self.metadata, 0x3ff0)['returned'], 0xfffffff2)
        self.assertEqual(bytes(self.mu.mem_read(0x3ff0, 16)), b'X' * 16)
        self.assertEqual(self.contract.bytes, {})
        self.assertEqual(self.writes, [])

    def test_stat_and_fstat_share_inode_metadata(self):
        nodes = {'/': {'kind': 'directory', 'uid': 0, 'gid': 0, 'mode': 0o40755},
                 '/file': {'kind': 'file', 'uid': 42, 'gid': 43, 'mode': 0o100644,
                           'size': 4, 'stat_metadata': self.metadata}}
        fs = GuestFilesystem(self.mu, nodes, lambda p, n: b'DATA', stat_contract=self.contract)
        self.mu.mem_write(0x3100, b'/file\0')
        a = fs.request(195, [0x3100, 0x3200, 0])
        fd = fs.request(5, [0x3100, 0, 0])['returned']
        b = fs.request(197, [fd, 0x3300, 0])
        self.assertEqual(a['source'], b['source'])
        self.assertEqual(bytes(self.mu.mem_read(0x3200, SIZE)), bytes(self.mu.mem_read(0x3300, SIZE)))
        self.assertEqual(fs.request(197, [99, 0x3300, 0])['returned'], 0xfffffff7)

    def test_regular_rdev_is_explicit_and_does_not_release_timestamp_guards(self):
        self.contract.regular_inode_rdev = True
        result = self.contract.request(self.metadata, 0x3000)
        self.assertEqual(bytes(self.mu.mem_read(0x3020, 8)), bytes(8))
        self.assertEqual(result['source']['st_rdev'], 0)
        self.contract.assert_known_host_read(0x3020, 8)
        self.instruction(0xe5910000, 0x3020)
        self.assertEqual(self.mu.reg_read(arm.UC_ARM_REG_R0), 0)
        self.assertFalse(self.stops)
        # A CPU read can span a named known field and a per-buffer known range.
        self.instruction(0xe5910000, 0x301e)
        self.assertFalse(self.stops)
        self.assertNotIn(None, self.contract.read_fields)
        with self.assertRaises(UnverifiedGuestData):
            self.contract.assert_known_host_read(0x3048, 4)

    def test_regular_rdev_does_not_release_special_nodes_or_other_buffers(self):
        self.contract.regular_inode_rdev = True
        self.contract.request(self.metadata, 0x3000)
        for mode in (0o20644, 0o60644, 0o40755, 0o120777):
            with self.subTest(mode=mode):
                result = self.contract.request({**self.metadata, 'mode': mode}, 0x3100)
                self.assertIn('st_rdev', result['guarded_fields'])
                with self.assertRaises(UnverifiedGuestData):
                    self.contract.assert_known_host_read(0x3120, 8)
                self.contract.assert_known_host_read(0x3020, 8)

    def test_character_device_rdev_written_and_not_guarded(self):
        chr_meta = {**self.metadata, 'mode': stat.S_IFCHR | 0o666, 'device_number': {'major': 1, 'minor': 9}}
        result = self.contract.request(chr_meta, 0x3000)
        # major=1, minor=9 -> makedev = (1 << 8) | 9 = 0x109 = 265
        self.assertEqual(result['source']['st_rdev'], 0x109)
        self.assertNotIn('st_rdev', result['guarded_fields'])
        rdev_val = struct.unpack('<Q', self.mu.mem_read(0x3020, 8))[0]
        self.assertEqual(rdev_val, 0x109)
        self.contract.assert_known_host_read(0x3020, 8)
        self.instruction(0xe5910000, 0x3020)
        self.assertEqual(self.mu.reg_read(arm.UC_ARM_REG_R0), 0x109)
        self.assertFalse(self.stops)

    def readonly_metadata(self):
        return {**self.metadata, 'image_sha256': 'a' * 64,
                'image_times': {'atime': 0xffffffff, 'mtime': 1234, 'ctime': 5678},
                'readonly_image_mount': {'image_sha256': 'a' * 64, 'filesystem': 'ext2',
                                         'flags': 0xc0ed0001, 'target': '/usr'}}

    def test_readonly_times_preserve_inode_bits_and_zero_ext2_nanoseconds(self):
        self.contract.readonly_image_times = True
        result = self.contract.request(self.readonly_metadata(), 0x3000)
        self.assertEqual(struct.unpack('<6I', self.mu.mem_read(0x3048, 24)),
                         (0xffffffff, 0, 1234, 0, 5678, 0))
        self.contract.assert_known_host_read(0x3048, 24)
        self.instruction(0xe5910000, 0x3050)
        self.assertEqual(self.mu.reg_read(arm.UC_ARM_REG_R0), 1234)
        self.assertFalse(self.stops)
        self.assertNotIn('st_atime', result['guarded_fields'])
        with self.assertRaises(UnverifiedGuestData):
            self.contract.assert_known_host_read(0x3020, 8)

    def test_readonly_times_need_policy_matching_image_and_readonly_ext2_mount(self):
        metadata = self.readonly_metadata()
        self.contract.request(metadata, 0x3000)
        with self.assertRaises(UnverifiedGuestData):
            self.contract.assert_known_host_read(0x3048, 24)
        self.contract.readonly_image_times = True
        for mount in ({}, {**metadata['readonly_image_mount'], 'flags': 0},
                      {**metadata['readonly_image_mount'], 'image_sha256': 'b' * 64},
                      {**metadata['readonly_image_mount'], 'filesystem': 'vfat'}):
            with self.subTest(mount=mount):
                result = self.contract.request({**metadata, 'readonly_image_mount': mount}, 0x3100)
                self.assertIn('st_atime', result['guarded_fields'])
                with self.assertRaises(UnverifiedGuestData):
                    self.contract.assert_known_host_read(0x3148, 24)

    def test_writable_inode_cannot_inherit_another_buffers_readonly_timestamp_permission(self):
        self.contract.readonly_image_times = True
        metadata = self.readonly_metadata()
        self.contract.request(metadata, 0x3000)
        self.contract.request(self.metadata, 0x3100)
        self.contract.assert_known_host_read(0x3048, 24)
        with self.assertRaises(UnverifiedGuestData):
            self.contract.assert_known_host_read(0x3148, 24)
        # Reusing the same destination for an unsupplied inode restores guards.
        self.contract.request(self.metadata, 0x3000)
        with self.assertRaises(UnverifiedGuestData):
            self.contract.assert_known_host_read(0x3048, 24)

    def test_invalid_readonly_times_fail_before_any_copy(self):
        self.contract.readonly_image_times = True
        for times in ({}, {'atime': -1, 'mtime': 0, 'ctime': 0},
                      {'atime': 0x100000000, 'mtime': 0, 'ctime': 0}):
            with self.subTest(times=times), self.assertRaises(ValueError):
                self.contract.request({**self.readonly_metadata(), 'image_times': times}, 0x3000)
            self.assertEqual(bytes(self.mu.mem_read(0x3000, 105)), b'Z' * 105)
            self.assertEqual(self.contract.bytes, {})
