"""Sony CXD90045 MMC/SD and MemoryStick character driver contracts.

Derived from /usr/kmod/mmc_drv.ko, /usr/kmod/ms_drv.ko, /usr/lib/libInfraMediaCommon.so,
and live ILCE-6400 hardware telemetry (reports/a6400_hw_dump.txt lines 198-204, 292-320):
- Character device nodes registered in /proc/devices:
  - /dev/mmca-char (major 250, minor 0, hwid 0)
  - /dev/mmcb-char (major 250, minor 1, hwid 1)
  - /dev/mmcc-char (major 250, minor 2, hwid 2)
  - /dev/ms-char   (major 249, minor 0)
  - /dev/sata      (major 249, minor 2; no driver registered on ILCE-6400 -> open returns -ENXIO = -6)
- File operations in mmc_drv.ko:
  - mmcd_char_open  (0x28b4): returns 0.
  - mmcd_char_close (0x28c8): returns 0.
  - minor_to_hwid   (0x9ae4): maps minor 0 / 10..29 -> hwid 0, minor 1 / 30..42 -> hwid 1, minor 2 / 50..62 -> hwid 2.
  - mmcd_char_ioctl (0x5898):
    - 0x01: mount / detect card on hwid (4-byte status word)
    - 0x20120328: mmcd_blk_exit / unmount on hwid (4-byte status word)
    - 0x03: mmc_trc_get_area (8-byte struct [phys_addr, size])
    - 0x04: mmc_trc_set_area (12-byte struct [status, phys_addr, size]; requires (size & 0x3f) == 0 else status = -3)
    - 0x05: get card type byte (1-byte out: 0 = SD/MMCP, 3 = MMC, 4 = no card)
    - 0x06: get host info (12-byte struct [status, count_and_flags, 0])
    - 0xf0: do_mmc_suspend(0..3)
    - 0xf1: do_mmc_resume(0..3)
    - 0xf2: mmc_hw_check_port
    - 0xf3: mmc_hwconf_mmc_power_on / off (4-byte int)
    - 0xf4: mmc_hwconf_set_iodrv (16-byte struct)
    - 0xf5: mmc_hw_wrapper_set_reject / reject (4-byte struct)
    - 0xf6: 36-byte status struct
    - 0xf7: mmc_mmcp_lockcard_func (40-byte struct)
    - 0xf8: mmc_mmcp_protect_func (8-byte struct)
    - 0xf9: set speed mode (8-byte struct)
    - 0xfa: set UHS mode (8-byte struct)
    - 0xfb: set force mode (8-byte struct)
    - 0xfc: mmc_mmcp_cancel_format (4-byte struct)
    - 0xfd: mmc_mmcp_get_format_progress (8-byte struct)
- File operations in ms_drv.ko:
  - ms_char_open  (0x343c): returns 0.
  - ms_char_close (0x3450): returns 0.
  - ms_char_ioctl (0x356c):
    - 0x80047601: msdl_ioctl_reject (4-byte status struct)
    - 0x80047602: msdl_ioctl_mount (4-byte status struct)
    - 0x80047603: msdl_ioctl_unmount (4-byte status struct)
    - 0x80047604: msdl_ioctl_get_errlog (8-byte struct)
    - 0x80047664: msdl_ioctl_get_retry_log (8-byte struct)
    - 0xc0047665: msdl_ioctl_set_msclk_delay (8-byte struct)
    - 0x80047666: msdl_ioctl_get_format_progress (8-byte struct)
    - 0x80047667: msdl_ioctl_set_errlog_area (12-byte struct [status, phys_addr, size])
"""
import struct


class UnsupportedMmcChar(Exception):
    def __init__(self, reason, **details):
        super().__init__(reason)
        self.reason = reason
        self.details = {'reason': reason, **details}


MMC_CHAR_NODES = {
    '/dev/mmca-char': {'major': 250, 'minor': 0, 'hwid': 0, 'driver': 'mmc_drv'},
    '/dev/mmcb-char': {'major': 250, 'minor': 1, 'hwid': 1, 'driver': 'mmc_drv'},
    '/dev/mmcc-char': {'major': 250, 'minor': 2, 'hwid': 2, 'driver': 'mmc_drv'},
    '/dev/ms-char':   {'major': 249, 'minor': 0, 'hwid': 0, 'driver': 'ms_drv'},
}

