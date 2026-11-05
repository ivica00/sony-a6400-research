import unittest
import struct
from src.a6400.execution.guest_hdmi import (
    GuestHdmi,
    UnsupportedHdmi,
    HDMI_IOCTL_INIT,
    HDMI_IOCTL_GET_STATUS,
    HDMI_IOCTL_SET_POWER,
    HDMI_IOCTL_SET_TMDS,
    HDMI_IOCTL_SET_RESO,
    HDMI_IOCTL_SET_XVYCC,
    HDMI_IOCTL_SET_SRC_DEV,
    HDMI_IOCTL_SET_AUDIO,
    HDMI_IOCTL_SET_CONTENT,
    HDMI_IOCTL_SET_DIMENSION,
    HDMI_IOCTL_SET_VSIF,
    HDMI_IOCTL_SET_COLORBAR,
    HDMI_IOCTL_SET_FORCE_STOP,
)


class TestGuestHdmi(unittest.TestCase):
    def setUp(self):
        self.dev = GuestHdmi(address_limit=0x5f000000)

    def test_device_numbers(self):
        # Evidenced by devno.ko and reports/a6400_hw_dump.txt
        self.assertEqual(self.dev.major, 248)
        self.assertEqual(self.dev.minor, 25)

    def test_open_close(self):
        owner = self.dev.open(flags=2, caller_pid=1007, caller_tgid=1000)
        self.assertEqual(owner['owner_id'], 1)
        self.assertEqual(owner['flags'], 2)
        self.assertEqual(owner['caller_pid'], 1007)
        self.assertEqual(self.dev.close(1), 0)
        self.assertEqual(self.dev.close(1), -9)

    def test_poll_and_empty_read(self):
        owner = self.dev.open(flags=2)
        # POLLOUT | POLLWRNORM (0x104)
        self.assertEqual(self.dev.poll(owner['owner_id']), 0x104)
        # Empty event queue -> -EAGAIN (-11)
        self.assertEqual(self.dev.read(owner['owner_id'], 0x1000, 32, lambda d: None), -11)

    def test_write_size_guard(self):
        owner = self.dev.open(flags=2)
        mem = {0x1000: b'\xaa' * 32}
        # Writing < 18 bytes returns -EMSGSIZE (-90)
        ret = self.dev.write(owner['owner_id'], 0x1000, 10, lambda a, sz: mem[a][:sz])
        self.assertEqual(ret, -90)
        # Writing >= 18 bytes succeeds
        ret = self.dev.write(owner['owner_id'], 0x1000, 18, lambda a, sz: mem[a][:sz])
        self.assertEqual(ret, 18)

    def test_ioctl_get_monitor_status(self):
        owner = self.dev.open(flags=2)
        written = {}

        def mem_write(addr, data):
            written[addr] = data

        arg_buf = struct.pack('<I', 0x2000)
        mem = {0x1000: arg_buf}

        # Cable disconnected -> 96 bytes of 0
        ret = self.dev.ioctl(
            owner['owner_id'],
            HDMI_IOCTL_GET_STATUS,
            0x1000,
            lambda addr, sz: mem[addr][:sz],
            mem_write
        )
        self.assertEqual(ret, 0)
        self.assertIn(0x2000, written)
        self.assertEqual(len(written[0x2000]), 96)
        self.assertEqual(written[0x2000][0], 0)

        # Cable connected
        self.dev.connected = True
        ret = self.dev.ioctl(
            owner['owner_id'],
            HDMI_IOCTL_GET_STATUS,
            0x1000,
            lambda addr, sz: mem[addr][:sz],
            mem_write
        )
        self.assertEqual(ret, 0)
        self.assertEqual(written[0x2000][0], 1)

    def test_ioctl_set_power_and_tmds(self):
        owner = self.dev.open(flags=2)
        mem = {
            0x1000: struct.pack('<I', 1),
            0x1004: struct.pack('<I', 3),
        }

        ret = self.dev.ioctl(
            owner['owner_id'],
            HDMI_IOCTL_SET_POWER,
            0x1000,
            lambda a, s: mem[a][:s],
            lambda a, d: None
        )
        self.assertEqual(ret, 0)
        self.assertEqual(self.dev.power_state, 1)

        ret = self.dev.ioctl(
            owner['owner_id'],
            HDMI_IOCTL_SET_TMDS,
            0x1004,
            lambda a, s: mem[a][:s],
            lambda a, d: None
        )
        self.assertEqual(ret, 0)
        self.assertEqual(self.dev.tmds_param, 3)

    def test_ioctl_set_src_dev(self):
        owner = self.dev.open(flags=2)
        mem = {0x1000: struct.pack('<I', 5)}
        ret = self.dev.ioctl(
            owner['owner_id'],
            HDMI_IOCTL_SET_SRC_DEV,
            0x1000,
            lambda a, s: mem[a][:s],
            lambda a, d: None
        )
        self.assertEqual(ret, 0)
        self.assertEqual(self.dev.src_dev, 5)

    def test_user_pointer_outside_task_limit(self):
        owner = self.dev.open(flags=2)
        with self.assertRaises(UnsupportedHdmi) as ctx:
            self.dev.ioctl(owner['owner_id'], HDMI_IOCTL_SET_POWER, 0x60000000, lambda a, s: b'', lambda a, d: None)
        self.assertEqual(ctx.exception.details['reason'], 'user_pointer_outside_task_limit')


if __name__ == '__main__':
    unittest.main()
