"""--uipc-timer-service emulated: queue 0x910042 counter reply, queue 0x910041 timed wait."""
import struct
import unittest

from unicorn import arm_const as arm

from project_paths import PROJECT_ROOT
from src.a6400.execution.guest_threads import GuestThreads
from src.a6400.execution.guest_uipc import GuestUipc, UIPC_CMD_SND_SYNC_DIRECT
from src.a6400.execution.interpreter_probe import InterpreterProbe
from test_interpreter_probe import make_elf

BASE = 0x50000000


class UipcTimerServiceTests(unittest.TestCase):
    def make_probe(self, tag):
        """Thumb fixture: ioctl(fd 3, 0x80000006, arg); exit."""
        folder = PROJECT_ROOT / 'artifacts/tests/uipc-timer-service'
        folder.mkdir(parents=True, exist_ok=True)
        interp = make_elf(folder / f'interpreter-{tag}.elf', bytes.fromhex('362700df012700dffee7'), thumb=True)
        app = make_elf(folder / f'app-{tag}.elf', bytes.fromhex('fee7'), dynamic=False)
        probe = InterpreterProbe(syscall_policy='mmap', uname_profile={'raw_hex': bytes(390).hex()},
                                 filesystem={'nodes': {}, 'content_loader': lambda *args: b''})
        probe.prepare(app, interp, ['/timer-fixture'])
        probe.syscall_policy = 'threads'
        probe.uipc = GuestUipc()
        probe.uipc.timer_service = 'emulated'
        probe.threads = GuestThreads()
        probe.filesystem.fds[3] = {'device': 'uipc', 'path': '/dev/uipc'}
        probe.mu.mem_map(BASE, 4096)
        for register, value in ((arm.UC_ARM_REG_R0, 3), (arm.UC_ARM_REG_R1, UIPC_CMD_SND_SYNC_DIRECT),
                                (arm.UC_ARM_REG_R2, BASE)):
            probe.mu.reg_write(register, value)
        return probe

    def test_counter_queue_writes_guest_microseconds(self):
        probe = self.make_probe('counter')
        probe.mu.mem_write(BASE, struct.pack('<2I', 0x910042, BASE + 64))
        probe.mu.mem_write(BASE + 64, struct.pack('<8I', 0x20, 0, 0, 0, 0, 0, 0, 0))
        probe.run(instruction_budget=100)
        status, counter = struct.unpack('<iQ', bytes(probe.mu.mem_read(BASE + 64 + 20, 12)))
        self.assertEqual(status, 0)
        self.assertGreater(counter, 0)
        self.assertEqual(counter, probe.uipc.now_us)

    def test_delay_queue_blocks_until_deadline_then_wakes(self):
        probe = self.make_probe('delay')
        probe.mu.mem_write(BASE, struct.pack('<2I', 0x910041, BASE + 64))
        deadline = 5_000_000
        probe.mu.mem_write(BASE + 64, struct.pack('<IIIIIIQ', 0x28, 0, 0, 0, 0, 0, 0)[:24]
                           + struct.pack('<QI', deadline, 1))
        # A second, runnable thread keeps the first one blocked while time is short of the deadline.
        probe.threads.threads[2000] = type(probe.threads.threads[probe.threads.current_tid])(
            tid=2000, name='peer', state='runnable')
        probe.threads.threads[2000].regs = {arm.UC_ARM_REG_PC: probe.mu.reg_read(arm.UC_ARM_REG_PC)}
        probe.uipc.now_us = 0
        probe.instructions = 0
        probe.uipc.timer_wait = deadline
        probe._block_on_timer(probe.mu)
        waiter = probe.threads.threads[1000]
        self.assertEqual(waiter.state, 'blocked_timer')
        self.assertEqual(probe.threads.current_tid, 2000)
        self.assertEqual(probe.threads.wake_due(deadline - 1), [])
        self.assertEqual(waiter.state, 'blocked_timer')
        self.assertEqual(probe.threads.wake_due(deadline), [1000])
        self.assertEqual(waiter.state, 'runnable')

    def test_idle_advances_guest_time_to_deadline(self):
        probe = self.make_probe('idle')
        probe.instructions = 10
        probe.uipc.timer_wait = 7_000_000
        probe._block_on_timer(probe.mu)
        self.assertEqual(probe.instructions, 7_000_000)
        self.assertEqual(probe.threads.threads[1000].state, 'running')
        self.assertEqual(probe.threads.timer_waiters, {})

    def test_idle_scheduler_wakes_timer_waiter_when_others_block(self):
        probe = self.make_probe('sched')
        threads = probe.threads
        threads.save_context(probe.mu)
        import copy
        waiter_tid = threads.current_tid + 1
        threads.threads[waiter_tid] = copy.deepcopy(threads.threads[threads.current_tid])
        threads.threads[waiter_tid].tid = waiter_tid
        threads.threads[threads.current_tid].state = 'blocked_uipc'
        threads.threads[waiter_tid].state = 'blocked_timer'
        threads.timer_waiters[waiter_tid] = 9_000_000
        self.assertEqual(threads.get_next_runnable_tid(), waiter_tid)
        self.assertEqual(threads.clock_floor, 9_000_000)
        self.assertEqual(threads.timer_waiters, {})

    def test_off_by_default_keeps_no_reply(self):
        probe = self.make_probe('off')
        probe.uipc.timer_service = 'off'
        probe.mu.mem_write(BASE, struct.pack('<2I', 0x910042, BASE + 64))
        probe.mu.mem_write(BASE + 64, struct.pack('<8I', 0x20, 0, 0, 0, 0, 0, 0, 0))
        probe.run(instruction_budget=100)
        self.assertEqual(bytes(probe.mu.mem_read(BASE + 64 + 20, 12)), bytes(12))


if __name__ == '__main__':
    unittest.main()
