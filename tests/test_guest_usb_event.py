import struct
import unittest
from src.a6400.execution.guest_usb_event import (
    GuestUsbEvent,
    UnsupportedUsbEvent,
    USB_EVENT_IOCTL_ENABLE,
    USB_EVENT_IOCTL_DISABLE,
    USB_EVENT_IOCTL_STOP,
)


class TestGuestUsbEvent(unittest.TestCase):
    def setUp(self):
        self.dev = GuestUsbEvent()
        self.memory = bytearray(0x1000)
        self.base_addr = 0x100000

    def mem_read(self, addr, size):
        offset = addr - self.base_addr
        return bytes(self.memory[offset:offset+size])

    def mem_write(self, addr, data):
        offset = addr - self.base_addr
        self.memory[offset:offset+len(data)] = data

    def test_open_close(self):
        self.assertEqual(self.dev.major, 242)
        self.assertEqual(self.dev.minor, 0)

        owner = self.dev.open(flags=2, caller_pid=1012, caller_tgid=1000)
        self.assertEqual(owner['owner_id'], 1)
        self.assertEqual(owner['flags'], 2)
        self.assertIn(1, self.dev.owners)

        self.dev.close(owner['owner_id'])
        self.assertNotIn(1, self.dev.owners)

    def test_invalid_owner_fails(self):
        with self.assertRaises(UnsupportedUsbEvent) as ctx:
            self.dev.ioctl(999, USB_EVENT_IOCTL_ENABLE, 0, self.mem_read, self.mem_write)
        self.assertEqual(ctx.exception.details['reason'], 'usb_event_invalid_owner_descriptor')

    def test_ioctl_enable_disable(self):
        owner = self.dev.open(flags=2)
        oid = owner['owner_id']

        # Write event ID 42 to user memory
        struct.pack_into('<I', self.memory, 0, 42)
        ret = self.dev.ioctl(oid, USB_EVENT_IOCTL_ENABLE, self.base_addr, self.mem_read, self.mem_write)
        self.assertEqual(ret, 0)
        self.assertIn(42, self.dev.enabled_events)

        # Disable event ID 42
        ret = self.dev.ioctl(oid, USB_EVENT_IOCTL_DISABLE, self.base_addr, self.mem_read, self.mem_write)
        self.assertEqual(ret, 0)
        self.assertNotIn(42, self.dev.enabled_events)

    def test_ioctl_stop(self):
        owner = self.dev.open(flags=2)
        oid = owner['owner_id']

        self.assertFalse(self.dev.stopped)
        ret = self.dev.ioctl(oid, USB_EVENT_IOCTL_STOP, 0, self.mem_read, self.mem_write)
        self.assertEqual(ret, 0)
        self.assertTrue(self.dev.stopped)

    def test_invalid_cmd_returns_einval(self):
        owner = self.dev.open(flags=2)
        oid = owner['owner_id']
        ret = self.dev.ioctl(oid, 0xdeadbeef, 0, self.mem_read, self.mem_write)
        self.assertEqual(ret, -22)

    def test_read_behavior(self):
        owner = self.dev.open(flags=2)
        oid = owner['owner_id']

        # When empty and not stopped: returns None (indicating blocking wait)
        res = self.dev.read(oid, 128, lambda data: None)
        self.assertIsNone(res)

        # When event pending: writes data and returns count
        test_event = b'\x01\x00\x00\x00\x04\x00\x00\x00'
        self.dev.pending_events.append(test_event)
        written = bytearray()
        res = self.dev.read(oid, 128, lambda data: written.extend(data))
        self.assertEqual(res, len(test_event))
        self.assertEqual(bytes(written), test_event)

        # When stopped: returns 0 (EOF)
        self.dev.stopped = True
        res = self.dev.read(oid, 128, lambda data: None)
        self.assertEqual(res, 0)

    def test_user_pointer_outside_task_limit(self):
        owner = self.dev.open(flags=2)
        oid = owner['owner_id']

        with self.assertRaises(UnsupportedUsbEvent) as ctx:
            self.dev.ioctl(oid, USB_EVENT_IOCTL_ENABLE, 0x5f000000, self.mem_read, self.mem_write)
        self.assertEqual(ctx.exception.details['reason'], 'user_pointer_outside_task_limit')


if __name__ == '__main__':
    unittest.main()
