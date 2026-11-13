"""Unit tests for seed_mondrv_output (MonDrv::mp_output queue seed)."""
import struct
import unittest

import unicorn

from src.a6400.execution.interpreter_probe import seed_mondrv_output

PAGE = 0x52000000          # fake libMWF page
MP_OUTPUT = PAGE + 0xfe0   # stands in for base + mp_output
REGION = 0x53000000        # stands in for the allocator region


class MondrvOutputSeedTests(unittest.TestCase):
    def setUp(self):
        self.mu = unicorn.Uc(unicorn.UC_ARCH_ARM, unicorn.UC_MODE_THUMB)
        self.mu.mem_map(PAGE, 0x1000, unicorn.UC_PROT_ALL)
        self.mu.mem_map(REGION, 0x8000, unicorn.UC_PROT_ALL)

    def test_seeds_empty_queue_and_pointer(self):
        self.assertTrue(seed_mondrv_output(self.mu, MP_OUTPUT, REGION))
        obj = struct.unpack('<IIII', bytes(self.mu.mem_read(REGION, 16)))
        self.assertEqual(obj, (REGION + 0x10, REGION + 0x14, REGION + 0x20, 0x7bf0))
        self.assertEqual(bytes(self.mu.mem_read(REGION + 0x10, 8)), bytes(8))
        self.assertEqual(struct.unpack('<I', bytes(self.mu.mem_read(MP_OUTPUT, 4)))[0], REGION)

    def test_no_write_when_pointer_already_set(self):
        self.mu.mem_write(MP_OUTPUT, struct.pack('<I', 0x12345678))
        self.mu.mem_write(REGION, b'\xaa' * 16)
        self.assertFalse(seed_mondrv_output(self.mu, MP_OUTPUT, REGION))
        self.assertEqual(struct.unpack('<I', bytes(self.mu.mem_read(MP_OUTPUT, 4)))[0], 0x12345678)
        self.assertEqual(bytes(self.mu.mem_read(REGION, 16)), b'\xaa' * 16)


if __name__ == '__main__':
    unittest.main()
