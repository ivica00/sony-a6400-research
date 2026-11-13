"""Exact-duplicate /dev/stream physical mappings alias one host buffer."""
import unittest

import unicorn

from src.a6400.execution.guest_stream import GuestStream, UnsupportedStream
from src.a6400.execution.guest_mmap import GuestMmap

PROFILE = {'major': 249, 'minor': 7, 'initial_offset': 0, 'module_sha256': 'fixture', 'devno_sha256': 'fixture'}


class StreamAliasTests(unittest.TestCase):
    def setUp(self):
        self.mu = unicorn.Uc(unicorn.UC_ARCH_ARM, unicorn.UC_MODE_ARM)
        self.mapper = GuestMmap(self.mu, type('FS', (), {'fds': {}})())
        self.stream = GuestStream(self.mu, self.mapper, PROFILE, lambda d: None, lambda a, n: None)

    def map(self, length=8192, pgoff=0x202e0):
        return self.stream.mmap2(0, length, 3, 1, 4, pgoff)['returned']

    def test_exact_duplicate_maps_and_writes_alias(self):
        v1, v2 = self.map(), self.map()
        self.assertNotEqual(v1, v2)
        self.mu.mem_write(v1 + 16, b'abcd')
        self.assertEqual(bytes(self.mu.mem_read(v2 + 16, 4)), b'abcd')
        self.mu.mem_write(v2 + 4096, b'wxyz')
        self.assertEqual(bytes(self.mu.mem_read(v1 + 4096, 4)), b'wxyz')
        self.assertEqual(self.stream.mappings[1]['alias_of'], v1)
        self.assertEqual(self.stream.transactions[-1]['operation'], 'mmap_alias')

    def test_existing_bytes_survive_aliasing(self):
        v1 = self.map()
        self.mu.mem_write(v1, b'keep')
        v2 = self.map()
        self.assertEqual(bytes(self.mu.mem_read(v2, 4)), b'keep')

    def test_write_through_either_va_clears_unknown_state_for_both(self):
        v1, v2 = self.map(), self.map()
        self.mu.mem_write(v1, b'1234')  # direct host write; emulate guest store via forget_range
        self.stream.forget_range(v2, 4)
        self.stream.assert_known_host_read(v1, 4)
        self.stream.assert_known_host_read(v2, 4)
        with self.assertRaises(Exception):
            self.stream.assert_known_host_read(v1 + 4, 4)

    def test_partial_overlap_still_raises(self):
        self.map()
        for length, pgoff in ((4096, 0x202e0), (8192, 0x202e1), (0x4000, 0x202e0)):
            with self.assertRaises(UnsupportedStream):
                self.map(length, pgoff)


if __name__ == '__main__':
    unittest.main()