MMC_CHAR_IOCTL_MOUNT = 0x01
MMC_CHAR_IOCTL_UNMOUNT = 0x20120328
MMC_CHAR_IOCTL_GET_TRC_AREA = 0x03
MMC_CHAR_IOCTL_SET_TRC_AREA = 0x04
MMC_CHAR_IOCTL_GET_CARD_TYPE = 0x05
MMC_CHAR_IOCTL_GET_HOST_INFO = 0x06
MMC_CHAR_IOCTL_SUSPEND = 0xf0
MMC_CHAR_IOCTL_RESUME = 0xf1
MMC_CHAR_IOCTL_CHECK_PORT = 0xf2
MMC_CHAR_IOCTL_SET_POWER = 0xf3
MMC_CHAR_IOCTL_SET_IODRV = 0xf4
MMC_CHAR_IOCTL_REJECT = 0xf5
MMC_CHAR_IOCTL_CMD_F6 = 0xf6
MMC_CHAR_IOCTL_LOCK_CARD = 0xf7
MMC_CHAR_IOCTL_PROTECT = 0xf8
MMC_CHAR_IOCTL_SET_SPEED_MODE = 0xf9
MMC_CHAR_IOCTL_SET_UHS_MODE = 0xfa
MMC_CHAR_IOCTL_SET_FORCE_MODE = 0xfb
MMC_CHAR_IOCTL_CANCEL_FORMAT = 0xfc
MMC_CHAR_IOCTL_GET_FORMAT_PROGRESS = 0xfd

MMC_CHAR_IOCTL_NAMES = {
    MMC_CHAR_IOCTL_MOUNT: 'MMC_CHAR_IOCTL_MOUNT',
    MMC_CHAR_IOCTL_UNMOUNT: 'MMC_CHAR_IOCTL_UNMOUNT',
    MMC_CHAR_IOCTL_GET_TRC_AREA: 'MMC_CHAR_IOCTL_GET_TRC_AREA',
    MMC_CHAR_IOCTL_SET_TRC_AREA: 'MMC_CHAR_IOCTL_SET_TRC_AREA',
    MMC_CHAR_IOCTL_GET_CARD_TYPE: 'MMC_CHAR_IOCTL_GET_CARD_TYPE',
    MMC_CHAR_IOCTL_GET_HOST_INFO: 'MMC_CHAR_IOCTL_GET_HOST_INFO',
    MMC_CHAR_IOCTL_SUSPEND: 'MMC_CHAR_IOCTL_SUSPEND',
    MMC_CHAR_IOCTL_RESUME: 'MMC_CHAR_IOCTL_RESUME',
    MMC_CHAR_IOCTL_CHECK_PORT: 'MMC_CHAR_IOCTL_CHECK_PORT',
    MMC_CHAR_IOCTL_SET_POWER: 'MMC_CHAR_IOCTL_SET_POWER',
    MMC_CHAR_IOCTL_SET_IODRV: 'MMC_CHAR_IOCTL_SET_IODRV',
    MMC_CHAR_IOCTL_REJECT: 'MMC_CHAR_IOCTL_REJECT',
    MMC_CHAR_IOCTL_CMD_F6: 'MMC_CHAR_IOCTL_CMD_F6',
    MMC_CHAR_IOCTL_LOCK_CARD: 'MMC_CHAR_IOCTL_LOCK_CARD',
    MMC_CHAR_IOCTL_PROTECT: 'MMC_CHAR_IOCTL_PROTECT',
    MMC_CHAR_IOCTL_SET_SPEED_MODE: 'MMC_CHAR_IOCTL_SET_SPEED_MODE',
    MMC_CHAR_IOCTL_SET_UHS_MODE: 'MMC_CHAR_IOCTL_SET_UHS_MODE',
    MMC_CHAR_IOCTL_SET_FORCE_MODE: 'MMC_CHAR_IOCTL_SET_FORCE_MODE',
    MMC_CHAR_IOCTL_CANCEL_FORMAT: 'MMC_CHAR_IOCTL_CANCEL_FORMAT',
    MMC_CHAR_IOCTL_GET_FORMAT_PROGRESS: 'MMC_CHAR_IOCTL_GET_FORMAT_PROGRESS',
}

MS_CHAR_IOCTL_REJECT = 0x80047601
MS_CHAR_IOCTL_MOUNT = 0x80047602
MS_CHAR_IOCTL_UNMOUNT = 0x80047603
MS_CHAR_IOCTL_GET_ERRLOG = 0x80047604
MS_CHAR_IOCTL_GET_RETRY_LOG = 0x80047664
MS_CHAR_IOCTL_SET_MSCLK_DELAY = 0xc0047665
MS_CHAR_IOCTL_GET_FORMAT_PROGRESS = 0x80047666
MS_CHAR_IOCTL_SET_ERRLOG_AREA = 0x80047667

