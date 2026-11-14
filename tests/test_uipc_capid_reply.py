"""Opt-in reply to the capture-ID-table request (queue 0x4015e)."""
import struct
import unittest
from src.a6400.execution.guest_uipc import GuestUipc


class CapidReplyTests(unittest.TestCase):
    def setUp(self):
        self.mem = {}
        self.r = lambda a, n: bytes(self.mem.get(a + i, 0) for i in range(n))
        self.w = lambda a, d: self.mem.update({a + i: b for i, b in enumerate(d)})
        self.u = GuestUipc()
        self.u.pool_base = 0x50330000

    def _send(self, cmd=0x1000, reply_queue=0x306011):
        msg = self.u.allocate_message(0x18, self.w)
        self.w(msg - 4, struct.pack('<I', reply_queue))
        self.w(msg, struct.pack('<II', 0, cmd) + bytes(0x10))
        self.w(0x1000, struct.pack('<II', 0x4015e, msg))
        self.assertEqual(self.u.handle_snd_msg(self.r, 0x1000, memory_writer=self.w), 0)
        return msg

    def test_default_is_off(self):
        msg = self._send()
        self.assertEqual(self.u.message_queues.get(0x306011), None)
        self.assertEqual(self.u.message_queues[0x4015e], [msg])

    def test_reply_goes_to_private_queue(self):
        self.u.capid_table_reply = 0x1f000000
        self._send()
        (rep,) = self.u.message_queues[0x306011]
        self.assertEqual(struct.unpack('<IIII', self.r(rep, 16)), (1, 0x1000, 0, 0x1f000000))
        self.assertEqual(self.u.message_queues.get(0x4015e), None)

    def test_cmd_1001_same_reply(self):
        self.u.capid_table_reply = 0x1f000000
        self._send(cmd=0x1001)
        (rep,) = self.u.message_queues[0x306011]
        self.assertEqual(struct.unpack('<II', self.r(rep + 4, 8)), (0x1000, 0))

    def test_other_command_stays_queued(self):
        self.u.capid_table_reply = 0x1f000000
        self._send(cmd=0x2000)
        self.assertEqual(self.u.message_queues.get(0x306011), None)
        self.assertEqual(len(self.u.message_queues[0x4015e]), 1)


if __name__ == '__main__':
    unittest.main()
