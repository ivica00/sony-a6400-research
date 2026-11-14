"""--uipc-rcv-timeout modeled: rcv_msg_tmo deadlines and the threads timer/uipc wake hooks."""
import struct
import unittest

from src.a6400.execution.guest_threads import GuestThreads
from src.a6400.execution.guest_uipc import GuestUipc

ARG_PTR = 0x1000
QUEUE = 0x0094016A
TID = 2000


class FakeMemory:
    def __init__(self, queue=QUEUE, timeout=5, p_out_msg=0, out_msg=0):
        self.data = bytearray(0x2000)
        self.data[ARG_PTR:ARG_PTR + 16] = struct.pack('<IIII', queue, p_out_msg, out_msg, timeout)
        self.writes = []

    def read(self, addr, size):
        return bytes(self.data[addr:addr + size])

    def write(self, addr, payload):
        self.writes.append((addr, payload))
        self.data[addr:addr + len(payload)] = payload


class RcvTimeoutTests(unittest.TestCase):
    def make_uipc(self, policy='modeled'):
        uipc = GuestUipc()
        if policy is not None:
            uipc.rcv_timeout_policy = policy
        return uipc

    def call(self, uipc, mem, now, tid=TID):
        uipc.clock_us = now
        uipc.rcv_tid = tid  # set by handle_ioctl in production; no tid kwarg
        return uipc.handle_rcv_msg_tmo(mem.read, mem.write, ARG_PTR)

    def test_first_call_arms_deadline_and_blocks(self):
        uipc, mem = self.make_uipc(), FakeMemory(timeout=5)
        self.assertIsNone(self.call(uipc, mem, now=1000))
        self.assertEqual(uipc.rcv_deadlines[TID], 1000 + 5 * 1000)
        self.assertEqual(uipc.rcv_wait, 6000)

    def test_call_before_deadline_still_blocks_without_rearming(self):
        uipc, mem = self.make_uipc(), FakeMemory(timeout=5)
        self.call(uipc, mem, now=1000)
        self.assertIsNone(self.call(uipc, mem, now=5999))
        self.assertEqual(uipc.rcv_deadlines[TID], 6000)

    def test_call_at_deadline_returns_timeout_and_drops_deadline(self):
        uipc, mem = self.make_uipc(), FakeMemory(timeout=5)
        self.call(uipc, mem, now=1000)
        self.assertEqual(self.call(uipc, mem, now=6000), -1022)
        self.assertNotIn(TID, uipc.rcv_deadlines)
        self.assertEqual(uipc.transactions[-1]['status'], 'timeout_expired')

    def test_queued_message_returns_zero_and_drops_deadline(self):
        uipc, mem = self.make_uipc(), FakeMemory(timeout=5, p_out_msg=0x1100)
        self.call(uipc, mem, now=1000)
        uipc.message_queues[QUEUE] = [0xABCD]
        self.assertEqual(self.call(uipc, mem, now=2000), 0)
        self.assertNotIn(TID, uipc.rcv_deadlines)
        self.assertEqual(mem.writes, [(0x1100, struct.pack('<I', 0xABCD))])

    def test_policy_unset_keeps_baseline_timeout_without_deadline(self):
        # Baseline fall-through: a positive timeout on an empty queue returns -1022 at once.
        uipc, mem = self.make_uipc(policy=None), FakeMemory(timeout=5)
        self.assertEqual(self.call(uipc, mem, now=1000), -1022)
        self.assertNotIn(TID, getattr(uipc, 'rcv_deadlines', {}))
        self.assertIsNone(getattr(uipc, 'rcv_wait', None))


class ThreadsTimerWakeTests(unittest.TestCase):
    QUEUE = 0x0094016A
    DEADLINE = 6000

    def make_threads(self):
        threads = GuestThreads(initial_tid=1000)
        threads.threads[TID] = type(threads.threads[1000])(tid=TID, name='peer', state='runnable')
        return threads

    def test_wait_with_deadline_registers_timer_waiter(self):
        threads = self.make_threads()
        threads.handle_uipc_wait(self.QUEUE, 0x2000, deadline=self.DEADLINE)
        self.assertEqual(threads.timer_waiters[1000], self.DEADLINE)
        self.assertIn(1000, threads.uipc_waiters[self.QUEUE])
        self.assertEqual(threads.threads[1000].state, 'blocked_uipc')

    def test_wake_due_at_deadline_makes_thread_runnable(self):
        threads = self.make_threads()
        threads.handle_uipc_wait(self.QUEUE, 0x2000, deadline=self.DEADLINE)
        self.assertEqual(threads.wake_due(self.DEADLINE - 1), [])
        self.assertEqual(threads.threads[1000].state, 'blocked_uipc')
        self.assertEqual(threads.wake_due(self.DEADLINE), [1000])
        self.assertEqual(threads.threads[1000].state, 'runnable')
        self.assertNotIn(1000, threads.uipc_waiters.get(self.QUEUE, []))
        self.assertNotIn(1000, threads.timer_waiters)

    def test_uipc_wake_removes_timer_waiter(self):
        threads = self.make_threads()
        threads.handle_uipc_wait(self.QUEUE, 0x2000, deadline=self.DEADLINE)
        self.assertEqual(threads.handle_uipc_wake(self.QUEUE), [1000])
        self.assertNotIn(1000, threads.timer_waiters)
        self.assertEqual(threads.wake_due(self.DEADLINE), [])

    def test_timer_object_pseudo_waiter_fires_hook_at_deadline(self):
        threads = self.make_threads()
        fired = []
        threads.timer_fire = fired.append
        threads.timer_waiters[-7] = self.DEADLINE
        threads.wake_due(self.DEADLINE - 1)
        self.assertEqual(fired, [])
        threads.wake_due(self.DEADLINE)
        self.assertEqual(fired, [7])
        self.assertNotIn(-7, threads.timer_waiters)


if __name__ == '__main__':
    unittest.main()
