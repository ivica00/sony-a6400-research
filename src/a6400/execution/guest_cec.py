"""Sony CXD90045 HDMI-CEC character driver (/dev/cec, major 248, minor 27) contract.

Derived from /usr/kmod/cec.ko:
- Device registration: udif_devnodes entry 47 ("cec", major 248, minor 27, count 1).
  Confirmed on live ILCE-6400 hardware (/proc/devices: 248 cec).
- File operations in cec.ko:
  - cec_dev_open    (0x5d28): allocates 0x50-byte state struct, initializes mutex, spinlock,
    waitqueue, and calls cec_core_open().
  - cec_dev_release (0x5c78): calls cec_core_set_connect(0), cec_core_release(), frees state.
  - cec_dev_poll    (0x5a6c): returns 0x104 (POLLOUT | POLLWRNORM) when rx queue is empty;
    ORs 0x41 (POLLIN | POLLRDNORM) when rx event nodes are queued.
  - cec_dev_write   (0x5af4): requires count >= 28 (0x1c); copies 28 bytes and calls
    cec_core_set_device_status(), returning count. Returns -EMSGSIZE (-90) if count <= 0x1b.
  - cec_dev_read    (0x5b80): pops rx event node or returns -EAGAIN (-11) if empty.
  - cec_dev_ioctl   (0x6074): 10 _IOWR('C', nr, size) commands:
    - 0xc0044301: cec_core_set_connect       (arg -> user ptr to 4-byte int)
    - 0xc0044302: cec_core_set_power         (arg -> 4-byte int)
    - 0xc0044303: cec_core_set_status        (arg -> 4-byte int)
    - 0xc0044304: cec_core_set_request       (arg -> 4-byte int)
    - 0xc0114304: cec_core_set_send          (arg -> user ptr to 17-byte CEC frame)
    - 0xc0084305: cec_core_set_register      (arg -> user ptr to 8-byte reg struct, R/W)
    - 0xc0044306: cec_core_set_cycle_time    (arg -> 4-byte int)
    - 0xc004430a: cec_core_set_key_interval  (arg -> 4-byte int)
    - 0xc004430b: cec_core_get_abort_flag    (writes 4-byte abort flag to arg)
    - 0xc001430e: cec_core_set_lgc_addr      (arg -> 1-byte logical address)
"""
import struct


class UnsupportedCec(Exception):
    def __init__(self, reason, **details):
        super().__init__(reason)
        self.reason = reason
        self.details = {'reason': reason, **details}


CEC_IOCTL_SET_CONNECT = 0xc0044301
CEC_IOCTL_SET_POWER = 0xc0044302
CEC_IOCTL_SET_STATUS = 0xc0044303
CEC_IOCTL_SET_REQUEST = 0xc0044304
CEC_IOCTL_SET_SEND = 0xc0114304
CEC_IOCTL_SET_REGISTER = 0xc0084305
CEC_IOCTL_SET_CYCLE_TIME = 0xc0044306
CEC_IOCTL_SET_KEY_INTERVAL = 0xc004430a
CEC_IOCTL_GET_ABORT_FLAG = 0xc004430b
CEC_IOCTL_SET_LGC_ADDR = 0xc001430e

CEC_IOCTL_NAMES = {
    CEC_IOCTL_SET_CONNECT: 'CEC_IOCTL_SET_CONNECT',
    CEC_IOCTL_SET_POWER: 'CEC_IOCTL_SET_POWER',
    CEC_IOCTL_SET_STATUS: 'CEC_IOCTL_SET_STATUS',
    CEC_IOCTL_SET_REQUEST: 'CEC_IOCTL_SET_REQUEST',
    CEC_IOCTL_SET_SEND: 'CEC_IOCTL_SET_SEND',
    CEC_IOCTL_SET_REGISTER: 'CEC_IOCTL_SET_REGISTER',
    CEC_IOCTL_SET_CYCLE_TIME: 'CEC_IOCTL_SET_CYCLE_TIME',
    CEC_IOCTL_SET_KEY_INTERVAL: 'CEC_IOCTL_SET_KEY_INTERVAL',
    CEC_IOCTL_GET_ABORT_FLAG: 'CEC_IOCTL_GET_ABORT_FLAG',
    CEC_IOCTL_SET_LGC_ADDR: 'CEC_IOCTL_SET_LGC_ADDR',
}


