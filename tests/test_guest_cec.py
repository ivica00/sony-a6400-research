import struct
import unittest

from src.a6400.execution.guest_cec import (
    CEC_IOCTL_GET_ABORT_FLAG,
    CEC_IOCTL_SET_CONNECT,
    CEC_IOCTL_SET_CYCLE_TIME,
    CEC_IOCTL_SET_KEY_INTERVAL,
    CEC_IOCTL_SET_LGC_ADDR,
    CEC_IOCTL_SET_POWER,
    CEC_IOCTL_SET_REGISTER,
    CEC_IOCTL_SET_REQUEST,
    CEC_IOCTL_SET_SEND,
    CEC_IOCTL_SET_STATUS,
    GuestCec,
    UnsupportedCec,
)


class TestGuestCec(unittest.TestCase):
    def test_device_numbers_and_open_close_poll(self):
        cec = GuestCec()
        self.assertEqual((cec.major, cec.minor), (248, 27))
        handle = cec.open(flags=2, pid=1007, tgid=1000)
        oid = handle['owner_id']
        self.assertEqual(cec.poll(oid), 0x104)
        self.assertEqual(cec.close(oid), 0)

    def test_write_size_validation(self):
        cec = GuestCec()
        oid = cec.open(flags=2, pid=1007, tgid=1000)['owner_id']
        # <= 27 bytes (0x1b) returns -EMSGSIZE (-90 = 0xffffffa6)
        self.assertEqual(cec.write(oid, b'\x00' * 27), 0xffffffa6)
        # >= 28 bytes (0x1c) returns byte count
        self.assertEqual(cec.write(oid, b'\x00' * 28), 28)

    def test_verified_cec_ioctls(self):
        cec = GuestCec()
        oid = cec.open(flags=2, pid=1007, tgid=1000)['owner_id']
        mem = bytearray(512)

        def reader(addr, sz):
            return bytes(mem[addr:addr + sz])

        def writer(addr, data):
            mem[addr:addr + len(data)] = data

        # SET_CONNECT: arg at 0x10 points to int at 0x40
        struct.pack_into('<I', mem, 0x10, 0x40)
        struct.pack_into('<I', mem, 0x40, 1)
        self.assertEqual(cec.ioctl(oid, CEC_IOCTL_SET_CONNECT, 0x10, reader, writer), 0)
        self.assertEqual(cec.connected, 1)

        # SET_POWER, SET_STATUS, SET_REQUEST, SET_CYCLE_TIME, SET_KEY_INTERVAL
        struct.pack_into('<I', mem, 0x20, 2)
        self.assertEqual(cec.ioctl(oid, CEC_IOCTL_SET_POWER, 0x20, reader, writer), 0)
        self.assertEqual(cec.ioctl(oid, CEC_IOCTL_SET_STATUS, 0x20, reader, writer), 0)
        self.assertEqual(cec.ioctl(oid, CEC_IOCTL_SET_REQUEST, 0x20, reader, writer), 0)
        self.assertEqual(cec.ioctl(oid, CEC_IOCTL_SET_CYCLE_TIME, 0x20, reader, writer), 0)
        self.assertEqual(cec.ioctl(oid, CEC_IOCTL_SET_KEY_INTERVAL, 0x20, reader, writer), 0)

        # SET_LGC_ADDR
        mem[0x28] = 0x04
        self.assertEqual(cec.ioctl(oid, CEC_IOCTL_SET_LGC_ADDR, 0x28, reader, writer), 0)
        self.assertEqual(cec.logical_addr, 4)

        # GET_ABORT_FLAG
        cec.abort_flag = 7
        self.assertEqual(cec.ioctl(oid, CEC_IOCTL_GET_ABORT_FLAG, 0x30, reader, writer), 0)
        self.assertEqual(struct.unpack_from('<I', mem, 0x30)[0], 7)

        # SET_SEND (17-byte frame at 0x80) and SET_REGISTER (8-byte struct at 0xa0)
        struct.pack_into('<I', mem, 0x34, 0x80)
        self.assertEqual(cec.ioctl(oid, CEC_IOCTL_SET_SEND, 0x34, reader, writer), 0)
        struct.pack_into('<I', mem, 0x38, 0xa0)
        self.assertEqual(cec.ioctl(oid, CEC_IOCTL_SET_REGISTER, 0x38, reader, writer), 0)

    def test_unknown_ioctl_raises(self):
        cec = GuestCec()
        oid = cec.open(flags=2, pid=1007, tgid=1000)['owner_id']
        with self.assertRaises(UnsupportedCec):
            cec.ioctl(oid, 0xc00443ff, 0x10, lambda a, s: b'\x00' * s, lambda a, d: None)


if __name__ == '__main__':
    unittest.main()
