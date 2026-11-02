import unittest

from tools.research.wbi_dmm_handle import mutation_allowed


class MutationBoundsTests(unittest.TestCase):
    def test_complete_access_must_fit_one_explicit_interval(self):
        ranges = [(0x1000, 0x1004), (0x1004, 0x1008)]
        self.assertTrue(mutation_allowed(0x1000, 4, ranges))
        self.assertTrue(mutation_allowed(0x1006, 2, ranges))
        self.assertFalse(mutation_allowed(0x1002, 4, ranges))
        self.assertFalse(mutation_allowed(0x1008, 1, ranges))
        self.assertFalse(mutation_allowed(0x0fff, 1, ranges))

    def test_invalid_sizes_and_arm32_wraparound_stop(self):
        ranges = [(0, 1 << 32)]
        for address, size in ((-1, 1), (0, 0), (0, -1), (0, 9), (0xffffffff, 2), (1 << 32, 1)):
            with self.subTest(address=address, size=size):
                self.assertFalse(mutation_allowed(address, size, ranges))
        self.assertTrue(mutation_allowed(0xfffffffc, 4, ranges))

    def test_empty_or_escaping_permission_ranges_do_not_supply_memory(self):
        self.assertFalse(mutation_allowed(0x1000, 4, []))
        self.assertFalse(mutation_allowed(0x1000, 4, [(-1, 0x2000)]))
        self.assertFalse(mutation_allowed(0x1000, 4, [(0, (1 << 32) + 1)]))
