"""--uipc-sync-direct yield: snd_sync_direct (ioctl 0x80000006) reuses the sched_yield switch."""
import struct
import unittest
from unittest import mock

from unicorn import arm_const as arm

from project_paths import PROJECT_ROOT
from src.a6400.execution.guest_threads import GuestThreads
from src.a6400.execution.guest_uipc import GuestUipc, UIPC_CMD_SND_SYNC_DIRECT
from src.a6400.execution.interpreter_probe import InterpreterProbe
from test_interpreter_probe import make_elf


class UipcSyncDirectYieldTests(unittest.TestCase):
    def run_send(self, mode):
        """Thumb fixture: ioctl(fd 3, 0x80000006, arg); exit. Returns (probe, report, yield mock)."""
        folder = PROJECT_ROOT / 'artifacts/tests/uipc-sync-direct-yield'
        folder.mkdir(parents=True, exist_ok=True)
        interp = make_elf(folder / f'interpreter-{mode}.elf', bytes.fromhex('362700df012700dffee7'), thumb=True)
        app = make_elf(folder / f'app-{mode}.elf', bytes.fromhex('fee7'), dynamic=False)
        probe = InterpreterProbe(syscall_policy='mmap', uname_profile={'raw_hex': bytes(390).hex()},
                                 filesystem={'nodes': {}, 'content_loader': lambda *args: b''})
        probe.prepare(app, interp, ['/sync-direct-fixture'])
        probe.syscall_policy = 'threads'
        probe.uipc = GuestUipc()
        probe.uipc.sync_direct_mode = mode
        probe.threads = GuestThreads()
        probe.filesystem.fds[3] = {'device': 'uipc', 'path': '/dev/uipc'}
        base = 0x50000000
        probe.mu.mem_map(base, 4096)
        probe.mu.mem_write(base, struct.pack('<2I', 0x1234, base + 64))   # queue, buf pointer
        probe.mu.mem_write(base + 64, struct.pack('<4I', 16, 0, 0, 0))    # header: total 16, no payload
        for register, value in ((arm.UC_ARM_REG_R0, 3), (arm.UC_ARM_REG_R1, UIPC_CMD_SND_SYNC_DIRECT),
                                (arm.UC_ARM_REG_R2, base)):
            probe.mu.reg_write(register, value)
        with mock.patch.object(probe.threads, 'handle_sched_yield',
                               return_value=(None, {'syscall': 'sched_yield'})) as yield_primitive:
            report = probe.run(instruction_budget=100)
        return probe, report, yield_primitive

    def test_yield_mode_invokes_sched_yield_primitive_after_send(self):
        probe, report, yield_primitive = self.run_send('yield')
        yield_primitive.assert_called_once_with()
        sends = [e for e in report['serviced_syscalls'] if e.get('cmd') == UIPC_CMD_SND_SYNC_DIRECT]
        self.assertEqual(len(sends), 1)
        self.assertEqual(sends[0]['returned'], 0)
        self.assertIn('yield_to', sends[0])
        self.assertEqual(probe.uipc.transactions[-1]['type'], 'snd_sync_direct')
        self.assertFalse(probe.uipc.yield_requested)

    def test_return_mode_does_not_yield(self):
        probe, report, yield_primitive = self.run_send('return')
        yield_primitive.assert_not_called()
        sends = [e for e in report['serviced_syscalls'] if e.get('cmd') == UIPC_CMD_SND_SYNC_DIRECT]
        self.assertEqual(len(sends), 1)
        self.assertNotIn('yield_to', sends[0])
        self.assertEqual(probe.uipc.transactions[-1]['type'], 'snd_sync_direct')


if __name__ == '__main__':
    unittest.main()
