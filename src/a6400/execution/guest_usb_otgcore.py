"""Guarded USB OTG core kernel interface (/dev/usb/otgcore).

Authentic Sony USB OTG core driver contract evidenced by:
- vmlinux.bin udif_devnodes table at offset 0x3d2ba8 (VA 0x604daba8):
  name: "usb/otgcore", dev_t: MKDEV(242, 2) -> Major 242, Minor 2
- vmlinux.bin unlocked_ioctl at offset 0x1afc00..0x1b01a0 (VA 0x601b7c00..0x601b81a0)
- libInfraUsbCmn.so otgcore management functions (0xa7e4..0xaa34):
  - 0xa806: open("/dev/usb/otgcore", O_RDWR=2)
  - 0xa828: fcntl(fd, F_SETFD, FD_CLOEXEC)
  - 0xa892: ioctl(fd, 0x4024e301, &struct_36_bytes) -> USB_OTGCORE_IOCTL_SET_PORT_DESC
  - 0xa8b4: ioctl(fd, 0x0000e304) -> USB_OTGCORE_IOCTL_START
  - 0xa9a0: ioctl(fd, 0x0000e303) -> USB_OTGCORE_IOCTL_STOP
  - 0xa9c2: ioctl(fd, 0x0000e302) -> USB_OTGCORE_IOCTL_RESET
  - 0xa7d2: ioctl(fd, 0x4040e311, &struct_64_bytes) -> USB_OTGCORE_IOCTL_SET_CONFIG
  - 0xaa0a: close(fd)
- Strict task limits: all user pointers checked against address_limit (TASK_SIZE <= 0x5f000000).
"""
import struct

USB_OTGCORE_IOCTL_SET_PORT_DESC = 0x4024e301  # _IOW(0xe3, 1, 36)
USB_OTGCORE_IOCTL_RESET = 0x0000e302          # _IO(0xe3, 2)
USB_OTGCORE_IOCTL_STOP = 0x0000e303           # _IO(0xe3, 3)
USB_OTGCORE_IOCTL_START = 0x0000e304          # _IO(0xe3, 4)
USB_OTGCORE_IOCTL_GET_STATUS = 0x8001e30b     # _IOR(0xe3, 0x0b, 1)
USB_OTGCORE_IOCTL_SET_MODE = 0x4001e30c       # _IOW(0xe3, 0x0c, 1)
USB_OTGCORE_IOCTL_SET_FLAG = 0x4001e30d       # _IOW(0xe3, 0x0d, 1)
USB_OTGCORE_IOCTL_GET_INFO = 0x8008e310       # _IOR(0xe3, 0x10, 8)
USB_OTGCORE_IOCTL_SET_CONFIG = 0x4040e311     # _IOW(0xe3, 0x11, 64)
USB_OTGCORE_IOCTL_SET_PARAM = 0x4010e313      # _IOW(0xe3, 0x13, 16)


class UnsupportedUsbOtgCore(RuntimeError):
    def __init__(self, reason, **details):
        super().__init__(reason)
        self.details = {'reason': reason, 'device': '/dev/usb/otgcore', **details}