MS_CHAR_IOCTL_NAMES = {
    MS_CHAR_IOCTL_REJECT: 'MS_CHAR_IOCTL_REJECT',
    MS_CHAR_IOCTL_MOUNT: 'MS_CHAR_IOCTL_MOUNT',
    MS_CHAR_IOCTL_UNMOUNT: 'MS_CHAR_IOCTL_UNMOUNT',
    MS_CHAR_IOCTL_GET_ERRLOG: 'MS_CHAR_IOCTL_GET_ERRLOG',
    MS_CHAR_IOCTL_GET_RETRY_LOG: 'MS_CHAR_IOCTL_GET_RETRY_LOG',
    MS_CHAR_IOCTL_SET_MSCLK_DELAY: 'MS_CHAR_IOCTL_SET_MSCLK_DELAY',
    MS_CHAR_IOCTL_GET_FORMAT_PROGRESS: 'MS_CHAR_IOCTL_GET_FORMAT_PROGRESS',
    MS_CHAR_IOCTL_SET_ERRLOG_AREA: 'MS_CHAR_IOCTL_SET_ERRLOG_AREA',
}


def minor_to_hwid(minor: int) -> int:
    """Matches minor_to_hwid (0x9ae4 in mmc_drv.ko)."""
    if minor <= 0x2a:
        if minor >= 0x1e or minor == 1:
            return 1
        if minor == 2:
            return 2
        return 0
    if (minor - 0x32) <= 0x0c:
        return 2
    return 0


