import stat
import struct
import tempfile
import unittest
from pathlib import Path

import unicorn
from unicorn import arm_const as arm

from src.a6400.execution.guest_checkpoint import restore_checkpoint, save_checkpoint
from src.a6400.execution.guest_filesystem import GuestFilesystem
from src.a6400.execution.guest_threads import GuestThreads
from src.a6400.execution.guest_uipc import GuestUipc


class MockFilesystem:
    def __init__(self):
        self.fds = {3: {'path': '/dev/uipc', 'device': 'uipc'}}
        self.cache = {'/usr/lib/test.so': b'TEST_BYTES'}


class MockHeap:
    def __init__(self):
        self.current = 0x12000
        self.start = 0x10000
        self.ceiling = 0x20000


class MockMmap:
    def __init__(self):
        self.next_address = 0x51000000
        self.mapped_pages = {0x50000000}
        self.page_backing = {0x50000000: {'kind': 'anonymous'}}
        self.mappings = [{'address': 0x50000000, 'length': 0x1000}]
        self.base_address = 0x50000000
        self.ceiling_address = 0x5f000000
        self.search_low_base = 0x10000000


class MockProbe:
    def __init__(self):
        self.mu = unicorn.Uc(unicorn.UC_ARCH_ARM, unicorn.UC_MODE_ARM)
        self.instructions = 123456
        self.signal_handlers = {4: {'handler': 0x40001000, 'flags': 0, 'restorer': 0, 'mask': b'\x00' * 8}}
        self.report = {
            'serviced_syscalls': [{'syscall': 'test', 'returned': 0}],
            'syscall_responses_supplied': 1,
            'loaded_modules': ['/usr/kmod/test.ko'],
        }
        self.filesystem = MockFilesystem()
        self.threads = GuestThreads(initial_tid=1000)
        self.uipc = GuestUipc()
        self.heap = MockHeap()
        self.mmap = MockMmap()


