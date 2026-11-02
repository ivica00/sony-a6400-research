"""Guest heap observable behavior, including failure and page ownership."""
import unittest
from unittest.mock import patch

import unicorn
from src.a6400.execution.guest_brk import GuestBrk, initial_break


class GuestBrkTests(unittest.TestCase):
    def setUp(self):
        self.mu = unicorn.Uc(unicorn.UC_ARCH_ARM, unicorn.UC_MODE_ARM)
        self.start = 0x10000
        self.heap = GuestBrk(self.mu, self.start, max_growth=0x10000)

    def test_initial_break_derived_from_segment_end(self):
        self.assertEqual(initial_break({'segments': [{'p_vaddr': 0x8000, 'p_memsz': 0x3001},
                                                    {'p_vaddr': 0x20000, 'p_memsz': 0}]}), 0xc000)

    def test_query_does_not_allocate(self):
        event = self.heap.request(0)
        self.assertEqual(event['returned'], self.start)
        self.assertEqual(event['reason'], 'query')
        self.assertEqual(list(self.mu.mem_regions()), [])

    def test_growth_is_zero_filled_rw(self):
        event = self.heap.request(self.start + 1)
        self.assertEqual(event['returned'], self.start + 1)
        self.assertEqual(bytes(self.mu.mem_read(self.start, 4096)), bytes(4096))
        region = list(self.mu.mem_regions())[0]
        self.assertEqual(region, (self.start, self.start + 4095, unicorn.UC_PROT_READ | unicorn.UC_PROT_WRITE))

    def test_same_page_shrink_preserves_bytes(self):
        self.heap.request(self.start + 100)
        self.mu.mem_write(self.start + 60, b'kept')
        event = self.heap.request(self.start + 10)
        self.assertEqual(event['reason'], 'same_page')
        self.assertEqual(bytes(self.mu.mem_read(self.start + 60, 4)), b'kept')

    def test_shrink_unmaps_and_regrowth_zeroes_pages(self):
        self.heap.request(self.start + 8192)
        self.mu.mem_write(self.start + 4096, b'old')
        self.heap.request(self.start + 4096)
        with self.assertRaises(unicorn.UcError):
            self.mu.mem_read(self.start + 4096, 1)
        self.heap.request(self.start + 8192)
        self.assertEqual(bytes(self.mu.mem_read(self.start + 4096, 3)), bytes(3))

    def test_below_start_and_limit_return_unchanged_break(self):
        self.heap.request(self.start + 10)
        for request in (self.start - 1, self.heap.ceiling + 1):
            self.assertEqual(self.heap.request(request)['returned'], self.start + 10)
        self.assertEqual(self.heap.current, self.start + 10)

    def test_collision_leaves_foreign_memory_and_heap_unchanged(self):
        self.mu.mem_map(self.start + 4096, 4096)
        self.mu.mem_write(self.start + 4096, b'foreign')
        event = self.heap.request(self.start + 8192)
        self.assertEqual(event['reason'], 'mapping_collision_or_guard')
        self.assertEqual(event['returned'], self.start)
        self.assertEqual(bytes(self.mu.mem_read(self.start + 4096, 7)), b'foreign')

    def test_guard_page_collision_blocks_adjacent_growth(self):
        self.mu.mem_map(self.start + 4096, 4096)
        event = self.heap.request(self.start + 1)
        self.assertEqual(event['reason'], 'mapping_collision_or_guard')
        self.assertEqual(list(self.mu.mem_regions())[0][0], self.start + 4096)

    def test_allocation_failure_returns_old_break(self):
        with patch.object(self.mu, 'mem_map', side_effect=unicorn.UcError(unicorn.UC_ERR_NOMEM)):
            event = self.heap.request(self.start + 1)
        self.assertEqual(event['reason'], 'allocation_failed')
        self.assertEqual(self.heap.current, self.start)
        self.assertEqual(list(self.mu.mem_regions()), [])

    def test_unmap_failure_preserves_break(self):
        self.heap.request(self.start + 8192)
        with patch.object(self.mu, 'mem_unmap', side_effect=unicorn.UcError(unicorn.UC_ERR_ARG)):
            event = self.heap.request(self.start)
        self.assertEqual(event['reason'], 'unmap_failed')
        self.assertEqual(self.heap.current, self.start + 8192)

    def test_limits_are_checked_before_same_page_update(self):
        heap = GuestBrk(self.mu, self.start, max_growth=10)
        heap.request(self.start + 1)
        self.assertEqual(heap.request(self.start + 11)['reason'], 'experimental_heap_limit')
        self.assertEqual(heap.current, self.start + 1)

    def test_invalid_bounds_and_requests(self):
        with self.assertRaises(ValueError):
            GuestBrk(self.mu, self.start + 1)
        for request in (-1, 0x100000000):
            with self.assertRaises(ValueError):
                self.heap.request(request)


if __name__ == '__main__':
    unittest.main()
