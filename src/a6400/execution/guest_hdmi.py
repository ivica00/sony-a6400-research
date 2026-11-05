"""Guarded HDMI controller kernel interface (/dev/hdmi).

Authentic Sony HDMI driver contract evidenced by:
- reports/a6400_hw_dump.txt:
    crwxrwxrwx 1 root root 248, 25 /dev/hdmi
    248 hdmi (under /proc/devices)
    Module: hdmi.ko (154,375 bytes), libInfraHdmi.so
- vmlinux.bin / devno.ko udif_devnodes table:
    MKDEV(248, 25) -> Major 248, Minor 25 (/dev/hdmi)
    MKDEV(248, 26) -> Major 248, Minor 26 (/dev/hdmi_external_tx)
    MKDEV(248, 30) -> Major 248, Minor 30 (/dev/hdmi_input)
- hdmi.ko operations:
    hdmi_dev_open (0x7e04)
    hdmi_dev_release (0x7d4c)
    hdmi_dev_read (0x7c54)
    hdmi_dev_write (0x7bc8)
    hdmi_dev_poll (0x7b40)
    hdmi_dev_ioctl (0x813c)
- libInfraHdmi.so consumer methods:
    0x4bf35: HDMI::HdmiCtrlImpl::initialize
    0x4be95: HDMI::HdmiCtrlImpl::finalize
    0x4bddd: HDMI::HdmiCtrlImpl::getMonitorStatus (0xc0044802)
    0x4c075: HDMI::HdmiCtrlImpl::setMonitoringHPD (0xc0044801, 0xc004480d, 0xc004480e)
    0x4cacd: HDMI::HdmiCtrlImpl::setPower (0xc0044803)
    0x4ccc5: HDMI::HdmiCtrlImpl::setTmds (0xc0044804)
    0x4d3f5: HDMI::HdmiCtrlImpl::setReso (0xc0044805)
    0x4d5fd: HDMI::HdmiCtrlImpl::setXvYcc (0xc0044806)
    0x4d019: HDMI::HdmiCtrlImpl::setSrcDev (0xc0044807)
    0x4d1bd: HDMI::HdmiCtrlImpl::setAudio (0xc0044808)
    0x4ce75: HDMI::HdmiCtrlImpl::setContent (0xc004480b)
    0x4d819: HDMI::HdmiCtrlImpl::setDimension (0xc004480f)
    0x4d8a9: HDMI::HdmiCtrlImpl::setVSIF (0xc0044810)
    0x3e891: HDMI::HDMISenserResponder::set_colorbar_for_musashi (0xc0044811)
    0x4dcf9: HDMI::HdmiCtrlImpl::setForceStop (0xc0044813)

Strictly adheres to fail-closed semantics and user memory task limits (TASK_SIZE <= 0x5f000000).
"""
import struct

HDMI_IOCTL_INIT = 0xc0044801            # _IOWR('H', 1, 4) - init / monitor HPD
HDMI_IOCTL_GET_STATUS = 0xc0044802      # _IOWR('H', 2, 4) - getMonitorStatus (96 bytes)
HDMI_IOCTL_SET_POWER = 0xc0044803       # _IOWR('H', 3, 4) - setPower
HDMI_IOCTL_SET_TMDS = 0xc0044804        # _IOWR('H', 4, 4) - setTmds
HDMI_IOCTL_SET_RESO = 0xc0044805        # _IOWR('H', 5, 4) - setReso (20 bytes)
HDMI_IOCTL_SET_XVYCC = 0xc0044806       # _IOWR('H', 6, 4) - setXvYcc (36 bytes)
HDMI_IOCTL_SET_SRC_DEV = 0xc0044807     # _IOWR('H', 7, 4) - setSrcDev (1 byte)
HDMI_IOCTL_SET_AUDIO = 0xc0044808       # _IOWR('H', 8, 4) - setAudio (12 bytes)
HDMI_IOCTL_SET_CONTENT = 0xc004480b     # _IOWR('H', 11, 4) - setContent
HDMI_IOCTL_SET_HPD_1 = 0xc004480d       # _IOWR('H', 13, 4) - setMonitoringHPD 1
HDMI_IOCTL_SET_HPD_2 = 0xc004480e       # _IOWR('H', 14, 4) - setMonitoringHPD 2
HDMI_IOCTL_SET_DIMENSION = 0xc004480f   # _IOWR('H', 15, 4) - setDimension
HDMI_IOCTL_SET_VSIF = 0xc0044810        # _IOWR('H', 16, 4) - setVSIF
HDMI_IOCTL_SET_COLORBAR = 0xc0044811    # _IOWR('H', 17, 4) - setColorbar
HDMI_IOCTL_SET_FORCE_STOP = 0xc0044813  # _IOWR('H', 19, 4) - setForceStop


