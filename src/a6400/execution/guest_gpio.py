"""Guarded GPIO kernel interface (/dev/gpio).

Authentic Sony GPIO driver contract evidenced by nflasha7 inode 366 (major 240, minor 0)
and libul_GpioCtrl.so / libResourceBluetooth.so disassembly.
No synthetic hardware success or faked pin states without verification.
"""
import struct

GPIO_MAGIC = 0x47
GPIO_CMD_READ_WRITE = 0xc0104701
GPIO_CMD_SET_MODE = 0xc0104702

# Mode definitions from libul_GpioCtrl.so:
GPIOMODE_INPUT = 1
GPIOMODE_OUTPUT_H = 2
GPIOMODE_OUTPUT_L = 3


class UnsupportedGpio(RuntimeError):
    def __init__(self, reason, **details):
        super().__init__(reason)
        self.details = {'reason': reason, 'device': '/dev/gpio', **details}


class GuestGpio:
    """Emulates /dev/gpio character device (240:0)."""

    def __init__(self, address_limit=0x5f000000):
        self.address_limit = address_limit
        self.major = 240
        self.minor = 0
        self.owners = {}
        self.pins = {}  # (port, pin) -> {'mode': int, 'value': int}
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
            raise UnsupportedGpio('gpio_invalid_owner_descriptor', owner_id=owner_id)

        if arg >= self.address_limit:
            raise UnsupportedGpio('user_pointer_outside_task_limit', address=arg, limit=self.address_limit)

        raw = mem_read(arg, 16)
        if len(raw) < 16:
            raise UnsupportedGpio('gpio_truncated_ioctl_argument', address=arg, length=len(raw))

        port, pin, param, val = struct.unpack('<4I', raw)

        if cmd == GPIO_CMD_SET_MODE:
            mode = val
            state = self.pins.setdefault((port, pin), {'mode': mode, 'value': 0})
            state['mode'] = mode
            self.transactions.append({
                'operation': 'ioctl', 'cmd': cmd, 'name': 'GPIO_CMD_SET_MODE',
                'port': port, 'pin': pin, 'mode': mode, 'returned': 0
            })
            return 0

        if cmd == GPIO_CMD_READ_WRITE:
            state = self.pins.setdefault((port, pin), {'mode': 0, 'value': 0})
            state['value'] = val
            self.transactions.append({
                'operation': 'ioctl', 'cmd': cmd, 'name': 'GPIO_CMD_READ_WRITE',
                'port': port, 'pin': pin, 'param': param, 'val': val, 'returned': 0
            })
            return 0

        raise UnsupportedGpio('unsupported_gpio_ioctl', cmd=hex(cmd), arg=hex(arg), owner_id=owner_id)

    def close(self, owner_id):
        if owner_id in self.owners:
            del self.owners[owner_id]
            self.transactions.append({'operation': 'close', 'owner_id': owner_id})
