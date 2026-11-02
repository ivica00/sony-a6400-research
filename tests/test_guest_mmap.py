"""Unit tests for GuestMmap contract: page allocation, protection, unmapping, and file-backed loading."""

import hashlib
import struct
import unittest
import unicorn
from unicorn import arm_const as arm

from src.a6400.execution.guest_mmap import (
    GuestMmap, UnsupportedMmap, PROT_READ, PROT_WRITE, PROT_EXEC,
    MAP_PRIVATE, MAP_ANONYMOUS, MAP_FIXED
)


class DummyFilesystem:
    def __init__(self, fds=None):
        self.fds = fds or {}


class GuestMmapTests(unittest.TestCase):
    def setUp(self):
        self.mu = unicorn.Uc(unicorn.UC_ARCH_ARM, unicorn.UC_MODE_ARM)
        self.fs = DummyFilesystem()
        self.mmap = GuestMmap(self.mu, self.fs, base_address=0x50000000, ceiling_address=0x60000000)

    def test_anonymous_allocation_page_aligned_and_zeroed(self):
        res = self.mmap.request_mmap2(0, 1000, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0)
        self.assertEqual(res['returned'], 0x50000000)
        self.assertEqual(res['reason'], 'guarded_mmap2_allocated')
        self.assertIn(0x50000000, self.mmap.mapped_pages)
        # Verify page is zeroed
        data = self.mu.mem_read(0x50000000, 4096)
        self.assertEqual(data, bytes(4096))
        # Subsequent unhinted allocation uses 64 KiB chunk alignment
        res2 = self.mmap.request_mmap2(0, 2000, PROT_READ, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0)
        self.assertEqual(res2['returned'], 0x50010000)

    def test_file_backed_allocation_and_partial_page_zeroing(self):
        file_bytes = b'HELLO_FIRMWARE_ELF_WORLD' + bytes(100)
        self.fs.fds[3] = {'path': '/usr/lib/libtest.so', 'data': file_bytes, 'offset': 0}
        res = self.mmap.request_mmap2(0, len(file_bytes), PROT_READ, MAP_PRIVATE, 3, 0)
        self.assertEqual(res['returned'], 0x50000000)
        read_back = bytes(self.mu.mem_read(0x50000000, len(file_bytes)))
        self.assertEqual(read_back, file_bytes)
        # Remainder of 4 KiB page must be zeroed
        remainder = bytes(self.mu.mem_read(0x50000000 + len(file_bytes), 4096 - len(file_bytes)))
        self.assertEqual(remainder, bytes(4096 - len(file_bytes)))

    def test_fixed_mapping_over_existing_region_updates_protection(self):
        # Map 8 KiB anonymous
        self.mmap.request_mmap2(0x50000000, 8192, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_FIXED | MAP_ANONYMOUS, -1, 0)
        self.assertIn(0x50000000, self.mmap.mapped_pages)
        self.assertIn(0x50001000, self.mmap.mapped_pages)
        # MAP_FIXED on second page with file content
        self.fs.fds[4] = {'path': '/lib/data.so', 'data': b'SECTION_DATA', 'offset': 0}
        res = self.mmap.request_mmap2(0x50001000, 12, PROT_READ, MAP_PRIVATE | MAP_FIXED, 4, 0)
        self.assertEqual(res['returned'], 0x50001000)
        self.assertEqual(bytes(self.mu.mem_read(0x50001000, 12)), b'SECTION_DATA')

    def test_misaligned_fixed_address_rejected(self):
        res = self.mmap.request_mmap2(0x50000001, 4096, PROT_READ, MAP_PRIVATE | MAP_FIXED | MAP_ANONYMOUS, -1, 0)
        self.assertEqual(res['returned'], 0xffffffea)  # -EINVAL

    def test_zero_or_negative_length_rejected(self):
        res = self.mmap.request_mmap2(0, 0, PROT_READ, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0)
        self.assertEqual(res['returned'], 0xffffffea)

    def test_invalid_file_descriptor_returns_ebadf(self):
        res = self.mmap.request_mmap2(0, 4096, PROT_READ, MAP_PRIVATE, 99, 0)
        self.assertEqual(res['returned'], 0xfffffff7)  # -EBADF
        self.assertEqual(list(self.mu.mem_regions()), [])
        self.assertEqual(self.mmap.next_address, self.mmap.base_address)
        self.assertEqual(self.mmap.mapped_pages, set())

    def test_minus_one_fd_without_anonymous_flag_is_not_anonymous(self):
        for fd in (-1, 0xffffffff):
            self.assertEqual(self.mmap.request_mmap2(0, 4096, 3, MAP_PRIVATE, fd, 0)['returned'], 0xfffffff7)
        self.assertEqual(list(self.mu.mem_regions()), [])

    def test_bad_fd_fixed_request_preserves_existing_protection_and_bytes(self):
        self.mu.mem_map(0x50000000, 4096, PROT_READ)
        self.mu.mem_write(0x50000000, b'KEEP')
        self.mmap.register_range(0x50000000, 4096)
        before = list(self.mu.mem_regions())
        result = self.mmap.request_mmap2(0x50000000, 4096, 3, MAP_PRIVATE | MAP_FIXED, 99, 0)
        self.assertEqual(result['returned'], 0xfffffff7)
        self.assertEqual(list(self.mu.mem_regions()), before)
        self.assertEqual(bytes(self.mu.mem_read(0x50000000, 4)), b'KEEP')

    def test_nonfixed_hint_cannot_replace_initial_mapping(self):
        self.mu.mem_map(0x50000000, 4096, PROT_READ | PROT_EXEC)
        self.mu.mem_write(0x50000000, b'CODE')
        self.mmap.register_range(0x50000000, 4096)
        result = self.mmap.request_mmap2(0x50000000, 4096, 3, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0)
        self.assertEqual(result['returned'], 0x50010000)
        self.assertEqual(bytes(self.mu.mem_read(0x50000000, 4)), b'CODE')
        self.assertEqual(next(p for a, b, p in self.mu.mem_regions() if a == 0x50000000), 5)

    def test_unhinted_allocation_skips_previous_hint(self):
        first = self.mmap.request_mmap2(0x50000000, 4096, 3, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0)
        self.mu.mem_write(first['returned'], b'KEEP')
        second = self.mmap.request_mmap2(0, 4096, 3, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0)
        self.assertNotEqual(first['returned'], second['returned'])
        self.assertEqual(bytes(self.mu.mem_read(first['returned'], 4)), b'KEEP')

    def test_failed_boundary_request_does_not_advance_cursor(self):
        with self.assertRaises(UnsupportedMmap):
            self.mmap.request_mmap2(0, 0x10001000, 3, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0)
        self.assertEqual(self.mmap.next_address, self.mmap.base_address)

    def test_address_outside_ceiling_raises_unsupported(self):
        with self.assertRaises(UnsupportedMmap):
            self.mmap.request_mmap2(0x60000000, 4096, PROT_READ, MAP_PRIVATE | MAP_FIXED | MAP_ANONYMOUS, -1, 0)

    def test_search_low_base_allows_wrap_around_allocation(self):
        custom_mmap = GuestMmap(self.mu, self.fs, base_address=0x50000000, ceiling_address=0x50020000,
                                search_low_base=0x10000000)
        res1 = custom_mmap.request_mmap2(0, 0x20000, PROT_READ, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0)
        self.assertEqual(res1['returned'], 0x50000000)
        res2 = custom_mmap.request_mmap2(0, 0x10000, PROT_READ, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0)
        self.assertEqual(res2['returned'], 0x10000000)

    def test_configurable_base_address(self):
        custom_mmap = GuestMmap(self.mu, self.fs, base_address=0x04000000)
        self.assertEqual(custom_mmap.base_address, 0x04000000)
        res = custom_mmap.request_mmap2(0, 4096, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0)
        self.assertEqual(res['returned'], 0x04000000)

    def test_default_ceiling_is_strictly_0x5f000000(self):
        default_mmap = GuestMmap(self.mu, self.fs)
        self.assertEqual(default_mmap.ceiling_address, 0x5f000000)
        with self.assertRaises(UnsupportedMmap):
            default_mmap.request_mmap2(0x5f000000, 4096, PROT_READ, MAP_PRIVATE | MAP_FIXED | MAP_ANONYMOUS, -1, 0)

    def test_mprotect_success_and_unmapped_error(self):
        self.mmap.request_mmap2(0x50000000, 4096, PROT_READ, MAP_PRIVATE | MAP_FIXED | MAP_ANONYMOUS, -1, 0)
        res = self.mmap.request_mprotect(0x50000000, 4096, PROT_READ | PROT_WRITE)
        self.assertEqual(res['returned'], 0)
        # Misaligned address
        res_mis = self.mmap.request_mprotect(0x50000004, 4096, PROT_READ)
        self.assertEqual(res_mis['returned'], 0xffffffea)
        # Unmapped page
        res_unm = self.mmap.request_mprotect(0x50002000, 4096, PROT_READ)
        self.assertEqual(res_unm['returned'], 0xfffffff4)  # -ENOMEM

    def test_munmap_removes_pages(self):
        self.mmap.request_mmap2(0x50000000, 8192, PROT_READ, MAP_PRIVATE | MAP_FIXED | MAP_ANONYMOUS, -1, 0)
        self.assertIn(0x50000000, self.mmap.mapped_pages)
        self.assertIn(0x50001000, self.mmap.mapped_pages)
        res = self.mmap.request_munmap(0x50000000, 4096)
        self.assertEqual(res['returned'], 0)
        self.assertNotIn(0x50000000, self.mmap.mapped_pages)
        self.assertIn(0x50001000, self.mmap.mapped_pages)


if __name__ == '__main__':
    unittest.main()