class UnsupportedHdmi(RuntimeError):
    def __init__(self, reason, **details):
        super().__init__(reason)
        self.details = {'reason': reason, 'device': '/dev/hdmi', **details}


class GuestHdmi:
    """Emulates /dev/hdmi character device (248:25)."""

    def __init__(self, address_limit=0x5f000000):
        self.address_limit = address_limit
        self.major = 248
        self.minor = 25
        self.owners = {}
        self.power_state = 0
        self.tmds_param = 0
        self.resolution = None
        self.xvycc_data = None
        self.src_dev = 0
        self.audio_data = None
        self.content_param = 0
        self.dimension_param = 0
        self.vsif_param = 0
        self.colorbar_enabled = False
        self.force_stop = 0
        self.connected = False
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

    def close(self, owner_id):
        if owner_id in self.owners:
            del self.owners[owner_id]
            self.transactions.append({'operation': 'close', 'owner_id': owner_id})
            return 0
        return -9

    def poll(self, owner_id):
        if owner_id not in self.owners:
            raise UnsupportedHdmi('hdmi_invalid_owner_descriptor', owner_id=owner_id)
        # POLLOUT | POLLWRNORM (0x104)
        return 0x104

    def write(self, owner_id, buf_ptr, count, mem_read):
        if owner_id not in self.owners:
            raise UnsupportedHdmi('hdmi_invalid_owner_descriptor', owner_id=owner_id)
        if count < 18:
            # -EMSGSIZE = -90
            return -90
        if buf_ptr >= self.address_limit or buf_ptr + count > self.address_limit:
            raise UnsupportedHdmi('user_pointer_outside_task_limit', address=buf_ptr, limit=self.address_limit)
        raw = mem_read(buf_ptr, count)
        self.transactions.append({'operation': 'write', 'count': count, 'data_prefix': raw[:16].hex()})
        return count

    def read(self, owner_id, buf_ptr, count, mem_write):
        if owner_id not in self.owners:
            raise UnsupportedHdmi('hdmi_invalid_owner_descriptor', owner_id=owner_id)
        # Empty queue -> -EAGAIN (-11)
        return -11

    def ioctl(self, owner_id, cmd, arg, mem_read, mem_write):
        owner = self.owners.get(owner_id)
        if not owner:
            raise UnsupportedHdmi('hdmi_invalid_owner_descriptor', owner_id=owner_id)

        if arg >= self.address_limit or arg == 0:
            raise UnsupportedHdmi('user_pointer_outside_task_limit', address=arg, limit=self.address_limit)

        # In hdmi_dev_ioctl, arg is a user pointer to a 4-byte buffer/pointer
        ptr_val = struct.unpack('<I', mem_read(arg, 4))[0]

        if cmd == HDMI_IOCTL_INIT:
            # Reads 8 bytes from ptr_val if non-zero
            data = b''
            if ptr_val != 0 and ptr_val < self.address_limit:
                data = mem_read(ptr_val, 8)
            self.transactions.append({
                'operation': 'ioctl',
                'cmd': cmd,
                'name': 'HDMI_IOCTL_INIT',
                'returned': 0
            })
            return 0

        if cmd == HDMI_IOCTL_GET_STATUS:
            # Writes 0x60 (96 bytes) of Shdmi_monitor_data to ptr_val
            if ptr_val >= self.address_limit or ptr_val == 0:
                raise UnsupportedHdmi('user_pointer_outside_task_limit', address=ptr_val, limit=self.address_limit)
            status_bytes = bytearray(96)
            if self.connected:
                # Mark connected: HPD high
                status_bytes[0] = 1
            mem_write(ptr_val, bytes(status_bytes))
            self.transactions.append({
                'operation': 'ioctl',
                'cmd': cmd,
                'name': 'HDMI_IOCTL_GET_STATUS',
                'connected': self.connected,
                'returned': 0
            })
            return 0

        if cmd == HDMI_IOCTL_SET_POWER:
            self.power_state = ptr_val
            self.transactions.append({
                'operation': 'ioctl',
                'cmd': cmd,
                'name': 'HDMI_IOCTL_SET_POWER',
                'power_state': ptr_val,
                'returned': 0
            })
            return 0

        if cmd == HDMI_IOCTL_SET_TMDS:
            self.tmds_param = ptr_val
            self.transactions.append({
                'operation': 'ioctl',
                'cmd': cmd,
                'name': 'HDMI_IOCTL_SET_TMDS',
                'tmds_param': ptr_val,
                'returned': 0
            })
            return 0

        if cmd == HDMI_IOCTL_SET_RESO:
            # 20 bytes from ptr_val
            if ptr_val != 0 and ptr_val < self.address_limit:
                self.resolution = mem_read(ptr_val, 20)
            self.transactions.append({
                'operation': 'ioctl',
                'cmd': cmd,
                'name': 'HDMI_IOCTL_SET_RESO',
                'returned': 0
            })
            return 0

        if cmd == HDMI_IOCTL_SET_XVYCC:
            # 36 bytes from ptr_val
            if ptr_val != 0 and ptr_val < self.address_limit:
                self.xvycc_data = mem_read(ptr_val, 36)
            self.transactions.append({
                'operation': 'ioctl',
                'cmd': cmd,
                'name': 'HDMI_IOCTL_SET_XVYCC',
                'returned': 0
            })
            return 0

        if cmd == HDMI_IOCTL_SET_SRC_DEV:
            self.src_dev = ptr_val & 0xff
            self.transactions.append({
                'operation': 'ioctl',
                'cmd': cmd,
                'name': 'HDMI_IOCTL_SET_SRC_DEV',
                'src_dev': self.src_dev,
                'returned': 0
            })
            return 0

        if cmd == HDMI_IOCTL_SET_AUDIO:
            # 12 bytes from ptr_val
            if ptr_val != 0 and ptr_val < self.address_limit:
                self.audio_data = mem_read(ptr_val, 12)
            self.transactions.append({
                'operation': 'ioctl',
                'cmd': cmd,
                'name': 'HDMI_IOCTL_SET_AUDIO',
                'returned': 0
            })
            return 0

        if cmd == HDMI_IOCTL_SET_CONTENT:
            self.content_param = ptr_val
            self.transactions.append({
                'operation': 'ioctl',
                'cmd': cmd,
                'name': 'HDMI_IOCTL_SET_CONTENT',
                'content_param': ptr_val,
                'returned': 0
            })
            return 0

        if cmd in (HDMI_IOCTL_SET_HPD_1, HDMI_IOCTL_SET_HPD_2):
            self.transactions.append({
                'operation': 'ioctl',
                'cmd': cmd,
                'name': 'HDMI_IOCTL_SET_HPD',
                'returned': 0
            })
            return 0

        if cmd == HDMI_IOCTL_SET_DIMENSION:
            self.dimension_param = ptr_val
            self.transactions.append({
                'operation': 'ioctl',
                'cmd': cmd,
                'name': 'HDMI_IOCTL_SET_DIMENSION',
                'returned': 0
            })
            return 0

        if cmd == HDMI_IOCTL_SET_VSIF:
            self.vsif_param = ptr_val
            self.transactions.append({
                'operation': 'ioctl',
                'cmd': cmd,
                'name': 'HDMI_IOCTL_SET_VSIF',
                'returned': 0
            })
            return 0

        if cmd == HDMI_IOCTL_SET_COLORBAR:
            self.colorbar_enabled = bool(ptr_val)
            self.transactions.append({
                'operation': 'ioctl',
                'cmd': cmd,
                'name': 'HDMI_IOCTL_SET_COLORBAR',
                'returned': 0
            })
            return 0

        if cmd == HDMI_IOCTL_SET_FORCE_STOP:
            self.force_stop = ptr_val
            self.transactions.append({
                'operation': 'ioctl',
                'cmd': cmd,
                'name': 'HDMI_IOCTL_SET_FORCE_STOP',
                'returned': 0
            })
            return 0

        raise UnsupportedHdmi('unsupported_hdmi_ioctl_command', cmd=hex(cmd), arg=hex(arg))
