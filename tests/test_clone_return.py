"""Constructed ARM syscall fixtures for clone's parent/child return boundary."""
import struct
import unittest

import unicorn
from unicorn import arm_const as arm

from project_paths import PROJECT_ROOT
from src.a6400.execution.guest_threads import GuestThreads, EXPECTED_PTHREAD_CLONE_FLAGS
from src.a6400.execution.interpreter_probe import InterpreterProbe
from test_interpreter_probe import make_elf


class CloneReturnTests(unittest.TestCase):
    def probe(self, flags=EXPECTED_PTHREAD_CLONE_FLAGS, writable=True):
        folder = PROJECT_ROOT / 'artifacts/tests/clone-return'
        folder.mkdir(parents=True, exist_ok=True)
        code = struct.pack('<5I', 0xe3a07078, 0xef000000, 0xe3e07000, 0xef000000, 0xeafffffe)
        interpreter = make_elf(folder / 'interpreter.elf', code, thumb=False)
        app = make_elf(folder / 'app.elf', bytes.fromhex('fee7'), dynamic=False)
        # Isolate clone dispatch without a firmware kuser template: this parent
        # fixture never schedules a child or executes a helper/device operation.
        probe = InterpreterProbe(syscall_policy='mmap', uname_profile={'raw_hex': bytes(390).hex()},
                                 filesystem={'nodes': {}, 'content_loader': lambda *args: b''})
        probe.prepare(app, interpreter, ['/clone-fixture'])
        probe.syscall_policy = 'threads'
        probe.threads = GuestThreads()
        probe.mu.mem_map(0x50000000, 4096, unicorn.UC_PROT_READ | unicorn.UC_PROT_WRITE)
        probe.mu.mem_write(0x50000000, b'KEEP')
        if not writable:
            probe.mu.mem_protect(0x50000000, 4096, unicorn.UC_PROT_READ)
        for register, value in ((arm.UC_ARM_REG_R0, flags),
                                (arm.UC_ARM_REG_R1, 0x60000000),
                                (arm.UC_ARM_REG_R2, 0x50000000),
                                (arm.UC_ARM_REG_R3, 0x12345000),
                                (arm.UC_ARM_REG_R4, 0x50000000),
                                (arm.UC_ARM_REG_LR, 0x12345678)):
            probe.mu.reg_write(register, value)
        return probe

    def test_original_svc_return_pc_is_copied_without_reading_child_stack(self):
        probe = self.probe()
        report = probe.run()
        self.assertEqual(report['status'], 'syscall_boundary')
        self.assertEqual(report['syscall_responses_supplied'], 1)
        self.assertEqual(probe.mu.reg_read(arm.UC_ARM_REG_R0), 1001)
        child = probe.threads.threads[1001]
        self.assertEqual(child.regs[arm.UC_ARM_REG_R0], 0)
        self.assertEqual(child.regs[arm.UC_ARM_REG_PC], 0x40000108)
        self.assertEqual(child.regs[arm.UC_ARM_REG_SP], 0x60000000)
        self.assertEqual(child.regs[arm.UC_ARM_REG_LR], 0x12345678)
        self.assertEqual(bytes(probe.mu.mem_read(0x50000000, 4)), struct.pack('<I', 1001))

    def test_read_only_parent_tid_stops_before_host_write_or_child_creation(self):
        probe = self.probe(writable=False)
        report = probe.run()
        self.assertEqual(report['status'], 'unsupported_thread_contract')
        self.assertEqual(report['syscall_responses_supplied'], 0)
        self.assertEqual(bytes(probe.mu.mem_read(0x50000000, 4)), b'KEEP')
        self.assertEqual(list(probe.threads.threads), [1000])

    def test_unknown_clone_flags_stop_before_host_write_or_child_creation(self):
        probe = self.probe(flags=EXPECTED_PTHREAD_CLONE_FLAGS | 0x4000)
        report = probe.run()
        self.assertEqual(report['status'], 'unsupported_thread_contract')
        self.assertEqual(report['syscall_responses_supplied'], 0)
        self.assertEqual(bytes(probe.mu.mem_read(0x50000000, 4)), b'KEEP')
        self.assertEqual(list(probe.threads.threads), [1000])
