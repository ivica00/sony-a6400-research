import unittest
from src.a6400.execution.guest_usb_otgcore import (
    GuestUsbOtgCore,
    UnsupportedUsbOtgCore,
    USB_OTGCORE_IOCTL_SET_PORT_DESC,
    USB_OTGCORE_IOCTL_START,
    USB_OTGCORE_IOCTL_STOP,
    USB_OTGCORE_IOCTL_RESET,
    USB_OTGCORE_IOCTL_SET_CONFIG,
    USB_OTGCORE_IOCTL_GET_STATUS,
    USB_OTGCORE_IOCTL_GET_INFO,
)


class TestGuestUsbOtgCore(unittest.TestCase):
    def setUp(self):
        self.dev = GuestUsbOtgCore(address_limit=0x5f000000)

    def test_device_numbers(self):
        self.assertEqual(self.dev.major, 242)
        self.assertEqual(self.dev.minor, 2)

    def test_open_close(self):
        owner = self.dev.open(flags=2, caller_pid=1012, caller_tgid=1000)
        self.assertEqual(owner['owner_id'], 1)
        self.assertEqual(owner['flags'], 2)
        self.assertEqual(owner['caller_pid'], 1012)
        self.assertEqual(self.dev.close(1), 0)
        self.assertEqual(self.dev.close(1), -9)

    def test_ioctl_set_port_desc(self):
        owner = self.dev.open(flags=2)
        payload = b'\x11' * 36
        mem = {0x1000: payload}

        ret = self.dev.ioctl(
            owner['owner_id'],
            USB_OTGCORE_IOCTL_SET_PORT_DESC,
            0x1000,
            lambda addr, sz: mem[addr][:sz],
            lambda addr, data: None
        )
        self.assertEqual(ret, 0)
        self.assertEqual(self.dev.port_desc, payload)

    def test_ioctl_start_stop_reset(self):
        owner = self.dev.open(flags=2)
        self.assertFalse(self.dev.started)

        ret = self.dev.ioctl(owner['owner_id'], USB_OTGCORE_IOCTL_START, 0, lambda a, s: b'', lambda a, d: None)
        self.assertEqual(ret, 0)
        self.assertTrue(self.dev.started)

        ret = self.dev.ioctl(owner['owner_id'], USB_OTGCORE_IOCTL_STOP, 0, lambda a, s: b'', lambda a, d: None)
        self.assertEqual(ret, 0)
        self.assertFalse(self.dev.started)

        ret = self.dev.ioctl(owner['owner_id'], USB_OTGCORE_IOCTL_RESET, 0, lambda a, s: b'', lambda a, d: None)
        self.assertEqual(ret, 0)
        self.assertFalse(self.dev.started)

    def test_ioctl_set_config(self):
        owner = self.dev.open(flags=2)
        payload = b'\x22' * 64
        mem = {0x2000: payload}

        ret = self.dev.ioctl(
            owner['owner_id'],
            USB_OTGCORE_IOCTL_SET_CONFIG,
            0x2000,
            lambda addr, sz: mem[addr][:sz],
            lambda addr, data: None
        )
        self.assertEqual(ret, 0)
        self.assertEqual(self.dev.config, payload)

    def test_ioctl_get_status_and_info(self):
        owner = self.dev.open(flags=2)
        mem = {}

        def write_mem(addr, data):
            mem[addr] = data

        ret = self.dev.ioctl(
            owner['owner_id'],
            USB_OTGCORE_IOCTL_GET_STATUS,
            0x3000,
            lambda a, s: b'',
            write_mem
        )
        self.assertEqual(ret, 0)
        self.assertEqual(mem[0x3000], b'\x00')

        ret = self.dev.ioctl(
            owner['owner_id'],
            USB_OTGCORE_IOCTL_GET_INFO,
            0x4000,
            lambda a, s: b'',
            write_mem
        )
        self.assertEqual(ret, 0)
        self.assertEqual(mem[0x4000], b'\x00' * 8)

    def test_user_pointer_outside_task_limit(self):
        owner = self.dev.open(flags=2)
        with self.assertRaises(UnsupportedUsbOtgCore) as ctx:
            self.dev.ioctl(
                owner['owner_id'],
                USB_OTGCORE_IOCTL_SET_PORT_DESC,
                0x60000000,  # kernel address
                lambda a, s: b'',
                lambda a, d: None
            )
        self.assertEqual(ctx.exception.details['reason'], 'user_pointer_outside_task_limit')

    def test_invalid_owner_and_unknown_ioctl(self):
        with self.assertRaises(UnsupportedUsbOtgCore):
            self.dev.ioctl(999, USB_OTGCORE_IOCTL_START, 0, lambda a, s: b'', lambda a, d: None)

        owner = self.dev.open(flags=2)
        ret = self.dev.ioctl(owner['owner_id'], 0xdeadbeef, 0, lambda a, s: b'', lambda a, d: None)
        self.assertEqual(ret, -22)


if __name__ == '__main__':
    unittest.main()
