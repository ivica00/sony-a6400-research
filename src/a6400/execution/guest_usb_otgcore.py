"""Guarded USB OTG core kernel interface (/dev/usb/otgcore).

Authentic Sony USB OTG core driver contract evidenced by:
- vmlinux.bin udif_devnodes table at offset 0x3d2ba8 (VA 0x604daba8):
  name: "usb/otgcore", dev_t: MKDEV(242, 2) -> Major 242, Minor 2
- vmlinux.bin usb_otgcore_ioctl (kallsyms 0x602b7468, base 0x60108000):
  a 32-bit _IOC command dispatcher built as a binary search.  The literal pool
  at 0x602b8188..0x602b81b0 contains the exact command words:
    0x4024e301 SET_PORT_DESC  (copy 36 bytes from user; driver state valid flag)
    0x0000e302 RESET          (clear port-descriptor valid flag; return 0)
    0x0000e303 STOP           (transition_to_stop; return its result)
    0x0000e304 START          (transition_to_idle; return its result)
    0x0000e305                (driver-ops callback +0x34; return its result)
    0x0000e306                (driver-ops callback +0x34/+0x24 sequence)
    0x0000e308 / 0xe309 / 0xe30a / 0xe30e (driver-ops callback sequences)
    0x0000e312                (no-op; returns 0)
    0x4001e30c SET_MODE       (copy 1 byte; 1|2; driver-ops callback +0x3c)
    0x4001e30d SET_FLAG       (copy 1 byte; driver-ops callback +0x44; returns 0)
    0x4001e30f SET_SELECT_PORT(copy 4 bytes; sets global+8 selected port)
    0x4010e313 SET_PARAM      (copy 16 bytes to global+0x4c; return 0)
    0x4040e311 SET_CONFIG     (copy 64 bytes; global+4 = config entry count; return 0)
    0x8001e30b GET_STATUS     (1-byte driver speed -> 1..3; not derivable)
    0x8008e310 GET_INFO       (8-byte reply {global+4, global+8})
    unknown command           -> -ENOTTY (-25)
- libInfraUsbCmn.so consumer (authentic library bytes):
    openSvc 0xa7e4: open("/dev/usb/otgcore", O_RDWR), regist_port_desc,
      usb_event_enable, SET_PORT_DESC (0xa892, 36-byte runtime descriptor),
      set_phy_parameter -> SET_PARAM, create_serialNumber, START (0xa8b0)
    createHost 0xb3a5 / createGadget 0xbbc4: SET_MODE, 0xe305, SET_MODE,
      DescriptorMaintainer + getSelectPort -> GET_INFO (0x97ed), 0xe306/0xe307
    closeSvc 0xa978: STOP (0xa99c), RESET (0xa9be), unregist_port_desc ->
      0xe312 (0xa6f6), close
- The retained 312M emulator checkpoint (boot-260m-e0298.ckpt) service history
  for this device is exactly: open, SET_PORT_DESC (36 bytes), SET_PARAM,
  START (0xe304) -- no SET_MODE / GET_STATUS / GET_INFO / SET_CONFIG yet.

Reply provenance (E0299 task-7):

* ``legacy-zero-stubs`` (default) keeps the previously introduced behaviour
  byte-for-byte, including the zero-valued GET_STATUS / GET_INFO stubs, so
  restored checkpoints and earlier regression baselines are unchanged.
* ``verified-connect`` is the explicit opt-in policy for a USB connect /
  Mass Storage run. Verified replies:
    - SET_CONFIG/SET_PARAM/SET_FLAG/SET_PORT_DESC/SET_SELECT_PORT return 0 as
      the pinned kernel handlers do; the app-supplied payload bytes are
      retained verbatim (they are never invented host-side).
    - GET_INFO returns 8 bytes derived from kernel global state that only the
      application itself can write plus the kernel's zero-initialised BSS:
      field0 = ConfigDescriptor entry count from SET_CONFIG byte 0 (0 until
      SET_CONFIG; >2 reproduces the kernel's -EFAULT), field1 = selected port
      from SET_SELECT_PORT (0 until a selection; BSS zero).  The kernel global
      struct at 0x6051b0e4 lies past the end of the 0x3e5880-byte image, and
      usb_otgcore_module_init 0x604a561c only stores the driver pointer at
      global+0, so global+4/+8 are zero until those application calls.
    - START/STOP/RESET (0xe302/0xe303/0xe304) keep their reply 0 on the strength
      of the retained E0072/E0298 behavioural evidence (the app checked the
      result and advanced to its blocked state; the 312M checkpoint is
      consistent), not on a decoded transition return.
  Non-derivable replies raise an explicit boundary with the command and the
  requested reply fields instead of fabricating success:
    - GET_STATUS speed byte (driver ops callback +0x40; hardware/UDC state),
    - SET_MODE (driver ops callback +0x3c result),
    - 0xe305/0xe306/0xe308/0xe309/0xe30a/0xe30e driver-ops callback results,
    - SET_SELECT_PORT with a non-zero port index (needs the hardware port
      count in driver byte+0x2c).

Strict task limits: all user pointers checked against address_limit
(TASK_SIZE <= 0x5f000000).
"""
import struct