class GuestCec:
    """Tracks /dev/cec character device state and ioctl transactions."""

    major = 248
    minor = 27

    def __init__(self):
        self.next_owner_id = 1
        self.open_handles = {}
        self.transactions = []
        self.connected = 0
        self.power_state = 0
        self.status_state = 0
        self.logical_addr = 0x0f
        self.cycle_time = 0
        self.key_interval = 0
        self.abort_flag = 0
        self.registers = {}
        self.rx_queue = []

    def open(self, flags, pid, tgid):
        acc_mode = flags & 3
        if acc_mode not in (0, 1, 2):
            raise UnsupportedCec('unsupported_open_flags', flags=flags)
        owner_id = self.next_owner_id
        self.next_owner_id += 1
        handle = {
            'owner_id': owner_id,
            'flags': flags,
            'pid': pid,
            'tgid': tgid,
            'poll_status': 0,
        }
        self.open_handles[owner_id] = handle
        self.transactions.append({
            'op': 'open',
            'owner_id': owner_id,
            'flags': flags,
            'pid': pid,
            'tgid': tgid,
        })
        return handle

    def close(self, owner_id):
        if owner_id not in self.open_handles:
            raise UnsupportedCec('close_on_unknown_owner', owner_id=owner_id)
        del self.open_handles[owner_id]
        self.transactions.append({'op': 'close', 'owner_id': owner_id})
        return 0

    def poll(self, owner_id):
        """Matches cec_dev_poll (0x5a6c in cec.ko)."""
        if owner_id not in self.open_handles:
            raise UnsupportedCec('poll_on_unknown_owner', owner_id=owner_id)
        handle = self.open_handles[owner_id]
        mask = handle['poll_status']
        if mask != 0:
            mask |= 0x104
            handle['poll_status'] = 0
        else:
            mask = 0x104  # POLLOUT | POLLWRNORM
        if self.rx_queue:
            mask |= 0x41  # POLLIN | POLLRDNORM
        return mask

    def write(self, owner_id, data: bytes):
        """Matches cec_dev_write (0x5af4 in cec.ko): requires count >= 28 (0x1c)."""
        if owner_id not in self.open_handles:
            raise UnsupportedCec('write_on_unknown_owner', owner_id=owner_id)
        if len(data) <= 0x1b:
            return 0xffffffa6  # -EMSGSIZE (-90)
        self.transactions.append({
            'op': 'write',
            'owner_id': owner_id,
            'count': len(data),
            'payload_hex': data[:28].hex(),
        })
        return len(data)

    def read(self, owner_id, count: int, mem_writer):
        """Matches cec_dev_read (0x5b80 in cec.ko)."""
        if owner_id not in self.open_handles:
            raise UnsupportedCec('read_on_unknown_owner', owner_id=owner_id)
        if not self.rx_queue:
            return None
        payload = self.rx_queue[0]
        if count < len(payload):
            return 0xffffffa6  # -EMSGSIZE (-90)
        self.rx_queue.pop(0)
        mem_writer(payload)
        self.transactions.append({
            'op': 'read',
            'owner_id': owner_id,
            'count': len(payload),
        })
        return len(payload)

    def ioctl(self, owner_id, cmd, arg, mem_reader, mem_writer):
        """Matches cec_dev_ioctl (0x6074 in cec.ko)."""
        if owner_id not in self.open_handles:
            raise UnsupportedCec('ioctl_on_unknown_owner', owner_id=owner_id, cmd=cmd, arg=arg)
        if cmd not in CEC_IOCTL_NAMES:
            raise UnsupportedCec('unsupported_ioctl_command', owner_id=owner_id, cmd=cmd, arg=arg)
        if arg == 0:
            raise UnsupportedCec('null_ioctl_arg', owner_id=owner_id, cmd=cmd)

        raw4 = mem_reader(arg, 4)
        val4 = struct.unpack('<I', raw4)[0]

        if cmd == CEC_IOCTL_SET_CONNECT:
            if val4 == 0:
                raise UnsupportedCec('null_set_connect_ptr', owner_id=owner_id, cmd=cmd)
            conn_raw = mem_reader(val4, 4)
            self.connected = struct.unpack('<I', conn_raw)[0]
        elif cmd == CEC_IOCTL_SET_POWER:
            self.power_state = val4
        elif cmd == CEC_IOCTL_SET_STATUS:
            self.status_state = val4
        elif cmd == CEC_IOCTL_SET_REQUEST:
            pass
        elif cmd == CEC_IOCTL_SET_SEND:
            if val4 == 0:
                raise UnsupportedCec('null_set_send_ptr', owner_id=owner_id, cmd=cmd)
            _frame = mem_reader(val4, 0x11)
        elif cmd == CEC_IOCTL_SET_REGISTER:
            if val4 == 0:
                raise UnsupportedCec('null_set_register_ptr', owner_id=owner_id, cmd=cmd)
            reg_data = bytearray(mem_reader(val4, 8))
            mem_writer(val4, bytes(reg_data))
        elif cmd == CEC_IOCTL_SET_CYCLE_TIME:
            self.cycle_time = val4
        elif cmd == CEC_IOCTL_SET_KEY_INTERVAL:
            self.key_interval = val4
        elif cmd == CEC_IOCTL_GET_ABORT_FLAG:
            mem_writer(arg, struct.pack('<I', self.abort_flag))
        elif cmd == CEC_IOCTL_SET_LGC_ADDR:
            self.logical_addr = raw4[0]

        self.transactions.append({
            'op': 'ioctl',
            'owner_id': owner_id,
            'cmd': cmd,
            'cmd_name': CEC_IOCTL_NAMES[cmd],
            'arg': arg,
            'val': val4,
        })
        return 0
