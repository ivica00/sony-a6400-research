"""Kernel-side UIPC semantics: -1020 for sync sends without a callback, -1023 pool exhaustion,
logging-module listener threads (0x8f013a x2, 0x8f0139 x1) and the 0x8012 state reply."""
import struct
import unittest
from src.a6400.execution.guest_uipc import (GuestUipc, UIPC_CMD_SND_MSG, UIPC_CMD_SND_SYNC_MSG,
                                            UIPC_CMD_VALLOC_MSG_WAIT)


class KernelQueueTests(unittest.TestCase):
    def setUp(self):
        self.mem = {}
        self.r = lambda a, n: bytes(self.mem.get(a + i, 0) for i in range(n))
        self.w = lambda a, d: self.mem.update({a + i: b for i, b in enumerate(d)})
        self.u = GuestUipc()
        self.u.pool_base = 0x50330000
        self.u.pool_options_policy = 'kernel-e0301'

    def _alloc(self, size=0x48, op=0):
        self.w(0x1000, struct.pack('<II', 0x4001, 0x2000))
        self.w(0x2000, struct.pack('<III', 0x3000, size, 1))
        rc = self.u.handle_ioctl(self.r, self.w, UIPC_CMD_VALLOC_MSG_WAIT, 0x1000)
        self.rc = rc
        if rc:
            return None
        msg = struct.unpack('<I', self.r(0x3000, 4))[0]
        self.w(msg, struct.pack('<H', op))
        return msg

    def _snd(self, queue, msg):
        self.w(0x1000, struct.pack('<II', queue, msg))
        return self.u.handle_ioctl(self.r, self.w, UIPC_CMD_SND_MSG, 0x1000)

    def _sync(self, queue, msg):
        self.w(0x1000, struct.pack('<II', queue, 0x2000))
        self.w(0x2000, struct.pack('<III', msg, 0, 0))
        return self.u.handle_ioctl(self.r, self.w, UIPC_CMD_SND_SYNC_MSG, 0x1000)

    def test_sync_without_callback_is_1020_only_under_kernel_policy(self):
        msg = self._alloc()
        self.assertEqual(self._sync(0x123456, msg), -1020)
        self.assertEqual(self._sync(0x00a30281, msg), 0)  # kernel-served queue
        self.u.callbacks[0x1000] = {'queue': 0x123456, 'callback': 1, 'user_data': 0, 'flags': 0}
        self.assertEqual(self._sync(0x123456, msg), 0)
        self.u.pool_options_policy = 'legacy-empty'
        self.assertEqual(self._sync(0x777777, msg), 0)

    def test_pool_exhaustion_code(self):
        self.u.pool_base = 0x50330000
        while self._alloc(0x1000) is not None:
            pass
        self.assertEqual(self.rc, -1023)
        self.u.pool_options_policy = 'legacy-empty'
        self.assertIsNone(self._alloc(0x1000))
        self.assertEqual(self.rc, -12)

    def test_ulogio_state_reply_follows_userspace_started(self):
        probe = self._alloc(op=0x8012)
        self.assertEqual(self._sync(0x8f013a, probe), 0)
        self.assertEqual(struct.unpack('<II', self.r(probe + 0x40, 8)), (0, 0))
        self.assertEqual(self._snd(0x8f0139, self._alloc(2, 0x8001)), 0)
        self.assertEqual(self._sync(0x8f013a, probe), 0)
        self.assertEqual(struct.unpack('<II', self.r(probe + 0x40, 8)), (1, 0))

    def test_listener_exits_after_userspace_started(self):
        self._snd(0x8f0139, self._alloc(2, 1))
        self.assertEqual(self.u.message_queues.get(0x8f0139, []), [])
        self._snd(0x8f0139, self._alloc(2, 0x8001))  # the only 0x8f0139 listener exits
        late = self._alloc(2, 1)
        self._snd(0x8f0139, late)
        self.assertEqual(self.u.message_queues[0x8f0139], [late])
        for _ in range(3):  # 0x8f013a keeps two listeners, one 0x8001 does not stop it
            self._snd(0x8f013a, self._alloc(2, 2))
        self._snd(0x8f013a, self._alloc(2, 0x8001))
        self._snd(0x8f013a, self._alloc(2, 2))
        self.assertEqual(self.u.message_queues.get(0x8f013a, []), [])
        self.assertEqual(self.u.queue_stats['0x8f013a/snd_msg/op0x8001'], 1)


if __name__ == '__main__':
    unittest.main()
