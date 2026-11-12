"""GuestMmap 'sigbus' EOF policy: pages wholly past EOF fault; later MAP_FIXED maps them normally."""
import unittest

import unicorn

from src.a6400.execution.guest_mmap import (
    GuestMmap, PROT_READ, PROT_WRITE, MAP_PRIVATE, MAP_ANONYMOUS, MAP_FIXED)


class DummyFilesystem:
    def __init__(self):
        self.fds = {}


class SigbusEofTests(unittest.TestCase):
    def setUp(self):
        self.mu = unicorn.Uc(unicorn.UC_ARCH_ARM, unicorn.UC_MODE_ARM)
        self.fs = DummyFilesystem()
        self.mmap = GuestMmap(self.mu, self.fs, base_address=0x50000000, ceiling_address=0x60000000)
        self.fs.fds[3] = {'path': '/usr/lib/short.so', 'data': b'A' * 5000, 'offset': 0}

    def test_zero_fill_default_unchanged(self):
        res = self.mmap.request_mmap2(0, 0x4000, PROT_READ, MAP_PRIVATE, 3, 0)
        self.assertNotIn('beyond_eof', res['mapping'])
        self.assertEqual(bytes(self.mu.mem_read(0x50003000, 16)), bytes(16))

    def test_pages_past_eof_fault_and_eof_page_tail_is_zero(self):
        self.mmap.eof_policy = 'sigbus'
        res = self.mmap.request_mmap2(0, 0x4000, PROT_READ, MAP_PRIVATE, 3, 0)
        self.assertEqual(res['mapping']['beyond_eof'], {'address': 0x50002000, 'length': 0x2000})
        self.assertEqual(bytes(self.mu.mem_read(0x50001388, 8)), bytes(8))  # tail of the EOF page
        with self.assertRaises(unicorn.UcError):
            self.mu.mem_read(0x50002000, 4)
        # mprotect over the whole range succeeds and leaves past-EOF pages faulting
        self.assertEqual(self.mmap.request_mprotect(0x50000000, 0x4000, PROT_READ | PROT_WRITE)['returned'], 0)
        with self.assertRaises(unicorn.UcError):
            self.mu.mem_read(0x50003000, 4)

    def test_map_fixed_over_past_eof_pages_maps_them(self):
        self.mmap.eof_policy = 'sigbus'
        self.mmap.request_mmap2(0, 0x4000, PROT_READ, MAP_PRIVATE, 3, 0)
        self.mmap.request_mmap2(0x50003000, 0x1000, PROT_READ | PROT_WRITE,
                                MAP_PRIVATE | MAP_ANONYMOUS | MAP_FIXED, -1, 0)
        self.assertEqual(bytes(self.mu.mem_read(0x50003000, 4)), bytes(4))
        self.assertNotIn(0x50003000, self.mmap.beyond_eof_pages)
        self.assertIn(0x50002000, self.mmap.beyond_eof_pages)
        self.assertEqual(self.mmap.request_munmap(0x50000000, 0x4000)['returned'], 0)
        self.assertFalse(self.mmap.beyond_eof_pages)


if __name__ == '__main__':
    unittest.main()
