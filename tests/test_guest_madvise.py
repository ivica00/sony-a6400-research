"""MADV_DONTNEED discards only owned private anonymous pages."""
import unittest

import unicorn
from src.a6400.execution.guest_mmap import GuestMmap, UnsupportedMmap


class MadviseTests(unittest.TestCase):
    def setUp(self):
        self.mu = unicorn.Uc(unicorn.UC_ARCH_ARM, unicorn.UC_MODE_ARM)
        self.fs = type('Files', (), {'fds': {3: {'path': '/lib/fixture', 'data': b'FILE'}}})()
        self.memory = GuestMmap(self.mu, self.fs)
        self.addr = self.memory.request_mmap2(0, 12288, 3, 0x22, -1, 0)['returned']
        self.mu.mem_write(self.addr, b'A' * 12288)

    def test_private_page_discard_preserves_neighbors_and_permissions(self):
        self.memory.request_mprotect(self.addr + 4096, 4096, 1)
        permissions = list(self.mu.mem_regions())
        writes = []
        self.memory.after_write = lambda address, size: writes.append((address, size))
        event = self.memory.request_madvise(self.addr + 4096, 1, 4)
        self.assertEqual(event['returned'], 0)
        self.assertEqual(event['discarded_bytes'], 4096)
        self.assertEqual(bytes(self.mu.mem_read(self.addr, 12288)), b'A' * 4096 + bytes(4096) + b'A' * 4096)
        self.assertEqual(list(self.mu.mem_regions()), permissions)
        self.assertEqual(writes, [(self.addr + 4096, 4096)])

    def test_missing_page_does_not_partially_discard(self):
        self.memory.request_munmap(self.addr + 8192, 4096)
        with self.assertRaises(UnsupportedMmap):
            self.memory.request_madvise(self.addr, 12288, 4)
        self.assertEqual(bytes(self.mu.mem_read(self.addr, 8192)), b'A' * 8192)

    def test_file_remapping_replaces_anonymous_ownership(self):
        self.memory.request_mmap2(self.addr + 4096, 4096, 3, 0x12, 3, 0)
        with self.assertRaises(UnsupportedMmap):
            self.memory.request_madvise(self.addr, 8192, 4)
        self.assertEqual(bytes(self.mu.mem_read(self.addr, 4)), b'AAAA')
        self.assertEqual(bytes(self.mu.mem_read(self.addr + 4096, 4)), b'FILE')

    def test_shared_and_device_memory_are_not_discarded(self):
        shared = self.memory.request_mmap2(0, 4096, 3, 0x21, -1, 0)['returned']
        self.memory.mark_device_range(self.addr + 4096, 4096, 'fixture-fb')
        for address in (shared, self.addr + 4096):
            with self.subTest(address=address), self.assertRaises(UnsupportedMmap):
                self.memory.request_madvise(address, 4096, 4)
        self.assertEqual(bytes(self.mu.mem_read(self.addr + 4096, 4)), b'AAAA')

    def test_initial_or_unregistered_mapping_is_not_owned_anonymous_ram(self):
        self.mu.mem_map(0x10000, 4096)
        self.memory.register_range(0x10000, 4096)
        self.mu.mem_map(0x20000, 4096)
        for address in (0x10000, 0x20000):
            with self.subTest(address=address), self.assertRaises(UnsupportedMmap):
                self.memory.request_madvise(address, 4096, 4)

    def test_unmapped_ownership_cannot_authorize_foreign_replacement(self):
        self.memory.request_munmap(self.addr, 4096)
        self.mu.mem_map(self.addr, 4096)
        self.mu.mem_write(self.addr, b'KEEP')
        with self.assertRaises(UnsupportedMmap):
            self.memory.request_madvise(self.addr, 4096, 4)
        self.assertEqual(bytes(self.mu.mem_read(self.addr, 4)), b'KEEP')

    def test_invalid_ranges_and_unsupported_advice_do_not_mutate_memory(self):
        for address, length in ((self.addr + 1, 1), (0xfffff000, 8192), (self.addr, -1)):
            event = self.memory.request_madvise(address, length, 4)
            self.assertEqual(event['returned'], (-22) & 0xffffffff)
        with self.assertRaises(UnsupportedMmap):
            self.memory.request_madvise(self.addr, 4096, 0)
        self.assertEqual(bytes(self.mu.mem_read(self.addr, 4)), b'AAAA')

    def test_zero_length_has_no_memory_effect(self):
        self.assertEqual(self.memory.request_madvise(self.addr, 0, 4)['discarded_bytes'], 0)
        self.assertEqual(bytes(self.mu.mem_read(self.addr, 4)), b'AAAA')


class MadviseArmTests(unittest.TestCase):
    def probe(self, enabled):
        import struct
        from test_interpreter_probe import make_elf
        from project_paths import PROJECT_ROOT
        from src.a6400.execution.interpreter_probe import InterpreterProbe
        folder = PROJECT_ROOT / 'artifacts/tests/madvise-arm'
        folder.mkdir(parents=True, exist_ok=True)
        words = (0xe59f0020, 0xe3a01a01, 0xe3a02004, 0xe3a070dc, 0xef000000,
                 0xe59f300c, 0xe5934000, 0xe3e07000, 0xef000000, 0xeafffffe, 0x50000000)
        image = make_elf(folder / 'interpreter.elf', struct.pack('<11I', *words), thumb=False)
        app = make_elf(folder / 'app.elf', bytes.fromhex('fee7'), dynamic=False)
        probe = InterpreterProbe(syscall_policy='mmap', uname_profile={'raw_hex': bytes(390).hex()},
                                 filesystem={'nodes': {}, 'content_loader': lambda *args: b''},
                                 madvise_policy='private-anonymous-dontneed' if enabled else 'stop')
        probe.prepare(app, image, ['/test'])
        probe.mmap.request_mmap2(0x50000000, 4096, 3, 0x22, -1, 0)
        probe.mu.mem_write(0x50000000, b'KEEP')
        return probe

    def test_arm_madvise_is_explicit_and_changes_subsequent_guest_read(self):
        from unicorn import arm_const as arm
        probe = self.probe(True)
        report = probe.run()
        self.assertEqual(report['status'], 'syscall_boundary')
        self.assertEqual(report['boundary']['r7'], 0xffffffff)
        self.assertEqual(probe.mu.reg_read(arm.UC_ARM_REG_R4), 0)
        self.assertEqual(report['serviced_syscalls'][0]['syscall'], 'madvise')
        self.assertEqual(report['serviced_syscalls'][0]['returned'], 0)
        self.assertEqual(bytes(probe.mu.mem_read(0x50000000, 4)), bytes(4))

    def test_default_policy_stops_without_discard(self):
        probe = self.probe(False)
        report = probe.run()
        self.assertEqual(report['status'], 'syscall_boundary')
        self.assertEqual(report['boundary']['r7'], 220)
        self.assertEqual(report['syscall_responses_supplied'], 0)
        self.assertEqual(bytes(probe.mu.mem_read(0x50000000, 4)), b'KEEP')
