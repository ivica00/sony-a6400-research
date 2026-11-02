"""Unit tests for ARM Linux kernel helper (kuser) vectors and TLS management."""
import hashlib
import struct
import unittest
from pathlib import Path

import unicorn
from unicorn import arm_const as arm

from project_paths import PROJECT_ROOT
from src.a6400.execution.guest_kuser import (
    GuestKuser,
    extract_kuser_template,
    EXPECTED_KUSER_SHA256,
    KUSER_PAGE_ADDR,
    KUSER_PAGE_SIZE,
    KUSER_TEMPLATE_OFFSET,
    KUSER_TEMPLATE_SIZE,
    KUSER_TLS_SOFTWARE_SLOT,
    KUSER_VERSION_SLOT,
)
from src.a6400.execution.guest_mmap import GuestMmap


class TestGuestKuser(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.kernel_path = PROJECT_ROOT / 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked/vmlinux.bin'
        if cls.kernel_path.exists():
            cls.template = extract_kuser_template(cls.kernel_path)
        else:
            cls.template = None

    def setUp(self):
        self.mu = unicorn.Uc(unicorn.UC_ARCH_ARM, unicorn.UC_MODE_ARM)
        self.mu.ctl_set_cpu_model(arm.UC_CPU_ARM_CORTEX_A9)

    def test_extract_kuser_template(self):
        if self.template is None:
            self.skipTest('Kernel image not available')
        self.assertEqual(len(self.template), KUSER_TEMPLATE_SIZE)
        self.assertEqual(hashlib.sha256(self.template).hexdigest(), EXPECTED_KUSER_SHA256)
        version = struct.unpack_from('<I', self.template, 0x9c)[0]
        self.assertEqual(version, 5)

    def test_extract_kuser_template_corrupt(self):
        # Truncated data
        with self.assertRaises(ValueError):
            extract_kuser_template(b'short')
        # Corrupt data
        dummy = bytearray(0x388fe0 + 160)
        with self.assertRaises(ValueError):
            extract_kuser_template(dummy)

    def test_guest_kuser_map_page(self):
        dummy_template = bytearray(self.template) if self.template else None
        if dummy_template is None:
            self.skipTest('Template not available')
        kuser = GuestKuser(self.mu, dummy_template)
        kuser.map_page()

        # Verify page read
        read_bytes = bytes(self.mu.mem_read(KUSER_PAGE_ADDR + KUSER_TEMPLATE_OFFSET, KUSER_TEMPLATE_SIZE))
        self.assertEqual(read_bytes, dummy_template)
        # Verify version slot at 0xffff0ffc
        version_bytes = bytes(self.mu.mem_read(KUSER_VERSION_SLOT, 4))
        self.assertEqual(struct.unpack('<I', version_bytes)[0], 5)

    def test_guest_kuser_set_tls(self):
        if self.template is None:
            self.skipTest('Template not available')
        kuser = GuestKuser(self.mu, self.template)
        kuser.map_page()

        test_tls = 0x503204c0
        res = kuser.set_tls(test_tls)
        self.assertEqual(res, test_tls)

        # Check CP15 C13 register
        self.assertEqual(self.mu.reg_read(arm.UC_ARM_REG_C13_C0_3), test_tls)
        # Check software memory slot at 0xffff0ff0
        slot_bytes = bytes(self.mu.mem_read(KUSER_TLS_SOFTWARE_SLOT, 4))
        self.assertEqual(struct.unpack('<I', slot_bytes)[0], test_tls)

    def test_guest_mmap_register_range(self):
        class DummyFS:
            fds = {}

        mmap_mgr = GuestMmap(self.mu, DummyFS())
        # Map a test region in unicorn
        self.mu.mem_map(0x40000000, 0x20000, unicorn.UC_PROT_READ | unicorn.UC_PROT_EXEC)
        # Register the range with GuestMmap
        mmap_mgr.register_range(0x40000000, 0x20000)

        # mprotect should now succeed on that range
        res = mmap_mgr.request_mprotect(0x4001f000, 0x1000, unicorn.UC_PROT_READ)
        self.assertEqual(res['returned'], 0)
        self.assertEqual(res['reason'], 'mprotect_applied')

        # Unregistered address should still return ENOMEM
        res_fail = mmap_mgr.request_mprotect(0x30000000, 0x1000, unicorn.UC_PROT_READ)
        self.assertEqual(res_fail['returned'], 0xfffffff4)
        self.assertEqual(res_fail['reason'], 'ENOMEM_unmapped_page')


if __name__ == '__main__':
    unittest.main()