class GuestMmcChar:
    """Tracks /dev/mmca-char, /dev/mmcb-char, /dev/mmcc-char, and /dev/ms-char state and ioctls."""

    major = 250
    minor = 0

    def __init__(self, card_present: bool = True):
        self.card_present = card_present
        self.next_owner_id = 1
        self.open_handles = {}
        self.transactions = []
        self.trc_areas = {
            0: {'phys_addr': 0, 'size': 0},
            1: {'phys_addr': 0, 'size': 0},
            2: {'phys_addr': 0, 'size': 0},
        }
        self.ms_errlog_area = {'phys_addr': 0, 'size': 0}
        self.mounted = {0: False, 1: False, 2: False}
        self.power_state = {0: 0, 1: 0, 2: 0}
        self.uhs_mode = {0: 0, 1: 0, 2: 0}
        self.force_mode = {0: 0, 1: 0, 2: 0}
        self.speed_mode = {0: (0, 0, 0), 1: (0, 0, 0), 2: (0, 0, 0)}

    def open(self, flags, pid, tgid, path='/dev/mmca-char'):
        if path not in MMC_CHAR_NODES:
            raise UnsupportedMmcChar('unsupported_device_path', path=path, flags=flags)
        acc_mode = flags & 3
        if acc_mode not in (0, 1, 2):
            raise UnsupportedMmcChar('unsupported_open_flags', path=path, flags=flags)
        node = MMC_CHAR_NODES[path]
        owner_id = self.next_owner_id
        self.next_owner_id += 1
        handle = {
            'owner_id': owner_id,
            'path': path,
            'major': node['major'],
            'minor': node['minor'],
            'hwid': node['hwid'],
            'driver': node['driver'],
            'flags': flags,
            'pid': pid,
            'tgid': tgid,
        }
        self.open_handles[owner_id] = handle
        self.transactions.append({
            'op': 'open',
            'owner_id': owner_id,
            'path': path,
            'major': node['major'],
            'minor': node['minor'],
            'hwid': node['hwid'],
            'flags': flags,
            'pid': pid,
            'tgid': tgid,
        })
        return handle

    def close(self, owner_id):
        if owner_id not in self.open_handles:
            raise UnsupportedMmcChar('close_on_unknown_owner', owner_id=owner_id)
        handle = self.open_handles.pop(owner_id)
        self.transactions.append({
            'op': 'close',
            'owner_id': owner_id,
            'path': handle['path'],
        })
        return 0

    def ioctl(self, owner_id, cmd, arg, mem_reader, mem_writer):
        """Dispatches mmcd_char_ioctl (0x5898 in mmc_drv.ko) or ms_char_ioctl (0x356c in ms_drv.ko)."""
        if owner_id not in self.open_handles:
            raise UnsupportedMmcChar('ioctl_on_unknown_owner', owner_id=owner_id, cmd=cmd, arg=arg)
        handle = self.open_handles[owner_id]
        if handle['driver'] == 'ms_drv':
            return self._ms_ioctl(handle, cmd, arg, mem_reader, mem_writer)
        return self._mmc_ioctl(handle, cmd, arg, mem_reader, mem_writer)

    def _mmc_ioctl(self, handle, cmd, arg, mem_reader, mem_writer):
        owner_id = handle['owner_id']
        hwid = handle['hwid']
        if cmd not in MMC_CHAR_IOCTL_NAMES:
            raise UnsupportedMmcChar(
                'unsupported_ioctl_command',
                owner_id=owner_id,
                path=handle['path'],
                hwid=hwid,
                cmd=cmd,
                arg=arg,
            )

        if cmd in (MMC_CHAR_IOCTL_SUSPEND, MMC_CHAR_IOCTL_RESUME, MMC_CHAR_IOCTL_CHECK_PORT):
            self.transactions.append({
                'op': 'ioctl',
                'owner_id': owner_id,
                'path': handle['path'],
                'hwid': hwid,
                'cmd': cmd,
                'cmd_name': MMC_CHAR_IOCTL_NAMES[cmd],
                'arg': arg,
            })
            return 0

        if arg == 0:
            raise UnsupportedMmcChar('null_ioctl_arg', owner_id=owner_id, path=handle['path'], cmd=cmd)

        extra = {}
        if cmd == MMC_CHAR_IOCTL_SET_TRC_AREA:
            raw = mem_reader(arg, 12)
            _status, phys_addr, size = struct.unpack('<III', raw)
            if (size & 0x3f) != 0:
                status_out = 0xfffffffd  # -3 per 0x6310 in mmcd_char_ioctl
            else:
                self.trc_areas[hwid] = {'phys_addr': phys_addr, 'size': size}
                status_out = 0
            mem_writer(arg, struct.pack('<III', status_out, phys_addr, size))
            extra = {'phys_addr': phys_addr, 'size': size, 'status_out': status_out}
        elif cmd == MMC_CHAR_IOCTL_GET_TRC_AREA:
            _raw = mem_reader(arg, 8)
            area = self.trc_areas.get(hwid, {'phys_addr': 0, 'size': 0})
            mem_writer(arg, struct.pack('<II', area['phys_addr'], area['size']))
            extra = {'phys_addr': area['phys_addr'], 'size': area['size']}
        elif cmd == MMC_CHAR_IOCTL_MOUNT:
            _raw = mem_reader(arg, 4)
            if hwid == 0 and self.card_present:
                self.mounted[hwid] = True
                status_out = 0
            else:
                self.mounted[hwid] = False
                status_out = 0xfffffff7  # -9 (no card)
            mem_writer(arg, struct.pack('<I', status_out))
            extra = {'status_out': status_out}
        elif cmd == MMC_CHAR_IOCTL_UNMOUNT:
            _raw = mem_reader(arg, 4)
            self.mounted[hwid] = False
            mem_writer(arg, struct.pack('<I', 0))
            extra = {'status_out': 0}
        elif cmd == MMC_CHAR_IOCTL_GET_CARD_TYPE:
            _raw = mem_reader(arg, 1)
            card_type_byte = 0 if (hwid == 0 and self.card_present) else 4
            mem_writer(arg, bytes([card_type_byte]))
            extra = {'card_type_byte': card_type_byte}
        elif cmd == MMC_CHAR_IOCTL_GET_HOST_INFO:
            _raw = mem_reader(arg, 12)
            card_count = 1 if (hwid == 0 and self.card_present) else 0
            mem_writer(arg, struct.pack('<III', 0, card_count, 0))
            extra = {'card_count': card_count}
        elif cmd == MMC_CHAR_IOCTL_SET_POWER:
            raw = mem_reader(arg, 4)
            val = struct.unpack('<I', raw)[0]
            self.power_state[hwid] = val
            extra = {'power_state': val}
        elif cmd == MMC_CHAR_IOCTL_SET_IODRV:
            raw = bytearray(mem_reader(arg, 16))
            struct.pack_into('<I', raw, 0, 0)
            mem_writer(arg, bytes(raw))
        elif cmd in (MMC_CHAR_IOCTL_REJECT, MMC_CHAR_IOCTL_CANCEL_FORMAT):
            _raw = mem_reader(arg, 4)
            mem_writer(arg, struct.pack('<I', 0))
        elif cmd == MMC_CHAR_IOCTL_CMD_F6:
            raw = bytearray(mem_reader(arg, 0x24))
            struct.pack_into('<I', raw, 0, 0)
            mem_writer(arg, bytes(raw))
        elif cmd == MMC_CHAR_IOCTL_LOCK_CARD:
            raw = bytearray(mem_reader(arg, 0x28))
            mode = raw[4]
            status_out = 0 if mode in (0, 1, 2) else 0xfffffffd
            struct.pack_into('<I', raw, 0, status_out)
            mem_writer(arg, bytes(raw))
            extra = {'mode': mode, 'status_out': status_out}
        elif cmd == MMC_CHAR_IOCTL_PROTECT:
            raw = bytearray(mem_reader(arg, 8))
            mode = raw[4]
            status_out = 0 if mode in (0, 1, 2) else 0xfffffffd
            struct.pack_into('<I', raw, 0, status_out)
            mem_writer(arg, bytes(raw))
            extra = {'mode': mode, 'status_out': status_out}
        elif cmd == MMC_CHAR_IOCTL_SET_SPEED_MODE:
            raw = bytearray(mem_reader(arg, 8))
            m0, m1, m2 = raw[4], raw[5], raw[6]
            if m0 in (1, 2, 4) and m1 <= 1:
                self.speed_mode[hwid] = (m0, m1, m2)
                status_out = 0
            elif m0 == 3:
                self.speed_mode[hwid] = (3, 1, m0 - 1)
                status_out = 0
            else:
                status_out = 0xfffffffd
            struct.pack_into('<I', raw, 0, status_out)
            mem_writer(arg, bytes(raw))
            extra = {'speed_mode': (m0, m1, m2), 'status_out': status_out}
        elif cmd == MMC_CHAR_IOCTL_SET_UHS_MODE:
            raw = bytearray(mem_reader(arg, 8))
            self.uhs_mode[hwid] = raw[4]
            struct.pack_into('<I', raw, 0, 0)
            mem_writer(arg, bytes(raw))
            extra = {'uhs_mode': raw[4]}
        elif cmd == MMC_CHAR_IOCTL_SET_FORCE_MODE:
            raw = bytearray(mem_reader(arg, 8))
            self.force_mode[hwid] = raw[4]
            struct.pack_into('<I', raw, 0, 0)
            mem_writer(arg, bytes(raw))
            extra = {'force_mode': raw[4]}
        elif cmd == MMC_CHAR_IOCTL_GET_FORMAT_PROGRESS:
            _raw = mem_reader(arg, 8)
            mem_writer(arg, struct.pack('<II', 0, 0))

        self.transactions.append({
            'op': 'ioctl',
            'owner_id': owner_id,
            'path': handle['path'],
            'hwid': hwid,
            'cmd': cmd,
            'cmd_name': MMC_CHAR_IOCTL_NAMES[cmd],
            'arg': arg,
            **extra,
        })
        return 0

    def _ms_ioctl(self, handle, cmd, arg, mem_reader, mem_writer):
        owner_id = handle['owner_id']
        if cmd not in MS_CHAR_IOCTL_NAMES:
            raise UnsupportedMmcChar(
                'unsupported_ms_ioctl_command',
                owner_id=owner_id,
                path=handle['path'],
                cmd=cmd,
                arg=arg,
            )
        if arg == 0:
            raise UnsupportedMmcChar('null_ioctl_arg', owner_id=owner_id, path=handle['path'], cmd=cmd)

        extra = {}
        if cmd == MS_CHAR_IOCTL_SET_ERRLOG_AREA:
            raw = mem_reader(arg, 12)
            _status, phys_addr, size = struct.unpack('<III', raw)
            self.ms_errlog_area = {'phys_addr': phys_addr, 'size': size}
            mem_writer(arg, struct.pack('<I', 0))
            extra = {'phys_addr': phys_addr, 'size': size, 'status_out': 0}
        elif cmd == MS_CHAR_IOCTL_MOUNT:
            _raw = mem_reader(arg, 4)
            mem_writer(arg, struct.pack('<I', 0xfffffff7))  # -9 (no MemoryStick card)
            extra = {'status_out': 0xfffffff7}
        elif cmd in (MS_CHAR_IOCTL_REJECT, MS_CHAR_IOCTL_UNMOUNT):
            _raw = mem_reader(arg, 4)
            mem_writer(arg, struct.pack('<I', 0))
        elif cmd in (
            MS_CHAR_IOCTL_GET_ERRLOG,
            MS_CHAR_IOCTL_GET_RETRY_LOG,
            MS_CHAR_IOCTL_SET_MSCLK_DELAY,
            MS_CHAR_IOCTL_GET_FORMAT_PROGRESS,
        ):
            raw = bytearray(mem_reader(arg, 8))
            struct.pack_into('<I', raw, 0, 0)
            mem_writer(arg, bytes(raw))

        self.transactions.append({
            'op': 'ioctl',
            'owner_id': owner_id,
            'path': handle['path'],
            'cmd': cmd,
            'cmd_name': MS_CHAR_IOCTL_NAMES[cmd],
            'arg': arg,
            **extra,
        })
        return 0
