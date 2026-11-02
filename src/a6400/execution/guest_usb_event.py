"""Guarded USB event kernel interface (/dev/usb/event).

Authentic Sony USB event driver contract evidenced by:
- vmlinux.bin udif_devnodes table at offset 0x3d2ba8 (VA 0x604daba8):
  name: "usb/event", dev_t: MKDEV(242, 0) -> Major 242, Minor 0
- vmlinux.bin file_operations at offset 0x3dcf38:
  open: 0x602b5a00, release: 0x602b56f8, unlocked_ioctl: 0x602b5814, read: 0x602b5d7c
- libInfraUsbCmn.so usb_event_start (0xc7a4), usb_event_stop (0xca1c),
  usb_event_enable (0xcb78), usb_event_disable (0xcc74)
- Ioctl commands:
  - 0x4004e101: USB_EVENT_IOCTL_ENABLE (_IOW(0xe1, 1, uint32))
  - 0x4004e102: USB_EVENT_IOCTL_DISABLE (_IOW(0xe1, 2, uint32))
  - 0x0000e103: USB_EVENT_IOCTL_STOP (_IO(0xe1, 3))

Strictly adheres to fail-closed semantics and user memory task limits (TASK_SIZE <= 0x5f000000).
"""
import struct

USB_EVENT_IOCTL_ENABLE = 0x4004e101
USB_EVENT_IOCTL_DISABLE = 0x4004e102
USB_EVENT_IOCTL_STOP = 0x0000e103


class UnsupportedUsbEvent(RuntimeError):
    def __init__(self, reason, **details):
        super().__init__(reason)
        self.details = {'reason': reason, 'device': '/dev/usb/event', **details}


class GuestUsbEvent:
    """Emulates /dev/usb/event character device (242:0)."""

    def __init__(self, address_limit=0x5f000000):
        self.address_limit = address_limit
        self.major = 242
        self.minor = 0
        self.owners = {}
        self.enabled_events = set()
        self.stopped = False
        self.pending_events = []
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
            raise UnsupportedUsbEvent('usb_event_invalid_owner_descriptor', owner_id=owner_id)

        if cmd == USB_EVENT_IOCTL_ENABLE:
            if arg >= self.address_limit or arg == 0:
                raise UnsupportedUsbEvent('user_pointer_outside_task_limit', address=arg, limit=self.address_limit)
            raw = mem_read(arg, 4)
            event_id = struct.unpack('<I', raw)[0]
            self.enabled_events.add(event_id)
            self.transactions.append({'operation': 'ioctl', 'cmd': cmd, 'name': 'USB_EVENT_IOCTL_ENABLE',
                                      'event_id': event_id, 'returned': 0})
            return 0

        if cmd == USB_EVENT_IOCTL_DISABLE:
            if arg >= self.address_limit or arg == 0:
                raise UnsupportedUsbEvent('user_pointer_outside_task_limit', address=arg, limit=self.address_limit)
            raw = mem_read(arg, 4)
            event_id = struct.unpack('<I', raw)[0]
            self.enabled_events.discard(event_id)
            self.transactions.append({'operation': 'ioctl', 'cmd': cmd, 'name': 'USB_EVENT_IOCTL_DISABLE',
                                      'event_id': event_id, 'returned': 0})
            return 0

        if cmd == USB_EVENT_IOCTL_STOP:
            self.stopped = True
            self.transactions.append({'operation': 'ioctl', 'cmd': cmd, 'name': 'USB_EVENT_IOCTL_STOP',
                                      'returned': 0})
            return 0

        return -22  # -EINVAL

    def read(self, owner_id, count, mem_write):
        owner = self.owners.get(owner_id)
        if not owner:
            raise UnsupportedUsbEvent('usb_event_invalid_owner_descriptor', owner_id=owner_id)

        if self.stopped:
            self.transactions.append({'operation': 'read', 'bytes_read': 0, 'stopped': True})
            return 0  # EOF

        if not self.pending_events:
            # No events available; blocks waiting for hardware event
            return None

        data = self.pending_events.pop(0)
        bytes_to_copy = min(count, len(data))
        mem_write(data[:bytes_to_copy])
        self.transactions.append({'operation': 'read', 'bytes_read': bytes_to_copy})
        return bytes_to_copy

    def close(self, owner_id):
        if owner_id in self.owners:
            del self.owners[owner_id]
            self.transactions.append({'operation': 'close', 'owner_id': owner_id})
        return 0
