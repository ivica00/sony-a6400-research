"""Opt-in 0x1004 reply to the model-info sync callback (queue 0x870136)."""
import struct
import unittest
from src.a6400.execution.guest_uipc import GuestUipc


class ModelInfoReplyTests(unittest.TestCase):
    def setUp(self):
        self.mem = {}
        self.r = lambda a, n: bytes(self.mem.get(a + i, 0) for i in range(n))
        self.w = lambda a, d: self.mem.update({a + i: b for i, b in enumerate(d)})
        self.u = GuestUipc()
        self.u.pool_base = 0x50330000

    def _register(self, queue=0x870136, flags=1):
        self.w(0x1000, struct.pack('<II', queue, 0x2000))
        self.w(0x2000, struct.pack('<IIII', 0x3000, 0x5100a43d, 0, flags))
        self.assertEqual(self.u.handle_reg_msg_queue_cb(self.r, self.w, 0x1000), 0)

    def test_default_is_off(self):
        self._register()
        self.assertEqual(self.u.message_queues.get(0x870136), None)

    def test_reply_is_queued_with_id_and_count(self):
        self.u.model_info_reply = 0
        self._register()
        (msg,) = self.u.message_queues[0x870136]
        self.assertEqual(struct.unpack('<I', self.r(msg, 4))[0], 0x1004)
        self.assertEqual(struct.unpack('<I', self.r(msg + 0x14, 4))[0], 0)

    def test_count_and_once_only(self):
        self.u.model_info_reply = 3
        self._register()
        self.assertFalse(self.u.deliver_model_info_reply(self.w))
        (msg,) = self.u.message_queues[0x870136]
        self.assertEqual(struct.unpack('<I', self.r(msg + 0x14, 4))[0], 3)

    def test_other_queue_or_async_flag_ignored(self):
        self.u.model_info_reply = 1
        self._register(queue=0x924127)
        self._register(flags=0)
        self.assertEqual(self.u.message_queues.get(0x870136), None)

    def test_late_enable_after_registration(self):  # checkpoint-resume case
        self._register()
        self.u.model_info_reply = 1
        self.assertTrue(self.u.deliver_model_info_reply(self.w))


if __name__ == '__main__':
    unittest.main()
