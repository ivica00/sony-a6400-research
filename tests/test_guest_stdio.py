"""Unit tests for verified standard I/O (stdio) and console contract."""

import struct
import unittest
from src.a6400.execution.guest_stdio import (
    GuestStdio,
    CONSOLE_DEV,
    CONSOLE_INODE,
    CONSOLE_MODE,
    CONSOLE_UID,
    CONSOLE_GID,
    CONSOLE_BLKSIZE,
    STAT64_SIZE,
    TCGETS,
    ENOTTY,
    EBADF,
)


class TestGuestStdio(unittest.TestCase):
    def setUp(self):
        self.memory = {}

    def _reader(self, addr, size):
        data = bytearray()
        for i in range(size):
            data.append(self.memory.get(addr + i, 0))
        return bytes(data)

    def _writer(self, addr, data):
        for i, b in enumerate(data):
            self.memory[addr + i] = b

    def test_pack_stat64_layout(self):
        stdio = GuestStdio(rootfs_dev=0xfc07)
        stat_bytes = stdio.pack_stat64()
        self.assertEqual(len(stat_bytes), STAT64_SIZE)

        st_dev = struct.unpack_from('<Q', stat_bytes, 0)[0]
        st_ino_low = struct.unpack_from('<I', stat_bytes, 12)[0]
        st_mode = struct.unpack_from('<I', stat_bytes, 16)[0]
        st_nlink = struct.unpack_from('<I', stat_bytes, 20)[0]
        st_uid = struct.unpack_from('<I', stat_bytes, 24)[0]
        st_gid = struct.unpack_from('<I', stat_bytes, 28)[0]
        st_rdev = struct.unpack_from('<Q', stat_bytes, 32)[0]
        st_size = struct.unpack_from('<q', stat_bytes, 48)[0]
        st_blksize = struct.unpack_from('<I', stat_bytes, 56)[0]
        st_ino = struct.unpack_from('<Q', stat_bytes, 96)[0]

        self.assertEqual(st_dev, 0xfc07)
        self.assertEqual(st_ino_low, CONSOLE_INODE)
        self.assertEqual(st_mode, CONSOLE_MODE)
        self.assertEqual(st_nlink, 1)
        self.assertEqual(st_uid, CONSOLE_UID)
        self.assertEqual(st_gid, CONSOLE_GID)
        self.assertEqual(st_rdev, CONSOLE_DEV)
        self.assertEqual(st_size, 0)
        self.assertEqual(st_blksize, CONSOLE_BLKSIZE)
        self.assertEqual(st_ino, CONSOLE_INODE)

    def test_fstat64_on_stdio_descriptors(self):
        stdio = GuestStdio()
        buf_ptr = 0x2000

        for fd in (0, 1, 2):
            ret = stdio.handle_fstat64(self._writer, fd, buf_ptr)
            self.assertEqual(ret, 0)
            data = self._reader(buf_ptr, STAT64_SIZE)
            self.assertEqual(len(data), STAT64_SIZE)
            st_rdev = struct.unpack_from('<Q', data, 32)[0]
            self.assertEqual(st_rdev, CONSOLE_DEV)

        # Non-stdio fd fails with -EBADF
        ret_bad = stdio.handle_fstat64(self._writer, 3, buf_ptr)
        self.assertEqual(ret_bad, -EBADF)

    def test_ioctl_tcgets_returns_enotty(self):
        stdio = GuestStdio()
        for fd in (0, 1, 2):
            ret = stdio.handle_ioctl(fd, TCGETS, 0x1000)
            self.assertEqual(ret, (-ENOTTY) & 0xffffffff)

        # Unhandled ioctl returns None
        self.assertIsNone(stdio.handle_ioctl(1, 0x1234, 0x1000))
        # Non-stdio descriptor returns None
        self.assertIsNone(stdio.handle_ioctl(3, TCGETS, 0x1000))

    def test_write_and_writev_logging(self):
        stdio = GuestStdio()
        # Direct write
        written = stdio.handle_write(1, b"Hello camera stdout\n")
        self.assertEqual(written, 20)
        self.assertEqual(stdio.stdout_log, [b"Hello camera stdout\n"])

        # Vector write
        iov_ptr = 0x4000
        str1 = b"Chunk 1: "
        str2 = b"Chunk 2\n"
        self._writer(0x5000, str1)
        self._writer(0x5100, str2)
        self._writer(iov_ptr, struct.pack('<II', 0x5000, len(str1)))
        self._writer(iov_ptr + 8, struct.pack('<II', 0x5100, len(str2)))

        written_v = stdio.handle_writev(self._reader, 2, iov_ptr, 2)
        self.assertEqual(written_v, len(str1) + len(str2))
        self.assertEqual(stdio.stderr_log, [str1 + str2])


if __name__ == '__main__':
    unittest.main()
