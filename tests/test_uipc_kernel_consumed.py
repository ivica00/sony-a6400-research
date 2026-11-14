"""snd_msg to a queue served by a kernel module callback consumes and frees the message."""
import struct
import unittest
from src.a6400.execution.guest_uipc import GuestUipc, UIPC_CMD_SND_MSG, UIPC_CMD_VALLOC_MSG_WAIT


class KernelConsumedQueueTests(unittest.TestCase):
    def setUp(self):
        self.mem = {}
        self.r = lambda a, n: bytes(self.mem.get(a + i, 0) for i in range(n))
        self.w = lambda a, d: self.mem.update({a + i: b for i, b in enumerate(d)})
        self.u = GuestUipc()
        self.u.pool_base = 0x50330000

    def _send(self, queue):
        self.w(0x1000, struct.pack('<II', queue, 0x2000))
        self.w(0x2000, struct.pack('<III', 0x3000, 52, 1))
        self.assertEqual(self.u.handle_ioctl(self.r, self.w, UIPC_CMD_VALLOC_MSG_WAIT, 0x1000), 0)
        msg = struct.unpack('<I', self.r(0x3000, 4))[0]
        self.w(0x1000, struct.pack('<II', queue, msg))
        self.assertEqual(self.u.handle_ioctl(self.r, self.w, UIPC_CMD_SND_MSG, 0x1000), 0)
        return msg

    def test_ulogio_queue_does_not_grow_and_frees_pool(self):
        for _ in range(50):
            self._send(0x8f013a)
        self.assertEqual(self.u.message_queues.get(0x8f013a, []), [])
        self.assertEqual(self.u.allocated_msgs, {})

    def test_other_queue_still_queues(self):
        msg = self._send(0x123456)
        self.assertEqual(self.u.message_queues[0x123456], [msg])
        self.assertIn(msg, self.u.allocated_msgs)


if __name__ == '__main__':
    unittest.main()
