"""--uipc-timer-service emulated: queue 0x910040 osal timer object ops (create/arm/free bookkeeping)."""
import struct
import unittest

from src.a6400.execution.guest_uipc import GuestUipc, TIMER_OBJECT_QUEUE

ARG = 0x00   # struct { uint32 queue; void *buf; }
MSG = 0x40   # 0x30-byte message
OP = MSG + 0x10
STATUS_NO_OBJECT = 0xFFFFFC00


class TimerObjectServiceTests(unittest.TestCase):
    def make_uipc(self, service='emulated'):
        uipc = GuestUipc()
        uipc.timer_service = service
        self.mem = bytearray(0x200)
        struct.pack_into('<II', self.mem, ARG, TIMER_OBJECT_QUEUE, MSG)
        struct.pack_into('<4I', self.mem, MSG, 0x30, 0, 0, 0)
        return uipc

    def reader(self, addr, size):
        return bytes(self.mem[addr:addr + size])

    def writer(self, addr, data):
        self.mem[addr:addr + len(data)] = data

    def call(self, uipc, op, key=0, a=0, b=0, c=0):
        struct.pack_into('<7I', self.mem, OP, op, 0, key, 0, a, b, c)
        status = uipc.handle_snd_sync_direct(self.reader, ARG, self.writer)
        self.assertEqual(status, 0)
        return struct.unpack_from('<I', self.mem, MSG + 0x14)[0]

    def test_create_returns_key_and_queue(self):
        uipc = self.make_uipc()
        self.assertEqual(self.call(uipc, 0), 0)
        self.assertEqual(struct.unpack_from('<I', self.mem, MSG + 0x18)[0], 1)
        self.assertEqual(struct.unpack_from('<I', self.mem, MSG + 0x20)[0], 0x00EE0001)
        self.assertEqual(uipc.transactions[-1]['type'], 'snd_sync_direct')
        self.assertEqual(uipc.transactions[-1]['timer_object_op'], 0)

    def test_set_callback_then_get_handle(self):
        uipc = self.make_uipc()
        self.call(uipc, 0)
        self.assertEqual(self.call(uipc, 1, key=1, a=0x1234, b=7, c=0x1050), 0)
        self.assertEqual(self.call(uipc, 4, key=1), 0)
        self.assertEqual(struct.unpack_from('<II', self.mem, MSG + 0x20), (0x00EE0001, 0x1050))

    def test_free_then_get_reports_no_object(self):
        uipc = self.make_uipc()
        self.call(uipc, 0)
        self.assertEqual(self.call(uipc, 5, key=1), 0)
        self.assertEqual(self.call(uipc, 4, key=1), STATUS_NO_OBJECT)

    def test_get_unknown_key_reports_no_object(self):
        uipc = self.make_uipc()
        self.assertEqual(self.call(uipc, 4, key=0), STATUS_NO_OBJECT)

    def test_off_service_writes_nothing(self):
        uipc = self.make_uipc(service='off')
        struct.pack_into('<7I', self.mem, OP, 0, 0, 0, 0, 0, 0, 0)
        before = bytes(self.mem)
        uipc.handle_snd_sync_direct(self.reader, ARG, self.writer)
        self.assertEqual(bytes(self.mem), before)
        self.assertFalse(hasattr(uipc, 'timer_objects'))


if __name__ == '__main__':
    unittest.main()