USB_OTGCORE_IOCTL_SET_PORT_DESC = 0x4024e301  # _IOW(0xe3, 1, 36)
USB_OTGCORE_IOCTL_RESET = 0x0000e302          # _IO(0xe3, 2)
USB_OTGCORE_IOCTL_STOP = 0x0000e303           # _IO(0xe3, 3)
USB_OTGCORE_IOCTL_START = 0x0000e304          # _IO(0xe3, 4)
USB_OTGCORE_IOCTL_CMD_0XE305 = 0x0000e305     # _IO(0xe3, 5)
USB_OTGCORE_IOCTL_CMD_0XE306 = 0x0000e306     # _IO(0xe3, 6)
USB_OTGCORE_IOCTL_CMD_0XE308 = 0x0000e308     # _IO(0xe3, 8)
USB_OTGCORE_IOCTL_CMD_0XE309 = 0x0000e309     # _IO(0xe3, 9)
USB_OTGCORE_IOCTL_CMD_0XE30A = 0x0000e30a     # _IO(0xe3, 0x0a)
USB_OTGCORE_IOCTL_GET_STATUS = 0x8001e30b     # _IOR(0xe3, 0x0b, 1)
USB_OTGCORE_IOCTL_SET_MODE = 0x4001e30c       # _IOW(0xe3, 0x0c, 1)
USB_OTGCORE_IOCTL_SET_FLAG = 0x4001e30d       # _IOW(0xe3, 0x0d, 1)
USB_OTGCORE_IOCTL_CMD_0XE30E = 0x0000e30e     # _IO(0xe3, 0x0e)
USB_OTGCORE_IOCTL_SET_SELECT_PORT = 0x4001e30f  # _IOW(0xe3, 0x0f, 4)
USB_OTGCORE_IOCTL_GET_INFO = 0x8008e310       # _IOR(0xe3, 0x10, 8)
USB_OTGCORE_IOCTL_SET_CONFIG = 0x4040e311     # _IOW(0xe3, 0x11, 64)
USB_OTGCORE_IOCTL_CMD_0XE312 = 0x0000e312     # _IO(0xe3, 0x12), no-op success
USB_OTGCORE_IOCTL_SET_PARAM = 0x4010e313      # _IOW(0xe3, 0x13, 16)

USB_OTGCORE_REPLY_POLICY_LEGACY = 'legacy-zero-stubs'
USB_OTGCORE_REPLY_POLICY_VERIFIED = 'verified-connect'
USB_OTGCORE_REPLY_POLICIES = (
    USB_OTGCORE_REPLY_POLICY_LEGACY,
    USB_OTGCORE_REPLY_POLICY_VERIFIED,
)

# Plain _IO(0xe3, n) commands whose pinned handler result depends on a
# driver-ops callback (hardware/UDC state) rather than on application input.
USB_OTGCORE_VERIFIED_CALLBACK_BOUNDARY_COMMANDS = {
    USB_OTGCORE_IOCTL_CMD_0XE305: '0xe305 (driver-ops callback +0x34)',
    USB_OTGCORE_IOCTL_CMD_0XE306: '0xe306 (driver-ops callback sequence +0x34/+0x24)',
    USB_OTGCORE_IOCTL_CMD_0XE308: '0xe308 (driver-ops callback sequence)',
    USB_OTGCORE_IOCTL_CMD_0XE309: '0xe309 (driver-ops callback sequence)',
    USB_OTGCORE_IOCTL_CMD_0XE30A: '0xe30a (driver-ops callback +0x34)',
    USB_OTGCORE_IOCTL_CMD_0XE30E: '0xe30e (driver-ops callback +0x34/+0x38)',
}


class UnsupportedUsbOtgCore(RuntimeError):
    def __init__(self, reason, **details):
        super().__init__(reason)
        self.details = {'reason': reason, 'device': '/dev/usb/otgcore', **details}