class GuestUsbOtgCore:
    """Emulates /dev/usb/otgcore character device (242:2)."""

    def __init__(self, address_limit=0x5f000000):
        self.address_limit = address_limit
        self.major = 242
        self.minor = 2
        self.owners = {}
        self.started = False
        self.port_desc = None
        self.config = None
        self.transactions = []

    def open(self, flags, caller_pid=None, caller_tgid=None):
        owner_id = len(self.owners) + 1
        owner = {
            'owner_id': owner_id,
            'flags': flags,
            'caller_pid': caller_pid,
            'caller_tgid': caller_tgid,
        }
        self.owners[owner_id] = owner
        self.transactions.append({'operation': 'open', 'flags': flags, 'owner_id': owner_id})
        return owner

    def ioctl(self, owner_id, cmd, arg, mem_read, mem_write):
        owner = self.owners.get(owner_id)
        if not owner:
            raise UnsupportedUsbOtgCore('usb_otgcore_invalid_owner_descriptor', owner_id=owner_id)

        if cmd == USB_OTGCORE_IOCTL_SET_PORT_DESC:
            if arg >= self.address_limit or arg == 0:
                raise UnsupportedUsbOtgCore('user_pointer_outside_task_limit', address=arg, limit=self.address_limit)
            raw = mem_read(arg, 36)
            self.port_desc = raw
            self.transactions.append({
                'operation': 'ioctl',
                'cmd': cmd,
                'name': 'USB_OTGCORE_IOCTL_SET_PORT_DESC',
                'size': 36,
                'returned': 0
            })
            return 0

        if cmd == USB_OTGCORE_IOCTL_START:
            self.started = True
            self.transactions.append({
                'operation': 'ioctl',
                'cmd': cmd,
                'name': 'USB_OTGCORE_IOCTL_START',
                'returned': 0
            })
            return 0

        if cmd == USB_OTGCORE_IOCTL_STOP:
            self.started = False
            self.transactions.append({
                'operation': 'ioctl',
                'cmd': cmd,
                'name': 'USB_OTGCORE_IOCTL_STOP',
                'returned': 0
            })
            return 0

        if cmd == USB_OTGCORE_IOCTL_RESET:
            self.started = False
            self.transactions.append({
                'operation': 'ioctl',
                'cmd': cmd,
                'name': 'USB_OTGCORE_IOCTL_RESET',
                'returned': 0
            })
            return 0

        if cmd == USB_OTGCORE_IOCTL_SET_CONFIG:
            if arg >= self.address_limit or arg == 0:
                raise UnsupportedUsbOtgCore('user_pointer_outside_task_limit', address=arg, limit=self.address_limit)
            raw = mem_read(arg, 64)
            self.config = raw
            self.transactions.append({
                'operation': 'ioctl',
                'cmd': cmd,
                'name': 'USB_OTGCORE_IOCTL_SET_CONFIG',
                'size': 64,
                'returned': 0
            })
            return 0

        if cmd == USB_OTGCORE_IOCTL_GET_STATUS:
            if arg >= self.address_limit or arg == 0:
                raise UnsupportedUsbOtgCore('user_pointer_outside_task_limit', address=arg, limit=self.address_limit)
            mem_write(arg, b'\x00')
            self.transactions.append({
                'operation': 'ioctl',
                'cmd': cmd,
                'name': 'USB_OTGCORE_IOCTL_GET_STATUS',
                'returned': 0
            })
            return 0

        if cmd == USB_OTGCORE_IOCTL_GET_INFO:
            if arg >= self.address_limit or arg == 0:
                raise UnsupportedUsbOtgCore('user_pointer_outside_task_limit', address=arg, limit=self.address_limit)
            mem_write(arg, b'\x00' * 8)
            self.transactions.append({
                'operation': 'ioctl',
                'cmd': cmd,
                'name': 'USB_OTGCORE_IOCTL_GET_INFO',
                'returned': 0
            })
            return 0

        if cmd == USB_OTGCORE_IOCTL_SET_MODE:
            if arg >= self.address_limit or arg == 0:
                raise UnsupportedUsbOtgCore('user_pointer_outside_task_limit', address=arg, limit=self.address_limit)
            raw = mem_read(arg, 1)
            self.transactions.append({
                'operation': 'ioctl',
                'cmd': cmd,
                'name': 'USB_OTGCORE_IOCTL_SET_MODE',
                'returned': 0
            })
            return 0

        if cmd == USB_OTGCORE_IOCTL_SET_FLAG:
            if arg >= self.address_limit or arg == 0:
                raise UnsupportedUsbOtgCore('user_pointer_outside_task_limit', address=arg, limit=self.address_limit)
            raw = mem_read(arg, 1)
            self.transactions.append({
                'operation': 'ioctl',
                'cmd': cmd,
                'name': 'USB_OTGCORE_IOCTL_SET_FLAG',
                'returned': 0
            })
            return 0

        if cmd == USB_OTGCORE_IOCTL_SET_PARAM:
            if arg >= self.address_limit or arg == 0:
                raise UnsupportedUsbOtgCore('user_pointer_outside_task_limit', address=arg, limit=self.address_limit)
            raw = mem_read(arg, 16)
            self.transactions.append({
                'operation': 'ioctl',
                'cmd': cmd,
                'name': 'USB_OTGCORE_IOCTL_SET_PARAM',
                'returned': 0
            })
            return 0

        return -22  # -EINVAL

    def close(self, owner_id):
        if owner_id in self.owners:
            self.transactions.append({'operation': 'close', 'owner_id': owner_id})
            del self.owners[owner_id]
            return 0
        return -9  # -EBADF
