"""Guarded USB bus power kernel interface (/dev/usb/buspwr).

Authentic Sony USB bus power driver contract evidenced by:
- nflasha7 inode 240 (character device, major 248, minor 13)
- devno.ko offset 0x1d0: "usb/buspwr" -> major 248, minor 13
- /usr/kmod/usb_buspwr.ko fops (usb_buspwr_fops_open, usb_buspwr_fops_close, usb_buspwr_fops_ioctl)
- libUsbBusPower.so methods (OpenResourceFile, SetSuspendEnable, SetChargingEnable, etc.)

Strictly adheres to fail-closed semantics and user memory task limits (TASK_SIZE <= 0x5f000000).
"""
import struct

USB_BUSPWR_MAGIC_BASE = 0xf200
USB_BUSPWR_CMD_SET_SUSPEND_ENABLE = 0xf200
USB_BUSPWR_CMD_SET_SUSPEND_DISABLE = 0xf201
USB_BUSPWR_CMD_SET_CURRENT_LIMIT_100MA = 0xf202
USB_BUSPWR_CMD_SET_CURRENT_LIMIT_500MA = 0xf203
USB_BUSPWR_CMD_SET_CHARGING_ENABLE = 0xf204
USB_BUSPWR_CMD_SET_CHARGING_DISABLE = 0xf205
USB_BUSPWR_CMD_START_NOTIFY_EVENT = 0xf206
USB_BUSPWR_CMD_STOP_NOTIFY_EVENT = 0xf207
USB_BUSPWR_CMD_GET_CURRENT_PORT_TYPE = 0xf209
USB_BUSPWR_CMD_GET_CURRENT_BATT_STATE = 0xf20a


class UnsupportedUsbBusPower(RuntimeError):
    def __init__(self, reason, **details):
        super().__init__(reason)
        self.details = {'reason': reason, 'device': '/dev/usb/buspwr', **details}


class GuestUsbBusPower:
    """Emulates /dev/usb/buspwr character device (248:13)."""

    def __init__(self, address_limit=0x5f000000):
        self.address_limit = address_limit
        self.major = 248
        self.minor = 13
        self.owners = {}
        self.suspend_enabled = False
        self.charging_enabled = False
        self.current_limit_ma = 500
        self.notify_events_enabled = False
        self.port_type = 0  # 0: PORT_NONE / disconnected
        self.batt_state = 0  # 0: normal
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
            raise UnsupportedUsbBusPower('usb_buspower_invalid_owner_descriptor', owner_id=owner_id)

        # Validate cmd in authentic range [0xf200, 0xf220]
        if cmd < USB_BUSPWR_MAGIC_BASE or cmd > (USB_BUSPWR_MAGIC_BASE + 0x20):
            return -22  # -EINVAL

        if cmd == USB_BUSPWR_CMD_SET_SUSPEND_ENABLE:
            self.suspend_enabled = True
            self.transactions.append({'operation': 'ioctl', 'cmd': cmd, 'name': 'SET_SUSPEND_ENABLE', 'returned': 0})
            return 0

        if cmd == USB_BUSPWR_CMD_SET_SUSPEND_DISABLE:
            self.suspend_enabled = False
            self.transactions.append({'operation': 'ioctl', 'cmd': cmd, 'name': 'SET_SUSPEND_DISABLE', 'returned': 0})
            return 0

        if cmd == USB_BUSPWR_CMD_SET_CURRENT_LIMIT_100MA:
            self.current_limit_ma = 100
            self.transactions.append({'operation': 'ioctl', 'cmd': cmd, 'name': 'SET_CURRENT_LIMIT_100MA', 'returned': 0})
            return 0

        if cmd == USB_BUSPWR_CMD_SET_CURRENT_LIMIT_500MA:
            self.current_limit_ma = 500
            self.transactions.append({'operation': 'ioctl', 'cmd': cmd, 'name': 'SET_CURRENT_LIMIT_500MA', 'returned': 0})
            return 0

        if cmd == USB_BUSPWR_CMD_SET_CHARGING_ENABLE:
            self.charging_enabled = True
            self.transactions.append({'operation': 'ioctl', 'cmd': cmd, 'name': 'SET_CHARGING_ENABLE', 'returned': 0})
            return 0

        if cmd == USB_BUSPWR_CMD_SET_CHARGING_DISABLE:
            self.charging_enabled = False
            self.transactions.append({'operation': 'ioctl', 'cmd': cmd, 'name': 'SET_CHARGING_DISABLE', 'returned': 0})
            return 0

        if cmd == USB_BUSPWR_CMD_START_NOTIFY_EVENT:
            self.notify_events_enabled = True
            self.transactions.append({'operation': 'ioctl', 'cmd': cmd, 'name': 'START_NOTIFY_EVENT', 'returned': 0})
            return 0

        if cmd == USB_BUSPWR_CMD_STOP_NOTIFY_EVENT:
            self.notify_events_enabled = False
            self.transactions.append({'operation': 'ioctl', 'cmd': cmd, 'name': 'STOP_NOTIFY_EVENT', 'returned': 0})
            return 0

        if cmd == USB_BUSPWR_CMD_GET_CURRENT_PORT_TYPE:
            if arg >= self.address_limit or arg == 0:
                raise UnsupportedUsbBusPower('user_pointer_outside_task_limit', address=arg, limit=self.address_limit)
            mem_write(arg, struct.pack('<I', self.port_type))
            self.transactions.append({'operation': 'ioctl', 'cmd': cmd, 'name': 'GET_CURRENT_PORT_TYPE',
                                      'port_type': self.port_type, 'returned': 0})
            return 0

        if cmd == USB_BUSPWR_CMD_GET_CURRENT_BATT_STATE:
            if arg >= self.address_limit or arg == 0:
                raise UnsupportedUsbBusPower('user_pointer_outside_task_limit', address=arg, limit=self.address_limit)
            mem_write(arg, struct.pack('<I', self.batt_state))
            self.transactions.append({'operation': 'ioctl', 'cmd': cmd, 'name': 'GET_CURRENT_BATT_STATE',
                                      'batt_state': self.batt_state, 'returned': 0})
            return 0

        # Commands in table range that return 0
        if cmd in (0xf20c, 0xf20d, 0xf20e, 0xf20f, 0xf214, 0xf215):
            self.transactions.append({'operation': 'ioctl', 'cmd': cmd, 'name': f'CMD_{hex(cmd)}', 'returned': 0})
            return 0

        return -22  # -EINVAL

    def close(self, owner_id):
        if owner_id in self.owners:
            del self.owners[owner_id]
            self.transactions.append({'operation': 'close', 'owner_id': owner_id})
