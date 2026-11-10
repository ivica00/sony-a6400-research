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
    USB_BUSPWR_CMD_SET_PORT_STATE,
    USB_BUSPWR_REPLY_POLICY_LEGACY,
    USB_BUSPWR_REPLY_POLICY_VERIFIED,
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


class TestGuestUsbBusPowerVerifiedPolicy(unittest.TestCase):
    """Opt-in 'verified-connect' policy: authentic values or explicit boundary."""

    def setUp(self):
        self.dev = GuestUsbBusPower(reply_policy=USB_BUSPWR_REPLY_POLICY_VERIFIED)
        self.memory = bytearray(0x1000)
        self.base_addr = 0x100000

    def mem_read(self, addr, size):
        offset = addr - self.base_addr
        return bytes(self.memory[offset:offset+size])

    def mem_write(self, addr, data):
        offset = addr - self.base_addr
        self.memory[offset:offset+len(data)] = data

    def test_default_policy_is_legacy(self):
        default = GuestUsbBusPower()
        self.assertEqual(default.reply_policy, USB_BUSPWR_REPLY_POLICY_LEGACY)
        self.assertIsNone(default.port_type_reply)
        self.assertIsNone(default.batt_state_reply)

    def test_unknown_policy_rejected(self):
        with self.assertRaises(ValueError):
            GuestUsbBusPower(reply_policy='invented')

    def test_verified_suspend_and_charging_controls(self):
        owner = self.dev.open(flags=2)
        oid = owner['owner_id']

        self.assertEqual(self.dev.ioctl(oid, 0xf200, 0, self.mem_read, self.mem_write), 0)
        self.assertTrue(self.dev.suspend_enabled)
        self.assertEqual(self.dev.ioctl(oid, 0xf201, 0, self.mem_read, self.mem_write), 0)
        self.assertFalse(self.dev.suspend_enabled)
        self.assertEqual(self.dev.ioctl(oid, 0xf204, 0, self.mem_read, self.mem_write), 0)
        self.assertTrue(self.dev.charging_enabled)
        self.assertEqual(self.dev.ioctl(oid, 0xf205, 0, self.mem_read, self.mem_write), 0)
        self.assertFalse(self.dev.charging_enabled)
        self.assertEqual(self.dev.ioctl(oid, 0xf202, 0, self.mem_read, self.mem_write), 0)
        self.assertEqual(self.dev.current_limit_ma, 100)
        self.assertEqual(self.dev.ioctl(oid, 0xf203, 0, self.mem_read, self.mem_write), 0)
        self.assertEqual(self.dev.current_limit_ma, 500)

    def test_verified_notify_and_set_port_state_return_zero(self):
        owner = self.dev.open(flags=2)
        oid = owner['owner_id']

        self.assertEqual(self.dev.ioctl(oid, USB_BUSPWR_CMD_START_NOTIFY_EVENT, 0, self.mem_read, self.mem_write), 0)
        self.assertTrue(self.dev.notify_events_enabled)
        self.assertEqual(self.dev.ioctl(oid, USB_BUSPWR_CMD_STOP_NOTIFY_EVENT, 0, self.mem_read, self.mem_write), 0)
        self.assertFalse(self.dev.notify_events_enabled)
        # usb_buspwr.ko 0x14e8: usb_buspw_ic_initialize(); return 0 (arg unused).
        self.assertEqual(self.dev.ioctl(oid, USB_BUSPWR_CMD_SET_PORT_STATE, 0x11800000,
                                        self.mem_read, self.mem_write), 0)

    def test_verified_mapped_table_commands_return_zero(self):
        owner = self.dev.open(flags=2)
        oid = owner['owner_id']
        for cmd in (0xf208, 0xf20b, 0xf21e, 0xf21f, 0xf220):
            self.assertEqual(self.dev.ioctl(oid, cmd, 0, self.mem_read, self.mem_write), 0, hex(cmd))

    def test_verified_unmapped_table_commands_return_einval(self):
        owner = self.dev.open(flags=2)
        oid = owner['owner_id']
        for cmd in (0xf20d, 0xf20e, 0xf20f, 0xf214, 0xf215, 0xf21d):
            self.assertEqual(self.dev.ioctl(oid, cmd, 0, self.mem_read, self.mem_write), -22, hex(cmd))

    def test_verified_out_of_range_returns_einval(self):
        owner = self.dev.open(flags=2)
        oid = owner['owner_id']
        self.assertEqual(self.dev.ioctl(oid, 0x1234, 0, self.mem_read, self.mem_write), -22)
        self.assertEqual(self.dev.ioctl(oid, 0xf221, 0, self.mem_read, self.mem_write), -22)

    def test_verified_port_type_query_is_explicit_boundary(self):
        owner = self.dev.open(flags=2)
        oid = owner['owner_id']
        ptr = self.base_addr + 0x20

        with self.assertRaises(UnsupportedUsbBusPower) as ctx:
            self.dev.ioctl(oid, USB_BUSPWR_CMD_GET_CURRENT_PORT_TYPE, ptr,
                           self.mem_read, self.mem_write)
        details = ctx.exception.details
        self.assertEqual(details['reason'], 'usb_buspower_port_type_reply_not_derivable')
        self.assertEqual(details['cmd'], USB_BUSPWR_CMD_GET_CURRENT_PORT_TYPE)
        self.assertEqual(details['requested_size'], 4)
        # The boundary must not have written a fabricated value.
        self.assertEqual(bytes(self.memory[0x20:0x24]), b'\x00\x00\x00\x00')
        self.assertFalse(any(row.get('name') == 'GET_CURRENT_PORT_TYPE'
                             for row in self.dev.transactions if row.get('operation') == 'ioctl'))

    def test_verified_batt_state_query_is_explicit_boundary(self):
        owner = self.dev.open(flags=2)
        oid = owner['owner_id']
        with self.assertRaises(UnsupportedUsbBusPower) as ctx:
            self.dev.ioctl(oid, USB_BUSPWR_CMD_GET_CURRENT_BATT_STATE, self.base_addr + 0x40,
                           self.mem_read, self.mem_write)
        self.assertEqual(ctx.exception.details['reason'],
                         'usb_buspower_batt_state_reply_not_derivable')
        self.assertEqual(bytes(self.memory[0x40:0x44]), b'\x00\x00\x00\x00')

    def test_verified_port_type_evidence_override(self):
        dev = GuestUsbBusPower(reply_policy=USB_BUSPWR_REPLY_POLICY_VERIFIED,
                               port_type_reply=1)
        owner = dev.open(flags=2)
        ptr = self.base_addr + 0x20
        ret = dev.ioctl(owner['owner_id'], USB_BUSPWR_CMD_GET_CURRENT_PORT_TYPE, ptr,
                        self.mem_read, self.mem_write)
        self.assertEqual(ret, 0)
        self.assertEqual(struct.unpack('<I', bytes(self.memory[0x20:0x24]))[0], 1)
        self.assertEqual(dev.transactions[-1]['source'], 'explicit-evidence-override')

    def test_verified_address_limits_still_enforced(self):
        owner = self.dev.open(flags=2)
        oid = owner['owner_id']
        with self.assertRaises(UnsupportedUsbBusPower) as ctx:
            self.dev.ioctl(oid, USB_BUSPWR_CMD_GET_CURRENT_PORT_TYPE, 0x60000000,
                           self.mem_read, self.mem_write)
        self.assertEqual(ctx.exception.details['reason'], 'user_pointer_outside_task_limit')
        with self.assertRaises(UnsupportedUsbBusPower):
            self.dev.ioctl(oid, USB_BUSPWR_CMD_GET_CURRENT_PORT_TYPE, 0,
                           self.mem_read, self.mem_write)

    def test_legacy_policy_unchanged_zero_stubs(self):
        legacy = GuestUsbBusPower()
        owner = legacy.open(flags=2)
        ptr = self.base_addr + 0x20
        self.assertEqual(legacy.ioctl(owner['owner_id'], USB_BUSPWR_CMD_GET_CURRENT_PORT_TYPE,
                                      ptr, self.mem_read, self.mem_write), 0)
        self.assertEqual(struct.unpack('<I', bytes(self.memory[0x20:0x24]))[0], 0)
        # Legacy keeps the earlier fabricated-success reply for 0xf20d.
        self.assertEqual(legacy.ioctl(owner['owner_id'], 0xf20d, 0,
                                      self.mem_read, self.mem_write), 0)


if __name__ == '__main__':
    unittest.main()
