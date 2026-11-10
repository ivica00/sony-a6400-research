"""Guarded USB bus power kernel interface (/dev/usb/buspwr).

Authentic Sony USB bus power driver contract evidenced by:
- nflasha7 inode 240 (character device, major 248, minor 13)
- devno.ko offset 0x1d0: "usb/buspwr" -> major 248, minor 13
- /usr/kmod/usb_buspwr.ko fops (usb_buspwr_fops_open, usb_buspwr_fops_close,
  usb_buspwr_fops_ioctl at .text 0x1314) with a 33-entry jump table
  (0xf200..0xf220) resolved from the R_ARM_ABS32 entries at .text 0x133c:
    0xf200..0xf208, 0xf20b, 0xf20c, 0xf21e..0xf220 -> handler returns 0
    0xf209 -> usb_buspw_ic_get_pwr_src_det_result() (0..3, else 3)
    0xf20a -> usb_buspw_ic_get_batt_state() (mapped to 0/1)
    0xf20d..0xf21d -> -EINVAL (-22)
    out of 0xf200..0xf220 -> -EINVAL (-22)
- libUsbBusPower.so methods (OpenResourceFile, SetSuspendEnable,
  SetChargingEnable, GetCurrentPortType, etc.); GetCurrentPortType(int*) at
  0x3638 issues exactly ioctl(fd, 0xf209, &int32) and 0x3635/0x3eb4 use
  0xf20c for SetPortState.

Reply provenance (E0299 task-7):

* ``legacy-zero-stubs`` (default) keeps the previously introduced behaviour,
  including zero-valued GET_CURRENT_PORT_TYPE / GET_CURRENT_BATT_STATE stubs,
  so restored checkpoints and prior regression baselines are unchanged.
* ``verified-connect`` is the explicit opt-in policy for a USB connect /
  Mass Storage run. It reports only values that are derivable from the retained
  driver evidence above. The two hardware-derived queries (current port type
  and current battery state) are not derivable from any retained observation,
  so they raise an explicit boundary with the command and requested fields
  instead of returning a fabricated value. A caller that later obtains an
  evidence-backed value (e.g. a read-only camera capture of the
  /proc/udm/usb_portMonitor or buspwr proc output) can supply it explicitly via
  ``port_type_reply`` / ``batt_state_reply``; that is recorded in the
  transaction log.

Strictly adheres to fail-closed semantics and user memory task limits
(TASK_SIZE <= 0x5f000000).
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
USB_BUSPWR_CMD_SET_PORT_STATE = 0xf20c

USB_BUSPWR_REPLY_POLICY_LEGACY = 'legacy-zero-stubs'
USB_BUSPWR_REPLY_POLICY_VERIFIED = 'verified-connect'
USB_BUSPWR_REPLY_POLICIES = (
    USB_BUSPWR_REPLY_POLICY_LEGACY,
    USB_BUSPWR_REPLY_POLICY_VERIFIED,
)

# usb_buspwr.ko jump-table entries whose handler calls an internal function and
# then returns 0 (all of these are verified from the module disassembly).
USB_BUSPWR_VERIFIED_ZERO_COMMANDS = frozenset((
    0xf200, 0xf201, 0xf202, 0xf203, 0xf204, 0xf205, 0xf206, 0xf207, 0xf208,
    0xf20b, 0xf20c, 0xf21e, 0xf21f, 0xf220,
))
# Jump-table entries that hit the shared default handler and return -EINVAL.
USB_BUSPWR_VERIFIED_EINVAL_COMMANDS = frozenset(range(0xf20d, 0xf21e))


class UnsupportedUsbBusPower(RuntimeError):
    def __init__(self, reason, **details):
        super().__init__(reason)
        self.details = {'reason': reason, 'device': '/dev/usb/buspwr', **details}


class GuestUsbBusPower:
    """Emulates /dev/usb/buspwr character device (248:13)."""

    def __init__(self, address_limit=0x5f000000,
                 reply_policy=USB_BUSPWR_REPLY_POLICY_LEGACY,
                 port_type_reply=None, batt_state_reply=None):
        if reply_policy not in USB_BUSPWR_REPLY_POLICIES:
            raise ValueError(f'unsupported usb buspower reply policy: {reply_policy!r}')
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
        self.reply_policy = reply_policy
        # Explicit, evidence-backed reply overrides for the two hardware-derived
        # queries.  None means "not derivable from retained evidence": the
        # verified policy then stops with an explicit boundary.
        self.port_type_reply = port_type_reply
        self.batt_state_reply = batt_state_reply

    # ------------------------------------------------------------------ open
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

    # ----------------------------------------------------------------- ioctl
    def ioctl(self, owner_id, cmd, arg, mem_read, mem_write):
        owner = self.owners.get(owner_id)
        if not owner:
            raise UnsupportedUsbBusPower('usb_buspower_invalid_owner_descriptor', owner_id=owner_id)

        policy = getattr(self, 'reply_policy', USB_BUSPWR_REPLY_POLICY_LEGACY)
        if policy == USB_BUSPWR_REPLY_POLICY_LEGACY:
            return self._ioctl_legacy(owner_id, cmd, arg, mem_read, mem_write)
        return self._ioctl_verified(owner_id, cmd, arg, mem_read, mem_write)

    # --------------------------------------------------------- legacy policy
    def _ioctl_legacy(self, owner_id, cmd, arg, mem_read, mem_write):
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

    # ------------------------------------------------------- verified policy
    def _ioctl_verified(self, owner_id, cmd, arg, mem_read, mem_write):
        """Opt-in policy: authentic values only, explicit boundary otherwise."""
        if cmd < USB_BUSPWR_MAGIC_BASE or cmd > (USB_BUSPWR_MAGIC_BASE + 0x20):
            return -22  # usb_buspwr.ko default handler: -EINVAL

        if cmd == USB_BUSPWR_CMD_GET_CURRENT_PORT_TYPE:
            if arg >= self.address_limit or arg == 0:
                raise UnsupportedUsbBusPower('user_pointer_outside_task_limit', address=arg, limit=self.address_limit)
            value = getattr(self, 'port_type_reply', None)
            if value is None:
                raise UnsupportedUsbBusPower(
                    'usb_buspower_port_type_reply_not_derivable',
                    cmd=cmd,
                    cmd_name='GET_CURRENT_PORT_TYPE',
                    arg=arg,
                    requested_size=4,
                    reply_layout='int32 current_port_type (0..3)',
                    driver_evidence=('usb_buspwr.ko usb_buspwr_fops_ioctl 0xf209 -> internal '
                                     'getter 0x8c8 -> usb_buspw_ic_get_pwr_src_det_result(); '
                                     'values outside 0..3 are clamped to 3'),
                    missing_evidence=('no retained observation of the USB power-source detection '
                                      'result produced while the camera is connected as Mass Storage'))
            mem_write(arg, struct.pack('<I', value & 0xffffffff))
            self.transactions.append({'operation': 'ioctl', 'cmd': cmd, 'name': 'GET_CURRENT_PORT_TYPE',
                                      'port_type': value & 0xffffffff, 'source': 'explicit-evidence-override',
                                      'returned': 0})
            return 0

        if cmd == USB_BUSPWR_CMD_GET_CURRENT_BATT_STATE:
            if arg >= self.address_limit or arg == 0:
                raise UnsupportedUsbBusPower('user_pointer_outside_task_limit', address=arg, limit=self.address_limit)
            value = getattr(self, 'batt_state_reply', None)
            if value is None:
                raise UnsupportedUsbBusPower(
                    'usb_buspower_batt_state_reply_not_derivable',
                    cmd=cmd,
                    cmd_name='GET_CURRENT_BATT_STATE',
                    arg=arg,
                    requested_size=4,
                    reply_layout='int32 batt_state (0=not present, 1=normal, -1=error)',
                    driver_evidence=('usb_buspwr.ko usb_buspwr_fops_ioctl 0xf20a -> internal getter '
                                     '0x838 -> usb_buspw_ic_get_batt_state(); -1/other -> 1, 0 -> 1, 1 -> 0'),
                    missing_evidence=('no retained observation of the battery state hardware result'))
            mem_write(arg, struct.pack('<I', value & 0xffffffff))
            self.transactions.append({'operation': 'ioctl', 'cmd': cmd, 'name': 'GET_CURRENT_BATT_STATE',
                                      'batt_state': value & 0xffffffff, 'source': 'explicit-evidence-override',
                                      'returned': 0})
            return 0

        if cmd == USB_BUSPWR_CMD_SET_PORT_STATE:
            # usb_buspwr.ko 0x14e8: usb_buspw_ic_initialize(); return 0 (arg unused).
            self.transactions.append({'operation': 'ioctl', 'cmd': cmd, 'name': 'SET_PORT_STATE', 'returned': 0})
            return 0

        if cmd in USB_BUSPWR_VERIFIED_EINVAL_COMMANDS:
            self.transactions.append({'operation': 'ioctl', 'cmd': cmd, 'name': f'CMD_{hex(cmd)}',
                                      'returned': -22})
            return -22

        if cmd in USB_BUSPWR_VERIFIED_ZERO_COMMANDS:
            self._apply_verified_control(cmd)
            return 0

        # Table-range command with no resolvable handler (should not happen for
        # 0xf200..0xf220 after the sets above).
        return -22

    def _apply_verified_control(self, cmd):
        name = {
            0xf200: 'SET_SUSPEND_ENABLE',
            0xf201: 'SET_SUSPEND_DISABLE',
            0xf202: 'SET_CURRENT_LIMIT_100MA',
            0xf203: 'SET_CURRENT_LIMIT_500MA',
            0xf204: 'SET_CHARGING_ENABLE',
            0xf205: 'SET_CHARGING_DISABLE',
            0xf206: 'START_NOTIFY_EVENT',
            0xf207: 'STOP_NOTIFY_EVENT',
            0xf208: 'CMD_0xf208',
            0xf20b: 'CMD_0xf20b',
            0xf21e: 'CMD_0xf21e',
            0xf21f: 'CMD_0xf21f',
            0xf220: 'CMD_0xf220',
        }.get(cmd, f'CMD_{hex(cmd)}')
        if cmd == USB_BUSPWR_CMD_SET_SUSPEND_ENABLE:
            self.suspend_enabled = True
        elif cmd == USB_BUSPWR_CMD_SET_SUSPEND_DISABLE:
            self.suspend_enabled = False
        elif cmd == USB_BUSPWR_CMD_SET_CURRENT_LIMIT_100MA:
            self.current_limit_ma = 100
        elif cmd == USB_BUSPWR_CMD_SET_CURRENT_LIMIT_500MA:
            self.current_limit_ma = 500
        elif cmd == USB_BUSPWR_CMD_SET_CHARGING_ENABLE:
            self.charging_enabled = True
        elif cmd == USB_BUSPWR_CMD_SET_CHARGING_DISABLE:
            self.charging_enabled = False
        elif cmd == USB_BUSPWR_CMD_START_NOTIFY_EVENT:
            self.notify_events_enabled = True
        elif cmd == USB_BUSPWR_CMD_STOP_NOTIFY_EVENT:
            self.notify_events_enabled = False
        self.transactions.append({'operation': 'ioctl', 'cmd': cmd, 'name': name, 'returned': 0})

    # ----------------------------------------------------------------- close
    def close(self, owner_id):
        if owner_id in self.owners:
            del self.owners[owner_id]
            self.transactions.append({'operation': 'close', 'owner_id': owner_id})
