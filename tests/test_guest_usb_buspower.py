import struct
import unittest
from src.a6400.execution.guest_usb_buspower import (
    GuestUsbBusPower,
    UnsupportedUsbBusPower,
    USB_BUSPWR_CMD_SET_SUSPEND_ENABLE,
    USB_BUSPWR_CMD_SET_SUSPEND_DISABLE,
    USB_BUSPWR_CMD_SET_CURRENT_LIMIT_100MA,
    USB_BUSPWR_CMD_SET_CURRENT_LIMIT_500MA,
    USB_BUSPWR_CMD_SET_CHARGING_ENABLE,
    USB_BUSPWR_CMD_SET_CHARGING_DISABLE,
    USB_BUSPWR_CMD_START_NOTIFY_EVENT,
    USB_BUSPWR_CMD_STOP_NOTIFY_EVENT,
    USB_BUSPWR_CMD_GET_CURRENT_PORT_TYPE,
    USB_BUSPWR_CMD_GET_CURRENT_BATT_STATE,
)


class TestGuestUsbBusPower(unittest.TestCase):
    def setUp(self):
        self.dev = GuestUsbBusPower()
        self.memory = bytearray(0x1000)
        self.base_addr = 0x100000

    def mem_read(self, addr, size):
        offset = addr - self.base_addr
        return bytes(self.memory[offset:offset+size])

    def mem_write(self, addr, data):
        offset = addr - self.base_addr
        self.memory[offset:offset+len(data)] = data

    def test_open_close(self):
        owner = self.dev.open(flags=2, caller_pid=1003, caller_tgid=1000)
        self.assertEqual(owner['owner_id'], 1)
        self.assertEqual(owner['flags'], 2)
        self.assertIn(1, self.dev.owners)

        self.dev.close(owner['owner_id'])
        self.assertNotIn(1, self.dev.owners)

    def test_invalid_owner_fails(self):
        with self.assertRaises(UnsupportedUsbBusPower) as ctx:
            self.dev.ioctl(999, USB_BUSPWR_CMD_SET_SUSPEND_ENABLE, 0, self.mem_read, self.mem_write)
        self.assertEqual(ctx.exception.details['reason'], 'usb_buspower_invalid_owner_descriptor')

    def test_suspend_controls(self):
        owner = self.dev.open(flags=2)
        oid = owner['owner_id']

        ret = self.dev.ioctl(oid, USB_BUSPWR_CMD_SET_SUSPEND_ENABLE, 0, self.mem_read, self.mem_write)
        self.assertEqual(ret, 0)
        self.assertTrue(self.dev.suspend_enabled)

        ret = self.dev.ioctl(oid, USB_BUSPWR_CMD_SET_SUSPEND_DISABLE, 0, self.mem_read, self.mem_write)
        self.assertEqual(ret, 0)
        self.assertFalse(self.dev.suspend_enabled)

    def test_current_limit_controls(self):
        owner = self.dev.open(flags=2)
        oid = owner['owner_id']

        ret = self.dev.ioctl(oid, USB_BUSPWR_CMD_SET_CURRENT_LIMIT_100MA, 0, self.mem_read, self.mem_write)
        self.assertEqual(ret, 0)
        self.assertEqual(self.dev.current_limit_ma, 100)

        ret = self.dev.ioctl(oid, USB_BUSPWR_CMD_SET_CURRENT_LIMIT_500MA, 0, self.mem_read, self.mem_write)
        self.assertEqual(ret, 0)
        self.assertEqual(self.dev.current_limit_ma, 500)

    def test_charging_controls(self):
        owner = self.dev.open(flags=2)
        oid = owner['owner_id']

        ret = self.dev.ioctl(oid, USB_BUSPWR_CMD_SET_CHARGING_ENABLE, 0, self.mem_read, self.mem_write)
        self.assertEqual(ret, 0)
        self.assertTrue(self.dev.charging_enabled)

        ret = self.dev.ioctl(oid, USB_BUSPWR_CMD_SET_CHARGING_DISABLE, 0, self.mem_read, self.mem_write)
        self.assertEqual(ret, 0)
        self.assertFalse(self.dev.charging_enabled)

    def test_notify_events(self):
        owner = self.dev.open(flags=2)
        oid = owner['owner_id']

        ret = self.dev.ioctl(oid, USB_BUSPWR_CMD_START_NOTIFY_EVENT, 0, self.mem_read, self.mem_write)
        self.assertEqual(ret, 0)
        self.assertTrue(self.dev.notify_events_enabled)

        ret = self.dev.ioctl(oid, USB_BUSPWR_CMD_STOP_NOTIFY_EVENT, 0, self.mem_read, self.mem_write)
        self.assertEqual(ret, 0)
        self.assertFalse(self.dev.notify_events_enabled)

    def test_get_current_port_type(self):
        owner = self.dev.open(flags=2)
        oid = owner['owner_id']
        ptr = self.base_addr + 0x20

        ret = self.dev.ioctl(oid, USB_BUSPWR_CMD_GET_CURRENT_PORT_TYPE, ptr, self.mem_read, self.mem_write)
        self.assertEqual(ret, 0)
        val = struct.unpack('<I', self.memory[0x20:0x24])[0]
        self.assertEqual(val, 0)

    def test_get_current_batt_state(self):
        owner = self.dev.open(flags=2)
        oid = owner['owner_id']
        ptr = self.base_addr + 0x40

        ret = self.dev.ioctl(oid, USB_BUSPWR_CMD_GET_CURRENT_BATT_STATE, ptr, self.mem_read, self.mem_write)
        self.assertEqual(ret, 0)
        val = struct.unpack('<I', self.memory[0x40:0x44])[0]
        self.assertEqual(val, 0)

    def test_address_limit_guards(self):
        owner = self.dev.open(flags=2)
        oid = owner['owner_id']

        with self.assertRaises(UnsupportedUsbBusPower):
            self.dev.ioctl(oid, USB_BUSPWR_CMD_GET_CURRENT_PORT_TYPE, 0x60000000, self.mem_read, self.mem_write)

        with self.assertRaises(UnsupportedUsbBusPower):
            self.dev.ioctl(oid, USB_BUSPWR_CMD_GET_CURRENT_PORT_TYPE, 0, self.mem_read, self.mem_write)

    def test_out_of_range_command_returns_einval(self):
        owner = self.dev.open(flags=2)
        oid = owner['owner_id']

        ret = self.dev.ioctl(oid, 0x1234, 0, self.mem_read, self.mem_write)
        self.assertEqual(ret, -22)


if __name__ == '__main__':
    unittest.main()
