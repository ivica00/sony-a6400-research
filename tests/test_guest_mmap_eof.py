"""GuestMmap 'sigbus' EOF policy, sys_read fd-check, and universal kuser extraction tests."""
from pathlib import Path
import unittest

import unicorn
import unicorn.arm_const as arm

from src.a6400.execution.guest_kuser import (
    EXPECTED_KUSER_SHA256, KUSER_TEMPLATE_SIZE, VMLINUX_KUSER_OFFSET, extract_kuser_template)
from src.a6400.execution.guest_mmap import (
    GuestMmap, PROT_READ, PROT_WRITE, MAP_PRIVATE, MAP_ANONYMOUS, MAP_FIXED)
from src.a6400.execution.interpreter_probe import InterpreterProbe


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
        self.assertNotIn(0x50002000, self.mmap.page_backing)

    def test_constructor_eof_policy_validation(self):
        mmap = GuestMmap(self.mu, self.fs, eof_policy='sigbus')
        self.assertEqual(mmap.eof_policy, 'sigbus')
        with self.assertRaises(ValueError):
            GuestMmap(self.mu, self.fs, eof_policy='invalid')


class ProbeAndUniversalTests(unittest.TestCase):
    def _make_probe(self, mmap_eof_policy='zero-fill'):
        uname = {
            'raw_hex': '00' * 390,
            'source_sha256': '0' * 64,
            'file_offset': 0,
        }
        filesystem = {'nodes': {}, 'content_loader': None}
        return InterpreterProbe(
            syscall_policy='mmap',
            uname_profile=uname,
            filesystem=filesystem,
            mmap_eof_policy=mmap_eof_policy,
        )

    def test_memory_boundary_reports_sigbus_for_beyond_eof_page(self):
        probe = self._make_probe(mmap_eof_policy='sigbus')
        self.assertEqual(probe.report['mmap_eof_policy'], 'sigbus')
        probe.filesystem.fds[3] = {'path': '/usr/lib/short.so', 'data': b'A' * 5000, 'offset': 0}
        res = probe.mmap.request_mmap2(0, 0x4000, PROT_READ, MAP_PRIVATE, 3, 0)
        addr = res['mapping']['beyond_eof']['address'] + 0x10
        probe.mu.reg_write(arm.UC_ARM_REG_PC, 0x10000)
        keep_going = probe._memory(probe.mu, unicorn.UC_MEM_READ_UNMAPPED, addr, 4, 0, None)
        self.assertFalse(keep_going)
        self.assertEqual(probe.report['status'], 'memory_boundary')
        boundary = probe.report['boundary']
        self.assertEqual(boundary['signal'], 'SIGBUS')
        self.assertEqual(boundary['reason'], 'file_mapping_access_beyond_eof')
        self.assertEqual(boundary['path'], '/usr/lib/short.so')
        self.assertEqual(boundary['mapping_address'], res['returned'])
        self.assertEqual(boundary['file_offset'], addr - res['returned'])

    def test_sys_read_tty_fd_reads_r0_before_check(self):
        probe = self._make_probe()
        probe.syscall_policy = 'uipc'
        probe.mu.mem_map(0x10000, 0x1000)
        probe.mu.mem_write(0x10000, b'\x00\x00\x00\xef')  # svc #0 (ARM)
        probe.filesystem.fds[7] = {'device': 'tty', 'path': '/dev/tty'}
        probe.mu.reg_write(arm.UC_ARM_REG_R0, 7)
        probe.mu.reg_write(arm.UC_ARM_REG_R7, 3)  # __NR_read
        probe.mu.reg_write(arm.UC_ARM_REG_PC, 0x10004)
        probe._interrupt(probe.mu, 2, None)
        self.assertEqual(probe.report['status'], 'unsupported_tty_contract')
        self.assertEqual(probe.report['boundary']['reason'], 'tty_read_not_supplied')

    def test_sched_getaffinity_returns_mask_byte_count(self):
        probe = self._make_probe()
        probe.syscall_policy = 'threads'  # the 242 branch sits under the threads policy
        probe.mu.mem_map(0x10000, 0x1000)
        probe.mu.mem_write(0x10000, b'\x00\x00\x00\xef')  # svc #0 (ARM)
        probe.mu.reg_write(arm.UC_ARM_REG_R0, 0)
        probe.mu.reg_write(arm.UC_ARM_REG_R1, 128)
        probe.mu.reg_write(arm.UC_ARM_REG_R2, 0x10100)
        probe.mu.reg_write(arm.UC_ARM_REG_R7, 242)  # __NR_sched_getaffinity
        probe.mu.reg_write(arm.UC_ARM_REG_PC, 0x10004)
        probe._interrupt(probe.mu, 2, None)
        self.assertEqual(probe.mu.reg_read(arm.UC_ARM_REG_R0), 4)
        self.assertEqual(probe.report['serviced_syscalls'][-1]['returned'], 4)
        self.assertEqual(bytes(probe.mu.mem_read(0x10100, 4)), b'\x01\x00\x00\x00')

        probe.mu.reg_write(arm.UC_ARM_REG_R1, 2)  # buffer smaller than the 4-byte mask
        probe.mu.reg_write(arm.UC_ARM_REG_PC, 0x10004)
        probe._interrupt(probe.mu, 2, None)
        self.assertEqual(probe.mu.reg_read(arm.UC_ARM_REG_R0), 0xFFFFFFEA)  # -EINVAL
        self.assertEqual(probe.report['serviced_syscalls'][-1]['returned'], -22)

    def test_extract_kuser_template_unknown_kernel_fails_closed(self):
        with self.assertRaises(ValueError):
            extract_kuser_template(b'\x00' * (VMLINUX_KUSER_OFFSET + KUSER_TEMPLATE_SIZE))

    def test_extract_kuser_template_scans_unknown_kernel_offset(self):
        vmlinux = Path('firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked/vmlinux.bin')
        if not vmlinux.exists():
            self.skipTest('Local firmware vmlinux.bin not present')
        template = extract_kuser_template(vmlinux)
        relocated = b'\x11' * 0x1234 + template + b'\x22' * 0x500
        extracted = extract_kuser_template(relocated)
        self.assertEqual(extracted, template)
        self.assertEqual(len(extracted), KUSER_TEMPLATE_SIZE)
        self.assertEqual(__import__('hashlib').sha256(extracted).hexdigest(), EXPECTED_KUSER_SHA256)


if __name__ == '__main__':
    unittest.main()
