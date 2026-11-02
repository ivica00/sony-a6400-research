"""Unit tests for GuestGpio: open, bounds validation, and ioctl dispatch."""
import struct
import unittest

from src.a6400.execution.guest_gpio import (
    GuestGpio, UnsupportedGpio, GPIO_CMD_SET_MODE, GPIO_CMD_READ_WRITE,
    GPIOMODE_INPUT, GPIOMODE_OUTPUT_H, GPIOMODE_OUTPUT_L
)


class GuestGpioTests(unittest.TestCase):
    def setUp(self):
        self.gpio = GuestGpio(address_limit=0x5f000000)

    def test_device_numbers(self):
        self.assertEqual((self.gpio.major, self.gpio.minor), (240, 0))

    def test_open_assigns_owner_and_records_transaction(self):
        owner = self.gpio.open(flags=2, caller_pid=1003, caller_tgid=1000)
        self.assertEqual(owner['owner_id'], 1)
        self.assertEqual(owner['flags'], 2)
        self.assertEqual(owner['caller_pid'], 1003)
        self.assertEqual(len(self.gpio.transactions), 1)
        self.assertEqual(self.gpio.transactions[0]['operation'], 'open')

    def test_ioctl_invalid_owner_descriptor(self):
        with self.assertRaises(UnsupportedGpio) as ctx:
            self.gpio.ioctl(owner_id=99, cmd=GPIO_CMD_SET_MODE, arg=0x1000,
                            mem_read=lambda *_: b'', mem_write=lambda *_: None)
        self.assertEqual(ctx.exception.details['reason'], 'gpio_invalid_owner_descriptor')

    def test_ioctl_rejects_pointer_beyond_task_size(self):
        owner = self.gpio.open(flags=2)
        with self.assertRaises(UnsupportedGpio) as ctx:
            self.gpio.ioctl(owner['owner_id'], GPIO_CMD_SET_MODE, 0x60000000,
                            mem_read=lambda *_: b'', mem_write=lambda *_: None)
        self.assertEqual(ctx.exception.details['reason'], 'user_pointer_outside_task_limit')

    def test_ioctl_set_mode_records_pin_mode(self):
        owner = self.gpio.open(flags=2)
        # 16-byte structure: port=1, pin=5, param=0, mode=GPIOMODE_OUTPUT_H (2)
        arg_bytes = struct.pack('<4I', 1, 5, 0, GPIOMODE_OUTPUT_H)
        mem = bytearray(0x100)
        mem[0x20:0x30] = arg_bytes

        ret = self.gpio.ioctl(
            owner['owner_id'], GPIO_CMD_SET_MODE, 0x20,
            mem_read=lambda a, s: bytes(mem[a:a + s]),
            mem_write=lambda a, d: mem.__setitem__(slice(a, a + len(d)), d)
        )
        self.assertEqual(ret, 0)
        self.assertEqual(self.gpio.pins[(1, 5)]['mode'], GPIOMODE_OUTPUT_H)

    def test_ioctl_read_write_records_pin_value(self):
        owner = self.gpio.open(flags=2)
        # port=2, pin=3, param=0, val=1
        arg_bytes = struct.pack('<4I', 2, 3, 0, 1)
        mem = bytearray(0x100)
        mem[0x40:0x50] = arg_bytes

        ret = self.gpio.ioctl(
            owner['owner_id'], GPIO_CMD_READ_WRITE, 0x40,
            mem_read=lambda a, s: bytes(mem[a:a + s]),
            mem_write=lambda a, d: mem.__setitem__(slice(a, a + len(d)), d)
        )
        self.assertEqual(ret, 0)
        self.assertEqual(self.gpio.pins[(2, 3)]['value'], 1)

    def test_ioctl_rejects_unsupported_cmd(self):
        owner = self.gpio.open(flags=2)
        arg_bytes = struct.pack('<4I', 0, 0, 0, 0)
        with self.assertRaises(UnsupportedGpio) as ctx:
            self.gpio.ioctl(owner['owner_id'], 0x12345678, 0x10,
                            mem_read=lambda a, s: arg_bytes, mem_write=lambda *_: None)
        self.assertEqual(ctx.exception.details['reason'], 'unsupported_gpio_ioctl')

    def test_close_removes_owner(self):
        owner = self.gpio.open(flags=2)
        self.gpio.close(owner['owner_id'])
        self.assertNotIn(owner['owner_id'], self.gpio.owners)


if __name__ == '__main__':
    unittest.main()
