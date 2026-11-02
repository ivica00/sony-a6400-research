"""Verified standard I/O (stdio) and console contract for guest Linux ARM processes.

Provides metadata and descriptor operations for standard descriptors 0 (stdin),
1 (stdout), and 2 (stderr) backed by verified /dev/console device nodes.
"""

import struct
from typing import Dict, List, Optional, Tuple

# Linux ARM ioctl constants
TCGETS = 0x5401  # Get terminal attributes (isatty check)

# Linux error codes
ENOTTY = 25      # Inappropriate ioctl for device
EBADF = 9        # Bad file descriptor

# Verified /dev/console metadata from ext2 image (nflasha7)
CONSOLE_DEV = 0x0501        # major 5, minor 1
CONSOLE_INODE = 118         # ext2 inode in /dev/console
CONSOLE_MODE = 8576         # S_IFCHR | 0600
CONSOLE_UID = 0             # root
CONSOLE_GID = 5             # tty
CONSOLE_BLKSIZE = 4096

# Linux ARM EABI struct stat64 size
STAT64_SIZE = 104

class GuestStdio:
    """Manages standard streams (stdin, stdout, stderr) and console I/O."""

    def __init__(self, rootfs_dev: int = 0xfc07):
        self.rootfs_dev = rootfs_dev
        self.stdout_log: List[bytes] = []
        self.stderr_log: List[bytes] = []

    def is_stdio_fd(self, fd: int) -> bool:
        return fd in (0, 1, 2)

    def pack_stat64(self) -> bytes:
        """Packs ARM EABI struct stat64 for /dev/console."""
        stat_bytes = bytearray(STAT64_SIZE)
        struct.pack_into('<Q', stat_bytes, 0, self.rootfs_dev)    # st_dev
        struct.pack_into('<I', stat_bytes, 12, CONSOLE_INODE)    # __st_ino
        struct.pack_into('<I', stat_bytes, 16, CONSOLE_MODE)     # st_mode
        struct.pack_into('<I', stat_bytes, 20, 1)                # st_nlink
        struct.pack_into('<I', stat_bytes, 24, CONSOLE_UID)      # st_uid
        struct.pack_into('<I', stat_bytes, 28, CONSOLE_GID)      # st_gid
        struct.pack_into('<Q', stat_bytes, 32, CONSOLE_DEV)      # st_rdev
        struct.pack_into('<q', stat_bytes, 48, 0)                # st_size
        struct.pack_into('<I', stat_bytes, 56, CONSOLE_BLKSIZE)  # st_blksize
        struct.pack_into('<Q', stat_bytes, 64, 0)                # st_blocks
        struct.pack_into('<Q', stat_bytes, 96, CONSOLE_INODE)    # st_ino
        return bytes(stat_bytes)

    def handle_fstat64(self, memory_writer, fd: int, buf_ptr: int) -> int:
        """Handles fstat64 on stdio descriptors."""
        if not self.is_stdio_fd(fd):
            return -EBADF
        data = self.pack_stat64()
        memory_writer(buf_ptr, data)
        return 0

    def handle_ioctl(self, fd: int, cmd: int, arg: int) -> Optional[int]:
        """Handles ioctls on stdio descriptors (e.g. TCGETS / isatty)."""
        if not self.is_stdio_fd(fd):
            return None
        if cmd == TCGETS:
            # Return -ENOTTY (0xffffffe7): non-terminal console device
            return (-ENOTTY) & 0xffffffff
        return None

    def handle_write(self, fd: int, data: bytes) -> int:
        """Appends output to diagnostic logs."""
        if fd == 1:
            self.stdout_log.append(data)
        elif fd == 2:
            self.stderr_log.append(data)
        return len(data)

    def handle_writev(self, memory_reader, fd: int, iov_ptr: int, iovcnt: int) -> int:
        """Gathers vector writes to diagnostic logs."""
        total = 0
        chunks = []
        for i in range(iovcnt):
            base, length = struct.unpack('<II', memory_reader(iov_ptr + i * 8, 8))
            if length > 0:
                chunk = memory_reader(base, length)
                chunks.append(chunk)
                total += length
        all_data = b''.join(chunks)
        self.handle_write(fd, all_data)
        return total