class TestGuestCheckpoint(unittest.TestCase):
    def test_unanswered_svc_is_retried_in_both_instruction_modes(self):
        for thumb in (False, True):
            with self.subTest(thumb=thumb):
                p1 = MockProbe()
                p1.mu.mem_map(0x10000, 0x1000, unicorn.UC_PROT_ALL)
                code = b'\x00\xdf\x07\x21' if thumb else bytes.fromhex('000000ef0710a0e3')
                p1.mu.mem_write(0x10000, code)
                cpsr = p1.mu.reg_read(arm.UC_ARM_REG_CPSR)
                p1.mu.reg_write(arm.UC_ARM_REG_CPSR, cpsr | 0x20 if thumb else cpsr & ~0x20)
                size = 2 if thumb else 4
                p1.mu.reg_write(arm.UC_ARM_REG_PC, (0x10000 + size) | int(thumb))
                p1.mu.reg_write(arm.UC_ARM_REG_R0, 0x1234)
                p1.mu.reg_write(arm.UC_ARM_REG_R7, 54)
                p1.report.update(status='unsupported_uipc_contract', boundary={'pc': 0x10000 + size, 'r7': 54})
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / 'pending.ckpt'
                    save_checkpoint(p1, path)
                    p2 = MockProbe()
                    restore_checkpoint(p2, path, exact=True)
                calls = []
                def interrupt(uc, number, _):
                    calls.append(uc.reg_read(arm.UC_ARM_REG_R7))
                    uc.reg_write(arm.UC_ARM_REG_R0, 0)
                p2.mu.hook_add(unicorn.UC_HOOK_INTR, interrupt)
                p2.mu.emu_start(p2.entry, 0x10000 + len(code), count=2)
                self.assertEqual(calls, [54])
                self.assertEqual(p2.mu.reg_read(arm.UC_ARM_REG_R0), 0)
                self.assertEqual(p2.mu.reg_read(arm.UC_ARM_REG_R1), 7)

    def test_invalid_svc_boundary_cannot_resume(self):
        p1 = MockProbe()
        p1.mu.mem_map(0x10000, 0x1000, unicorn.UC_PROT_ALL)
        p1.mu.mem_write(0x10000, bytes.fromhex('0000a0e1'))
        p1.mu.reg_write(arm.UC_ARM_REG_PC, 0x10004)
        p1.report.update(status='syscall_boundary', boundary={'pc': 0x10004})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'invalid.ckpt'
            save_checkpoint(p1, path)
            with self.assertRaisesRegex(ValueError, 'not_verified_eabi'):
                restore_checkpoint(MockProbe(), path, exact=True)

    def test_save_and_restore_checkpoint(self):
        # 1. Setup mock probe with mapped memory and register state
        p1 = MockProbe()
        p1.mu.mem_map(0x10000, 0x2000, unicorn.UC_PROT_ALL)
        p1.mu.mem_write(0x10000, b'HELLO CHECKPOINT 12345')
        p1.mu.reg_write(arm.UC_ARM_REG_R0, 0x42)
        p1.mu.reg_write(arm.UC_ARM_REG_R7, 197)
        p1.mu.reg_write(arm.UC_ARM_REG_PC, 0x10004)

        # 2. Save checkpoint
        with tempfile.TemporaryDirectory() as tmpdir:
            ckpt_path = Path(tmpdir) / 'test.ckpt'
            saved_size = save_checkpoint(p1, ckpt_path)
            self.assertGreater(saved_size, 0)
            self.assertTrue(ckpt_path.exists())

            # 3. Restore into clean probe
            p2 = MockProbe()
            restore_checkpoint(p2, ckpt_path)

            # 4. Verify registers and memory
            self.assertEqual(p2.mu.reg_read(arm.UC_ARM_REG_R0), 0x42)
            self.assertEqual(p2.mu.reg_read(arm.UC_ARM_REG_R7), 197)
            self.assertEqual(p2.mu.reg_read(arm.UC_ARM_REG_PC), 0x10004)
            self.assertEqual(bytes(p2.mu.mem_read(0x10000, 22)), b'HELLO CHECKPOINT 12345')

            # 5. Verify subsystem states
            self.assertEqual(p2.instructions, 123456)
            self.assertEqual(p2.filesystem.fds[3]['path'], '/dev/uipc')
            self.assertEqual(p2.filesystem.cache['/usr/lib/test.so'], b'TEST_BYTES')
            self.assertEqual(p2.threads.current_tid, 1000)
            self.assertEqual(p2.heap.current, 0x12000)
            self.assertEqual(p2.mmap.next_address, 0x51000000)
            self.assertEqual(p2.mmap.mapped_pages, {0x50000000})
            self.assertEqual(p2.report['syscall_responses_supplied'], 1)
            self.assertEqual(p2.report['loaded_modules'], ['/usr/kmod/test.ko'])


    def test_v2_checkpoint_preserves_uipc_callback_and_waiter_state(self):
        """E0302/E1: v2 restore must keep in-flight callback/waiter bookkeeping."""
        p1 = MockProbe()
        p1.threads.uipc_waiters = {0x12002da: [1005], 0x61003c: [1015, 1017]}
        p1.uipc.callback_inflight = {7: {'queue': 0x61003c, 'msg_ptr': 0x503304ac}}
        p1.uipc.sync_callback_inflight = {9: {'queue': 0x61003c, 'callback': 0x52f3b0dd}}
        p1.uipc.callback_proxy_owners = {0: 1001, 1: 1002, 2: 1003, 3: 1006}
        with tempfile.TemporaryDirectory() as tmpdir:
            ckpt_path = Path(tmpdir) / 'uipc-v2.ckpt'
            save_checkpoint(p1, ckpt_path)
            p2 = MockProbe()
            restore_checkpoint(p2, ckpt_path, exact=True)
        self.assertEqual(p2.threads.uipc_waiters, p1.threads.uipc_waiters)
        self.assertEqual(p2.uipc.callback_inflight, p1.uipc.callback_inflight)
        self.assertEqual(p2.uipc.sync_callback_inflight, p1.uipc.sync_callback_inflight)
        self.assertEqual(p2.uipc.callback_proxy_owners, p1.uipc.callback_proxy_owners)
        # Restored state is live, not a stale copy: a follow-up save keeps it.
        with tempfile.TemporaryDirectory() as tmpdir:
            ckpt_path = Path(tmpdir) / 'uipc-v2-again.ckpt'
            save_checkpoint(p2, ckpt_path)
            p3 = MockProbe()
            restore_checkpoint(p3, ckpt_path, exact=True)
        self.assertEqual(p3.threads.uipc_waiters, p1.threads.uipc_waiters)
        self.assertEqual(p3.uipc.callback_inflight, p1.uipc.callback_inflight)
        self.assertEqual(p3.uipc.callback_proxy_owners, p1.uipc.callback_proxy_owners)


    def test_checkpoint_saves_and_restores_filesystem_cwd(self):
        d = {'kind': 'directory', 'mode': stat.S_IFDIR | 0o755, 'uid': 0, 'gid': 0}
        nodes = {'/': dict(d), '/lib': dict(d),
                 '/lib/file': {'kind': 'file', 'mode': stat.S_IFREG | 0o644, 'uid': 0, 'gid': 0, 'size': 1}}

        def make_probe():
            probe = MockProbe()
            probe.mu.mem_map(0x10000, 0x1000, unicorn.UC_PROT_ALL)
            probe.filesystem = GuestFilesystem(probe.mu, dict(nodes), lambda path, node: b'x')
            return probe

        p1 = make_probe()
        p1.mu.mem_write(0x10100, b'/lib' + bytes(1))
        self.assertEqual(p1.filesystem.request(12, [0x10100, 0, 0])['returned'], 0)
        self.assertEqual(p1.filesystem.cwd, '/lib')

        with tempfile.TemporaryDirectory() as tmpdir:
            ckpt_path = Path(tmpdir) / 'cwd.ckpt'
            save_checkpoint(p1, ckpt_path)
            p2 = make_probe()
            restore_checkpoint(p2, ckpt_path)
            self.assertEqual(p2.filesystem.cwd, '/lib')
            p2.mu.mem_write(0x10200, b'file' + bytes(1))
            opened = p2.filesystem.request(5, [0x10200, 0, 0])
            self.assertIn(opened['returned'], p2.filesystem.fds)
            self.assertEqual(opened['path'], '/lib/file')

            # a checkpoint without a cwd leaves cwd unset, so relative paths still stop
            p3 = make_probe()
            save_checkpoint(make_probe(), ckpt_path)
            restore_checkpoint(p3, ckpt_path)
            self.assertFalse(hasattr(p3.filesystem, 'cwd'))


if __name__ == '__main__':
    unittest.main()


class TestRunGuardThumb(unittest.TestCase):
    def test_budget_stop_keeps_thumb_state(self):
        from types import SimpleNamespace
        from src.a6400.execution.interpreter_probe import InterpreterProbe
        for cpsr in (0x30, 0x10):
            uc = unicorn.Uc(unicorn.UC_ARCH_ARM, unicorn.UC_MODE_ARM)
            uc.mem_map(0x1000, 0x1000)
            uc.reg_write(arm.UC_ARM_REG_CPSR, cpsr)
            stub = SimpleNamespace(PROGRESS_SYSCALLS=(5,), stall_syscalls=0, report={'instruction_budget': 1}, instructions=1)
            self.assertTrue(InterpreterProbe._run_guard(stub, uc, 5, 0x1000))
            self.assertEqual(uc.reg_read(arm.UC_ARM_REG_CPSR) & 0x20, cpsr & 0x20)
