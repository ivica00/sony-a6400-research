"""Error/lifetime checks for the bounded E0300 callback transport."""
import struct
import unittest

from src.a6400.execution.guest_uipc import GuestUipc, UnsupportedUipc, UIPC_CMD_WAIT_CB


class CallbackDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.data = bytearray(b'\xcc' * 8192)
        self.u = GuestUipc()
        self.u.pool_options_policy = 'kernel-e0300'
        self.u.pool_base = 0x1000
        self.write(0x100, struct.pack('<II', 0, 0x200))
        self.write(0x200, struct.pack('<4I', 0, 0, 0, 2))

    def read(self, address, size):
        return bytes(self.data[address:address + size])

    def write(self, address, value):
        self.data[address:address + len(value)] = value

    def test_options_preserve_unspecified_bytes_and_legacy(self):
        self.u.pool_options_policy = 'legacy-empty'
        before = bytes(self.data)
        self.u.initialize_pool_options(self.write)
        self.assertEqual(bytes(self.data), before)
        self.u.pool_options_policy = 'kernel-e0300'
        self.u.initialize_pool_options(self.write)
        self.assertEqual(self.read(0x1010, 4), struct.pack('<I', 4))
        self.assertEqual(self.read(0x1014, 4), b'\xcc\x01\x00\xcc')
        self.assertEqual(self.read(0x1018, 8), b'\xcc' * 8)

    def test_geometry_rejects_before_writing(self):
        self.u.total_pool_size = 4096
        before = bytes(self.data)
        with self.assertRaises(UnsupportedUipc):
            self.u.initialize_pool_options(self.write)
        self.assertEqual(bytes(self.data), before)

    def test_empty_wait_delivery_and_completion_boundary(self):
        before = self.read(0x200, 16)
        self.assertIsNone(self.u.handle_ioctl(self.read, self.write, UIPC_CMD_WAIT_CB, 0x100, tid=1001))
        self.assertEqual(self.read(0x200, 16), before)
        self.assertEqual(self.u.handle_wait_cb(self.read, self.write, 0x100, tid=1002), -22)
        self.assertEqual(self.read(0x200, 16), before)
        self.u.callbacks[4] = dict(queue=0x12002da, callback=0x1235, user_data=0x5678, flags=0)
        self.u.enqueue_message(0x12002da, 0x110c)
        self.assertEqual(self.u.handle_ioctl(self.read, self.write, UIPC_CMD_WAIT_CB, 0x100, tid=1001), 0)
        self.assertEqual(struct.unpack('<4I', self.read(0x200, 16)), (0x1235, 0x5678, 0x110c, 2))
        with self.assertRaisesRegex(UnsupportedUipc, 'completion_not_implemented'):
            self.u.handle_ioctl(self.read, self.write, UIPC_CMD_WAIT_CB, 0x100, tid=1001)

    def test_sync_and_failed_copy_do_not_consume(self):
        cb = dict(queue=1, callback=0x1235, user_data=0, flags=1)
        self.u.callbacks[4] = cb
        self.u.enqueue_message(1, 0x110c)
        with self.assertRaisesRegex(UnsupportedUipc, 'sync_callback'):
            self.u.handle_wait_cb(self.read, self.write, 0x100, tid=1001)
        cb['flags'] = 0
        def fail(address, value):
            raise ValueError('inaccessible output')
        with self.assertRaises(ValueError):
            self.u.handle_wait_cb(self.read, fail, 0x100, tid=1001)
        self.assertEqual(self.u.message_queues[1], [0x110c])
