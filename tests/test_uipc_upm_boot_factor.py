"""Opt-in reply to the boot-factor request (queue 0x924127, op 0x111)."""
import struct
import unittest
from src.a6400.execution.guest_uipc import GuestUipc, UIPC_CMD_VALLOC_MSG_WAIT


class UpmBootFactorTests(unittest.TestCase):
    def setUp(self):
        self.mem = {}
        self.r = lambda a, n: bytes(self.mem.get(a + i, 0) for i in range(n))
        self.w = lambda a, d: self.mem.update({a + i: b for i, b in enumerate(d)})
        self.u = GuestUipc()
        self.u.pool_base = 0x50330000
        self.u.pool_options_policy = 'kernel-e0301'

    def _request(self):
        q = 0x924127
        self.w(0x1000, struct.pack('<II', q, 0x2000))
        self.w(0x2000, struct.pack('<III', 0x3000, 0x1c, 1))
        self.assertEqual(self.u.handle_ioctl(self.r, self.w, UIPC_CMD_VALLOC_MSG_WAIT, 0x1000), 0)
        msg = struct.unpack('<I', self.r(0x3000, 4))[0]
        self.w(msg, struct.pack('<I', 0x920111))
        self.w(0x2000, struct.pack('<III', msg, 0, 0))
        rc = self.u.handle_ioctl(self.r, self.w, 0x1000, memory_writer=None) \
            if False else self.u.handle_snd_sync_msg(self.r, 0x1000, memory_writer=self.w, tid=1000)
        return rc, struct.unpack('<7I', self.r(msg, 0x1c))

    def test_default_leaves_reply_unmodelled(self):
        rc, words = self._request()
        self.assertEqual((rc, words[1]), (0, 0))

    def test_boot_key_is_written_to_word1(self):
        self.u.upm_boot_key = 2
        rc, words = self._request()
        self.assertEqual((rc, words[0], words[1], words[2:]), (0, 0x920111, 2, (0,) * 5))


if __name__ == '__main__':
    unittest.main()