class GuestUsbOtgCore:
    """Emulates /dev/usb/otgcore character device (242:2)."""

    def __init__(self, address_limit=0x5f000000,
                 reply_policy=USB_OTGCORE_REPLY_POLICY_LEGACY):
        if reply_policy not in USB_OTGCORE_REPLY_POLICIES:
            raise ValueError(f'unsupported usb otgcore reply policy: {reply_policy!r}')
        self.address_limit = address_limit
        self.major = 242
        self.minor = 2
        self.owners = {}
        self.started = False
        self.port_desc = None
        self.config = None
        self.transactions = []
        self.reply_policy = reply_policy
        # Kernel-state mirrors needed by the verified GET_INFO derivation.
        self.config_count = 0   # kernel global+4, written by SET_CONFIG byte 0
        self.selected_port = 0  # kernel global+8, written by SET_SELECT_PORT
        self.param = None       # kernel global+0x4c, written by SET_PARAM
        self.flag = None        # kernel driver+0x2d, written by SET_FLAG

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
            raise UnsupportedUsbOtgCore('usb_otgcore_invalid_owner_descriptor', owner_id=owner_id)

        policy = getattr(self, 'reply_policy', USB_OTGCORE_REPLY_POLICY_LEGACY)
        if policy == USB_OTGCORE_REPLY_POLICY_LEGACY:
            return self._ioctl_legacy(owner_id, cmd, arg, mem_read, mem_write)
        return self._ioctl_verified(owner_id, cmd, arg, mem_read, mem_write)

    # ----------------------------------------------------------- shared rules
    def _check_user_pointer(self, arg):
        if arg >= self.address_limit or arg == 0:
            raise UnsupportedUsbOtgCore('user_pointer_outside_task_limit',
                                        address=arg, limit=self.address_limit)

    # --------------------------------------------------------- legacy policy
    def _ioctl_legacy(self, owner_id, cmd, arg, mem_read, mem_write):
        if cmd == USB_OTGCORE_IOCTL_SET_PORT_DESC:
            self._check_user_pointer(arg)
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
            self._check_user_pointer(arg)
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
            self._check_user_pointer(arg)
            mem_write(arg, b'\x00')
            self.transactions.append({
                'operation': 'ioctl',
                'cmd': cmd,
                'name': 'USB_OTGCORE_IOCTL_GET_STATUS',
                'returned': 0
            })
            return 0

        if cmd == USB_OTGCORE_IOCTL_GET_INFO:
            self._check_user_pointer(arg)
            mem_write(arg, b'\x00' * 8)
            self.transactions.append({
                'operation': 'ioctl',
                'cmd': cmd,
                'name': 'USB_OTGCORE_IOCTL_GET_INFO',
                'returned': 0
            })
            return 0

        if cmd == USB_OTGCORE_IOCTL_SET_MODE:
            self._check_user_pointer(arg)
            raw = mem_read(arg, 1)
            self.transactions.append({
                'operation': 'ioctl',
                'cmd': cmd,
                'name': 'USB_OTGCORE_IOCTL_SET_MODE',
                'returned': 0
            })
            return 0

        if cmd == USB_OTGCORE_IOCTL_SET_FLAG:
            self._check_user_pointer(arg)
            raw = mem_read(arg, 1)
            self.transactions.append({
                'operation': 'ioctl',
                'cmd': cmd,
                'name': 'USB_OTGCORE_IOCTL_SET_FLAG',
                'returned': 0
            })
            return 0

        if cmd == USB_OTGCORE_IOCTL_SET_PARAM:
            self._check_user_pointer(arg)
            raw = mem_read(arg, 16)
            self.transactions.append({
                'operation': 'ioctl',
                'cmd': cmd,
                'name': 'USB_OTGCORE_IOCTL_SET_PARAM',
                'returned': 0
            })
            return 0

        return -22  # -EINVAL

    # ------------------------------------------------------- verified policy
    def _ioctl_verified(self, owner_id, cmd, arg, mem_read, mem_write):
        """Opt-in policy: authentic values only, explicit boundary otherwise."""

        if cmd == USB_OTGCORE_IOCTL_SET_PORT_DESC:
            self._check_user_pointer(arg)
            raw = mem_read(arg, 36)
            if getattr(self, 'port_desc', None) is not None:
                # vmlinux 0x602b761c: driver descriptor-valid word already
                # nonzero -> -EBUSY (-16) (0x602b7b94).
                self.transactions.append({'operation': 'ioctl', 'cmd': cmd,
                                          'name': 'USB_OTGCORE_IOCTL_SET_PORT_DESC',
                                          'size': 36, 'returned': -16,
                                          'reason': 'port_descriptor_already_set'})
                return -16
            if int.from_bytes(raw[:4], 'little') == 0:
                # vmlinux 0x602b7610: word0 == 0 -> -EINVAL (-22).
                self.transactions.append({'operation': 'ioctl', 'cmd': cmd,
                                          'name': 'USB_OTGCORE_IOCTL_SET_PORT_DESC',
                                          'size': 36, 'returned': -22,
                                          'reason': 'zero_port_descriptor_word0'})
                return -22
            self.port_desc = raw
            self.transactions.append({'operation': 'ioctl', 'cmd': cmd,
                                      'name': 'USB_OTGCORE_IOCTL_SET_PORT_DESC',
                                      'size': 36, 'returned': 0})
            return 0

        if cmd == USB_OTGCORE_IOCTL_SET_PARAM:
            self._check_user_pointer(arg)
            raw = mem_read(arg, 16)
            self.param = raw
            self.transactions.append({'operation': 'ioctl', 'cmd': cmd,
                                      'name': 'USB_OTGCORE_IOCTL_SET_PARAM',
                                      'size': 16, 'returned': 0})
            return 0

        if cmd == USB_OTGCORE_IOCTL_SET_CONFIG:
            self._check_user_pointer(arg)
            raw = mem_read(arg, 64)
            self.config = raw
            self.config_count = raw[0]
            self.transactions.append({'operation': 'ioctl', 'cmd': cmd,
                                      'name': 'USB_OTGCORE_IOCTL_SET_CONFIG',
                                      'size': 64, 'entry_count': raw[0], 'returned': 0})
            return 0

        if cmd == USB_OTGCORE_IOCTL_SET_MODE:
            self._check_user_pointer(arg)
            raw = mem_read(arg, 1)
            mode = raw[0]
            if mode not in (1, 2):
                # vmlinux 0x602b7c28..0x602b7c34: only 1 or 2 accepted.
                self.transactions.append({'operation': 'ioctl', 'cmd': cmd,
                                          'name': 'USB_OTGCORE_IOCTL_SET_MODE',
                                          'mode': mode, 'returned': -22})
                return -22
            raise UnsupportedUsbOtgCore(
                'usb_otgcore_set_mode_reply_not_derivable',
                cmd=cmd,
                cmd_name='USB_OTGCORE_IOCTL_SET_MODE',
                arg=arg,
                requested_size=1,
                request_field=f'mode={mode}',
                reply_layout='int32 return of driver ops vtable +0x3c (r1=mode-1)',
                kernel_evidence=('vmlinux usb_otgcore_ioctl 0x602b7bd0: copy 1 byte; '
                                 'store driver+0x2e; call driver->ops[+0x3c]; return that result'),
                missing_evidence=('the UDC driver ops object registered with usb_otgcore is '
                                  'not located in retained evidence; its return depends on '
                                  'gadget controller state'))

        if cmd == USB_OTGCORE_IOCTL_SET_FLAG:
            self._check_user_pointer(arg)
            raw = mem_read(arg, 1)
            self.flag = raw[0]
            # vmlinux 0x602b7d20: copy 1 byte; values outside 1..10 take the
            # success path; the driver callback result is NOT propagated.
            self.transactions.append({'operation': 'ioctl', 'cmd': cmd,
                                      'name': 'USB_OTGCORE_IOCTL_SET_FLAG',
                                      'flag': raw[0], 'returned': 0})
            return 0

        if cmd == USB_OTGCORE_IOCTL_SET_SELECT_PORT:
            self._check_user_pointer(arg)
            raw = mem_read(arg, 4)
            port = int.from_bytes(raw, 'little')
            if port != 0:
                raise UnsupportedUsbOtgCore(
                    'usb_otgcore_select_port_reply_not_derivable',
                    cmd=cmd,
                    cmd_name='USB_OTGCORE_IOCTL_SET_SELECT_PORT',
                    arg=arg,
                    requested_size=4,
                    request_field=f'port={port}',
                    reply_layout='int32 0 on success, -EINVAL if port >= driver port count',
                    kernel_evidence=('vmlinux usb_otgcore_ioctl 0x602b7ef0: copy 4 bytes; if '
                                     'driver byte+0x2c (port count) <= 1 returns 0 unchanged; '
                                     'otherwise validates port < count and stores kernel global+8'),
                    missing_evidence=('the hardware port count in driver byte+0x2c is not '
                                      'contained in retained evidence; only port 0 is unambiguous'))
            self.selected_port = 0
            self.transactions.append({'operation': 'ioctl', 'cmd': cmd,
                                      'name': 'USB_OTGCORE_IOCTL_SET_SELECT_PORT',
                                      'port': 0, 'returned': 0})
            return 0

        if cmd == USB_OTGCORE_IOCTL_GET_STATUS:
            self._check_user_pointer(arg)
            raise UnsupportedUsbOtgCore(
                'usb_otgcore_get_status_reply_not_derivable',
                cmd=cmd,
                cmd_name='USB_OTGCORE_IOCTL_GET_STATUS',
                arg=arg,
                requested_size=1,
                reply_layout='uint8 status: 1=(speed 0), 2=(speed 1), 3=(speed 2)',
                kernel_evidence=('vmlinux usb_otgcore_ioctl 0x602b7c80: calls driver->ops[+0x40] '
                                 '(speed getter), maps 0->1, 1->2, 2->3, other->-EFAULT'),
                missing_evidence=('the gadget controller speed negotiated with the USB host is '
                                  'hardware state and no retained evidence fixes it'))

        if cmd == USB_OTGCORE_IOCTL_GET_INFO:
            self._check_user_pointer(arg)
            config_count = getattr(self, 'config_count', 0)
            if config_count > 2:
                # vmlinux 0x602b7f84..0x602b7fc0: global+4 must be 0..2, else -EFAULT.
                self.transactions.append({'operation': 'ioctl', 'cmd': cmd,
                                          'name': 'USB_OTGCORE_IOCTL_GET_INFO',
                                          'config_count': config_count, 'returned': -14})
                return -14
            selected_port = getattr(self, 'selected_port', 0)
            mem_write(arg, struct.pack('<II', config_count, selected_port))
            self.transactions.append({'operation': 'ioctl', 'cmd': cmd,
                                      'name': 'USB_OTGCORE_IOCTL_GET_INFO',
                                      'config_count': config_count,
                                      'selected_port': selected_port,
                                      'reply_bytes': struct.pack('<II', config_count, selected_port).hex(),
                                      'source': 'derived-application-state',
                                      'returned': 0})
            return 0

        if cmd == USB_OTGCORE_IOCTL_START:
            self.started = True
            self.transactions.append({'operation': 'ioctl', 'cmd': cmd,
                                      'name': 'USB_OTGCORE_IOCTL_START',
                                      'source': 'behavioural-e0072-e0298',
                                      'returned': 0})
            return 0

        if cmd == USB_OTGCORE_IOCTL_STOP:
            self.started = False
            self.transactions.append({'operation': 'ioctl', 'cmd': cmd,
                                      'name': 'USB_OTGCORE_IOCTL_STOP',
                                      'source': 'behavioural-e0072-e0298',
                                      'returned': 0})
            return 0

        if cmd == USB_OTGCORE_IOCTL_RESET:
            # vmlinux 0x602b77e4: clears the port-descriptor valid flag; return 0.
            self.started = False
            self.port_desc = None
            self.transactions.append({'operation': 'ioctl', 'cmd': cmd,
                                      'name': 'USB_OTGCORE_IOCTL_RESET',
                                      'returned': 0})
            return 0

        if cmd == USB_OTGCORE_IOCTL_CMD_0XE312:
            # vmlinux 0x602b8104: unconditional success (r6 = 0).
            self.transactions.append({'operation': 'ioctl', 'cmd': cmd,
                                      'name': 'CMD_0xe312', 'returned': 0})
            return 0

        if cmd in USB_OTGCORE_VERIFIED_CALLBACK_BOUNDARY_COMMANDS:
            raise UnsupportedUsbOtgCore(
                'usb_otgcore_driver_callback_reply_not_derivable',
                cmd=cmd,
                cmd_name=USB_OTGCORE_VERIFIED_CALLBACK_BOUNDARY_COMMANDS[cmd],
                arg=arg,
                requested_size=0,
                reply_layout='int32 return of the pinned driver-ops callback',
                kernel_evidence='vmlinux usb_otgcore_ioctl binary-search dispatch',
                missing_evidence=('the registered UDC driver ops object and its callback '
                                  'returns are not located in retained evidence'))

        # Pinned dispatcher returns -ENOTTY for an unrecognised command
        # (vmlinux 0x602b8168: mvn r6, #24).
        self.transactions.append({'operation': 'ioctl', 'cmd': cmd, 'name': 'UNKNOWN',
                                  'returned': -25})
        return -25

    # ----------------------------------------------------------------- close
    def close(self, owner_id):
        if owner_id in self.owners:
            self.transactions.append({'operation': 'close', 'owner_id': owner_id})
            del self.owners[owner_id]
            return 0
        return -9  # -EBADF
