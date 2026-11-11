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

Gadget function-descriptor table (E0303 / task C5): the opt-in
``function_policy='descriptor-table'`` (``configured_functions=('mass-storage',)``
by default) parses the verified 64-byte SET_CONFIG layout and selects functions
through ``GADGET_FUNCTION_TABLE``: the verified MSC entry (host descriptor
E0084 + the app's builder signature) plus explicit PTP, UVC VideoControl,
UVC VideoStreaming and composite PTP+UVC entries whose USB descriptors are from
the retained host captures (E0258/E0240/E0210) but whose otgcore SET_CONFIG
template is unresolved.  Unknown functions/descriptors raise explicit
``UnsupportedUsbOtgCore`` boundaries instead of succeeding silently; the default
``function_policy='legacy'`` path never consults the table and stays
byte-identical.

Strict task limits: all user pointers checked against address_limit
(TASK_SIZE <= 0x5f000000).
"""
import struct
from collections import namedtuple

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

# ---------------------------------------------------------------------------
# Gadget function-descriptor table (E0303)
#
# SET_CONFIG (0x4040e311) wire format, decoded from the pinned kernel handler
# (vmlinux usb_otgcore_ioctl 0x602b8008..0x602b8104):
#
#   config[0]              u8   function/entry count (the kernel stores it in
#                               global+4 (word) and global+12 (byte); GET_INFO
#                               field0 returns global+4 and rejects values > 2)
#   config[1..3]           --   unused padding
#   entry i (i < count)    24 B at config[4 + 24*i]:
#       +0   u32  io_type_a  -> conv_io_type_otgcore2ups() -> global+16+24*i
#       +4   u8              -> global+20+24*i
#       +8   u32             -> global+24+24*i
#       +12  u32  io_type_b  -> conv_io_type_otgcore2ups() -> global+28+24*i
#       +16  u8              -> global+32+24*i
#       +20  u32             -> global+36+24*i
#   config[52]             u32  -> global+0x40
#   config[56]             u8   -> global+0x44
#   config[60]             u32  -> global+0x48
#
# conv_io_type_otgcore2ups (vmlinux 0x602b607c) is an identity for inputs
# 0..4 and prints "<3>usb_otgcore: error" + returns 0 for anything else; the
# valid io-type domain of 0..4 is therefore verified, the semantics of each
# value are not.  The app's only retained SET_CONFIG producer is
# CUsbSvc::read_port_desc_from_backup (libInfraUsbCmn.so 0xa70c), which builds
# a fixed 2-entry descriptor: entry io-type pairs (2,4)/(0,4), fixed zero
# fields, tail word 3, and six values read from backup property IDs
# 0x00F90552/0x00F90553/0x00F90287/0x00F90288/0x00F902C7/0x00F902C8 after the
# 0x010D0077 presence check.  Those properties carry no USB class/subclass
# codes, so the mapping from an entry to a specific USB function (MSC/PTP/UVC)
# is NOT derivable; see the artifacts/analysis/e0303 note.
#
# The table below therefore separates what is verified at USB-descriptor level
# (host captures) from the otgcore entry template.  Only the MSC baseline has a
# retained template (the app's mode-independent builder constants); the PTP and
# UVC entries are explicit placeholders whose otgcore template is unresolved
# and selecting them stops explicitly.
# ---------------------------------------------------------------------------
USB_OTGCORE_CONFIG_SIZE = 64
USB_OTGCORE_CONFIG_COUNT_OFFSET = 0
USB_OTGCORE_CONFIG_ENTRY_OFFSET = 4
USB_OTGCORE_CONFIG_ENTRY_SIZE = 24
USB_OTGCORE_CONFIG_MAX_ENTRIES = 2
USB_OTGCORE_CONFIG_TAIL_OFFSET = 52
USB_OTGCORE_IO_TYPE_VALUES = (0, 1, 2, 3, 4)

USB_OTGCORE_FUNCTION_POLICY_LEGACY = 'legacy'
USB_OTGCORE_FUNCTION_POLICY_DESCRIPTOR_TABLE = 'descriptor-table'
USB_OTGCORE_FUNCTION_POLICIES = (
    USB_OTGCORE_FUNCTION_POLICY_LEGACY,
    USB_OTGCORE_FUNCTION_POLICY_DESCRIPTOR_TABLE,
)

UsbEndpoint = namedtuple(
    'UsbEndpoint', 'address transfer_type max_packet_size interval')
UsbInterface = namedtuple(
    'UsbInterface', 'number alternate class_code subclass protocol endpoints')
OtgcoreConfigTemplate = namedtuple(
    'OtgcoreConfigTemplate',
    'entry_count entry_io_type_pairs fixed_entry_fields tail_word '
    'mutable_fields evidence unresolved_fields')
GadgetFunctionDescriptor = namedtuple(
    'GadgetFunctionDescriptor',
    'name kind usb_class usb_subclass usb_protocol configuration_count '
    'interfaces otgcore_template evidence unresolved_fields notes')
GadgetConfigEntry = namedtuple(
    'GadgetConfigEntry',
    'index io_type_a byte_a word_a io_type_b byte_b word_b raw')

_MSC_TEMPLATE = OtgcoreConfigTemplate(
    entry_count=2,
    entry_io_type_pairs=((2, 4), (0, 4)),
    fixed_entry_fields=(
        {'byte_4': 0x00, 'word_8': 0x00000000},
        {'byte_4': 0x00, 'word_8': 0x00000000},
    ),
    tail_word=3,
    mutable_fields=('entry[0].byte_16', 'entry[0].word_20',
                    'entry[1].byte_16', 'entry[1].word_20',
                    'tail_byte', 'tail_word2'),
    evidence=('libInfraUsbCmn.so CUsbSvc::read_port_desc_from_backup 0xa70c '
              'constants (count=2, io-type pairs (2,4)/(0,4), fixed zeros, tail '
              'word 3); backup property values are mutable'),
    unresolved_fields=(
        'io_type values 0..4 semantics',
        'backup property IDs 0x010D0077/0x00F90552/0x00F90553/0x00F90287/'
        '0x00F90288/0x00F902C7/0x00F902C8 meanings',
        'whether an otgcore entry denotes a USB function or a port descriptor',
    ),
)

GADGET_FUNCTION_TABLE = {
    'mass-storage': GadgetFunctionDescriptor(
        name='mass-storage',
        kind='usb-function',
        usb_class=0x08,
        usb_subclass=0x06,
        usb_protocol=0x50,
        configuration_count=1,
        interfaces=(
            UsbInterface(number=0, alternate=0, class_code=0x08, subclass=0x06,
                         protocol=0x50,
                         endpoints=(UsbEndpoint(0x81, 'bulk', 512, 0),
                                    UsbEndpoint(0x02, 'bulk', 512, 0))),
        ),
        otgcore_template=_MSC_TEMPLATE,
        evidence=('E0084 host enumeration VID_054C PID_0CA8, USB_CLASS_MSC '
                  '8/6/0x50 Bulk-Only Transport, endpoints 0x81 IN / 0x02 OUT '
                  '512 B; MSC entry is the existing verified-connect baseline'),
        unresolved_fields=(
            'configuration count 1 is inferred (single-configuration gadget; '
            'not directly captured for 0CA8)',
        ),
        notes=('verified MSC function; SET_CONFIG template is the app port-'
               'descriptor builder signature, not a per-function class code'),
    ),
    'ptp': GadgetFunctionDescriptor(
        name='ptp',
        kind='usb-interface',
        usb_class=0x06,
        usb_subclass=0x01,
        usb_protocol=0x01,
        configuration_count=1,
        interfaces=(
            UsbInterface(number=0, alternate=0, class_code=0x06, subclass=0x01,
                         protocol=0x01,
                         endpoints=(UsbEndpoint(0x81, 'bulk', 512, 0),
                                    UsbEndpoint(0x02, 'bulk', 512, 0),
                                    UsbEndpoint(0x83, 'interrupt', 32, 7))),
        ),
        otgcore_template=None,
        evidence=('E0258/E0240 host descriptor captures (VID_054C PID_0CAA PC '
                  'Remote): 1 configuration, interface 0 class 6/1/1, endpoints '
                  '0x81 bulk 512 / 0x02 bulk 512 / 0x83 interrupt 32 interval 7; '
                  'firmware-side corroboration: libptp.so interface template '
                  '09 04 00 00 03 06 01 01 05 at 0x1bebb (E0315)'),
        unresolved_fields=(
            'otgcore SET_CONFIG entry template (count, io_type pairs, fixed '
            'fields) for a PTP selected function',
            'mapping of otgcore entry io_type values to this interface',
        ),
        notes='USB descriptor verified; otgcore function selection unresolved',
    ),
    'uvc-control': GadgetFunctionDescriptor(
        name='uvc-control',
        kind='usb-interface',
        usb_class=0x0E,
        usb_subclass=0x01,
        usb_protocol=0x00,
        configuration_count=1,
        interfaces=(
            UsbInterface(number=1, alternate=0, class_code=0x0E, subclass=0x01,
                         protocol=0x00, endpoints=()),
        ),
        otgcore_template=None,
        evidence=('ZV-E10 2.03 UVC chain (E0316): libInfraUsbCmn.so af830315... '
                  'CUsbGadgetStreaming/UVC tables; verified E0154 173-byte '
                  'configuration descriptor cc99cbd9... VideoControl 0x0E/1; '
                  'experimental host composite capture E0258/E0240 also shows '
                  'interface 1 class 14/1 with IAD {8,11,1,2,14,3}'),
        unresolved_fields=(
            'otgcore SET_CONFIG entry template for the UVC control function',
            'interface-association/IAD mapping to otgcore descriptor entries',
        ),
        notes='USB VC descriptor verified; function selection unresolved',
    ),
    'uvc-streaming': GadgetFunctionDescriptor(
        name='uvc-streaming',
        kind='usb-interface',
        usb_class=0x0E,
        usb_subclass=0x02,
        usb_protocol=0x00,
        configuration_count=1,
        interfaces=(
            UsbInterface(number=2, alternate=0, class_code=0x0E, subclass=0x02,
                         protocol=0x00,
                         endpoints=(UsbEndpoint(0x84, 'bulk', 512, 0),)),
        ),
        otgcore_template=None,
        evidence=('ZV-E10 2.03 UVC chain (E0316): verified E0154 173-byte '
                  'configuration descriptor cc99cbd9... VideoStreaming 0x0E/2 '
                  'MJPEG 1280x720, bulk-IN endpoint 0x82 512 B; experimental '
                  'host composite capture E0240 also recorded a 14/2 interface'),
        unresolved_fields=(
            'stock-camera UVC-only topology (captures are the experimental '
            'composite; transfer type/alternate settings unverified for stock)',
            'otgcore SET_CONFIG entry template for UVC streaming',
        ),
        notes='USB VS descriptor from the experimental composite, not stock UVC',
    ),
    'composite-ptp-uvc': GadgetFunctionDescriptor(
        name='composite-ptp-uvc',
        kind='usb-composite',
        usb_class=0xEF,
        usb_subclass=0x02,
        usb_protocol=0x01,
        configuration_count=1,
        interfaces=(
            UsbInterface(number=0, alternate=0, class_code=0x06, subclass=0x01,
                         protocol=0x01,
                         endpoints=(UsbEndpoint(0x81, 'bulk', 512, 0),
                                    UsbEndpoint(0x02, 'bulk', 512, 0),
                                    UsbEndpoint(0x83, 'interrupt', 32, 7))),
            UsbInterface(number=1, alternate=0, class_code=0x0E, subclass=0x01,
                         protocol=0x00, endpoints=()),
            UsbInterface(number=2, alternate=0, class_code=0x0E, subclass=0x02,
                         protocol=0x00,
                         endpoints=(UsbEndpoint(0x84, 'bulk', 512, 0),)),
        ),
        otgcore_template=None,
        evidence=('ZV-E10 2.03 UVC chain (E0316) + verified E0154 serializer '
                  'output cc99cbd9...: device class 0xEF/2/1, 3 interfaces, '
                  'PTP 6/1/1 unchanged, UVC VC 0x0E/1 + VS 0x0E/2 added, IAD '
                  '{08,0B,01,02,0E,03}'),
        unresolved_fields=(
            'otgcore SET_CONFIG entry template for a composite configuration',
            'IAD descriptor bytes beyond class/subclass ({8,11,1,2,14,3})',
        ),
        notes='composite host evidence only; no otgcore selection evidence',
    ),
}


# ---------------------------------------------------------------------------
# ZV-E10 2.03 UVC chain reference evidence (E0316)
#
# The complete UVC chain exists only in the ZV-E10 reference firmware:
#   kmod/usbg_video.ko, kmod/usbg_audio.ko, lib/libInfraStreamingUsb.so and the
#   ZV-E10 lib/libInfraUsbCmn.so (CUsbGadgetStreaming, PAL/NTSC descriptor
#   tables, RegVideoDataBufInfo/UpdateVideoBufEvt/WaitVideoReadCmp).
# All components use the same vermagic as a6400 and the a6400 kernel/modules
# export the referenced symbols (dma330_mem_transfer_async; osal_snd_msg,
# osal_valloc_msg_wait, osal_snd_sync_direct, osal_snd_sync_msg,
# osal_dynamic_id, osal_free_msg, osal_rcv_msg_tmo).  This is symbol/vermagic
# parity, not loadability or runtime proof; nothing was loaded on the camera.
#
# The configuration descriptor below is the compiled, verified E0154 serializer
# output (173 bytes, SHA-256 cc99cbd9...): PTP 6/1/1 with 3 endpoints, IAD,
# UVC VideoControl 0x0E/1, UVC VideoStreaming 0x0E/2 with MJPEG 1280x720 and
# bulk-IN endpoint 0x82 512 B.  It supplies descriptor evidence only; the
# otgcore SET_CONFIG io-type mapping remains unresolved.
# ---------------------------------------------------------------------------
ZVE10_UVC_CHAIN_COMPONENTS = {
    '/usr/kmod/usbg_video.ko': {
        'size': 20668,
        'sha256': 'd385a051bf01b0e5ea37412623ae85cfe3cda76ab0d11e61d111994ca9fbf4fb',
    },
    '/usr/kmod/usbg_audio.ko': {
        'size': 20456,
        'sha256': '8f73572784aab15da291c9f311a945d4ec56d2dd4162218164bc2aa18cc5fae0',
    },
    '/usr/lib/libInfraStreamingUsb.so': {
        'size': 52524,
        'sha256': '0a9448e364e8f014db02edc8e164470c70f2d2143ce5de74697e9ffba697cce8',
    },
    '/usr/lib/libInfraUsbCmn.so': {
        'size': 94612,
        'sha256': 'af830315ce51c38b010995f2147d556286364323734f64b877fcc3bb1a916c02',
        'note': 'ZV-E10 build with CUsbGadgetStreaming/UVC tables; a6400 tree '
                'has a different build without streaming definitions',
    },
}
ZVE10_UVC_CONFIG_DESCRIPTOR_HEX = (
    '0902ad0003010080fa'
    '090400000306010100'
    '07058102000200'
    '07050202000200'
    '07058303200007'
    '080b01020e030000'
    '09040100000e010000'
    '0d240100012800006cdc020102'
    '122402010102000000000000000003000000'
    '092403020101000100'
    '09040200010e020000'
    '0e2401013d008200020000000100'
    '0b24060101010100000000'
    '1e240701000005d00200'
    '005e1a00005e1a0000e100151605000115160500'
    '06240d010104'
    '07058202000200'
)
ZVE10_UVC_CONFIG_DESCRIPTOR_SHA256 = (
    'cc99cbd9ca3ed62b009de00e69095cf04fdc6986b337719dbda8e7c2d197231f')
ZVE10_UVC_ACTIVATION_SEQUENCE = (
    'StreamingGadget_init / usb_streaming_register_gadget',
    'usb_gadgetcore_register_driver',
    'host SET_CONFIG / proc_kevent_video',
    'StateMachine Idle/Ready funcHostStartVideoEvt',
    'funcStartVideoDriverCmp / VideoEsManager video_stream_start',
    'funcProbeReqVideoEvt / SendProbeInfo (UVC PROBE)',
    'funcCommitReqVideoEvt / SendCommitInfo (UVC COMMIT)',
    'funcVideoStartBulkEvt / RegVideoDataBufInfo / UpdateVideoBufEvt',
    'usbg_video iso-in + dma330_mem_transfer_async / uvc_transfer_dmac_cb',
    'WaitVideoReadCmp / buffer completion',
    'funcHostStopVideoEvt / video_stream_stop / unregister',
)
ZVE10_UVC_VIDEO_BUFFER_API = (
    'RegVideoDataBufInfo', 'UnregVideoDataBufInfo', 'UpdateVideoBufEvt',
    'WaitVideoReadCmp', 'SendProbeInfo', 'SendCommitInfo',
)


# ZV-E10 UVC descriptor source cross-check (E0317)
#
# The E0154 verified UVC+PTP configuration descriptor is byte-derived from the
# ZV-E10 2.03 libInfraUsbCmn.so descriptor tables (SHA-256 af830315...):
#   VC class-specific 40 B at file offset 0x12598
#   VS class-specific 61 B at file offset 0x12625 (endpoint byte 0x81)
#   MJPEG 1280x720/30fps frame 30 B at file offset 0x1263e
# with exactly two documented adaptations (VC baInterfaceNr 1->2, VS endpoint
# 0x81->0x82).  Descriptor evidence only: the otgcore SET_CONFIG template
# remains unresolved and no UVC function is claimed.
ZVE10_UVC_SOURCE_BLOBS = {
    'vc_class_specific': {
        'file_offset': 0x12598,
        'length': 40,
        'hex': ('0d240100012800006cdc020101'
                '122402010102000000000000000003000000'
                '092403020101000100'),
    },
    'vs_class_specific': {
        'file_offset': 0x12625,
        'length': 61,
        'hex': ('0e2401013d008100020000000100'
                '0b24060101010100000000'
                '1e240701000005d00200005e1a00005e1a0000e100151605000115160500'
                '06240d010104'),
    },
    'ntsc_frame': {
        'file_offset': 0x1263e,
        'length': 30,
        'hex': '1e240701000005d00200005e1a00005e1a0000e100151605000115160500',
    },
}
ZVE10_UVC_DESCRIPTOR_CHANGES = (
    ('vc_class_specific', 12, 0x01, 0x02, 'baInterfaceNr 1 -> 2'),
    ('vs_class_specific', 6, 0x81, 0x82, 'bEndpointAddress 0x81 -> 0x82'),
)


def uvc_ptp_configuration_source_crosscheck():
    '''Verify the E0154 descriptor against the ZV-E10 source blobs (E0317).

    Returns a dict with booleans and the exact documented byte changes.  Pure
    byte comparison; no firmware read and no camera access.
    '''
    entries = parse_usb_configuration_descriptor(
        bytes.fromhex(ZVE10_UVC_CONFIG_DESCRIPTOR_HEX))
    class_blobs = {off: blob for off, _length, dtype, blob in entries
                   if dtype == 0x24}
    vc = b''.join(class_blobs[off] for off in (0x38, 0x45, 0x57))
    vs = b''.join(class_blobs[off] for off in (0x69, 0x77, 0x82, 0xA0))
    frame = class_blobs[0x82]
    source = {name: bytes.fromhex(info['hex'])
              for name, info in ZVE10_UVC_SOURCE_BLOBS.items()}
    adapted = {'vc_class_specific': bytearray(source['vc_class_specific']),
               'vs_class_specific': bytearray(source['vs_class_specific'])}
    applied = []
    for name, index, old, new, meaning in ZVE10_UVC_DESCRIPTOR_CHANGES:
        blob = adapted[name]
        matched = len(blob) > index and blob[index] == old
        if matched:
            blob[index] = new
        applied.append({'block': name, 'index': index, 'old_byte': old,
                        'new_byte': new, 'meaning': meaning,
                        'source_byte_matched': matched})
    return {
        'vc_equal': bytes(adapted['vc_class_specific']) == vc,
        'vs_equal': bytes(adapted['vs_class_specific']) == vs,
        'frame_equal': source['ntsc_frame'] == frame,
        'source_offsets': {name: info['file_offset']
                           for name, info in ZVE10_UVC_SOURCE_BLOBS.items()},
        'changes': applied,
        'vc_bytes': len(vc),
        'vs_bytes': len(vs),
        'frame_bytes': len(frame),
    }


def parse_usb_configuration_descriptor(raw):
    '''Return the flat descriptor list of a USB configuration blob.

    Each item is ``(offset, length, descriptor_type, bytes)``.  Pure structure
    parsing; no field interpretation or validation of device behaviour.
    '''
    entries = []
    offset = 0
    while offset + 2 <= len(raw):
        length = raw[offset]
        if length < 2 or offset + length > len(raw):
            break
        entries.append((offset, length, raw[offset + 1],
                        bytes(raw[offset:offset + length])))
        offset += length
    return tuple(entries)


def summarize_uvc_ptp_configuration(raw=None):
    '''Summarize the verified UVC+PTP configuration descriptor (E0154/E0316).'''
    data = bytes.fromhex(ZVE10_UVC_CONFIG_DESCRIPTOR_HEX) if raw is None else bytes(raw)
    summary = {'total_length': len(data), 'interfaces': [], 'endpoints': [],
               'class_specific': [], 'other': []}
    for offset, length, dtype, blob in parse_usb_configuration_descriptor(data):
        if dtype == 0x02:
            summary['config'] = {
                'offset': offset,
                'wTotalLength': int.from_bytes(blob[2:4], 'little'),
                'bNumInterfaces': blob[4],
                'bConfigurationValue': blob[5],
            }
        elif dtype == 0x04:
            summary['interfaces'].append({
                'offset': offset,
                'number': blob[2],
                'alternate': blob[3],
                'endpoints': blob[4],
                'class_code': blob[5],
                'subclass': blob[6],
                'protocol': blob[7],
            })
        elif dtype == 0x05:
            summary['endpoints'].append({
                'offset': offset,
                'address': blob[2],
                'attributes': blob[3],
                'max_packet_size': int.from_bytes(blob[4:6], 'little'),
                'interval': blob[6],
            })
        elif dtype == 0x24:
            entry = {'offset': offset, 'subtype': blob[2], 'length': length}
            if blob[2] == 0x07 and length >= 26:
                entry['frame'] = {
                    'width': int.from_bytes(blob[5:7], 'little'),
                    'height': int.from_bytes(blob[7:9], 'little'),
                    'max_frame_buffer': int.from_bytes(blob[17:21], 'little'),
                    'default_interval_100ns': int.from_bytes(blob[21:25], 'little'),
                }
            summary['class_specific'].append(entry)
        else:
            summary['other'].append({'offset': offset, 'type': dtype,
                                     'length': length})
    return summary


def parse_otgcore_config(raw):
    """Parse the pinned 64-byte SET_CONFIG layout.

    Returns ``(count, entries, tail)`` with ``entries`` a tuple of
    :class:`GadgetConfigEntry` and ``tail`` holding the raw tail fields
    (``word``/``byte``/``word2``).  Pure parsing; no validation is implied.
    """
    if len(raw) != USB_OTGCORE_CONFIG_SIZE:
        raise ValueError(f'expected {USB_OTGCORE_CONFIG_SIZE}-byte otgcore config')
    count = raw[USB_OTGCORE_CONFIG_COUNT_OFFSET]
    entries = []
    for index in range(min(count, USB_OTGCORE_CONFIG_MAX_ENTRIES)):
        base = USB_OTGCORE_CONFIG_ENTRY_OFFSET + index * USB_OTGCORE_CONFIG_ENTRY_SIZE
        entries.append(GadgetConfigEntry(
            index=index,
            io_type_a=struct.unpack_from('<I', raw, base + 0)[0],
            byte_a=raw[base + 4],
            word_a=struct.unpack_from('<I', raw, base + 8)[0],
            io_type_b=struct.unpack_from('<I', raw, base + 12)[0],
            byte_b=raw[base + 16],
            word_b=struct.unpack_from('<I', raw, base + 20)[0],
            raw=bytes(raw[base:base + USB_OTGCORE_CONFIG_ENTRY_SIZE]),
        ))
    tail = {
        'word': struct.unpack_from('<I', raw, USB_OTGCORE_CONFIG_TAIL_OFFSET)[0],
        'byte': raw[USB_OTGCORE_CONFIG_TAIL_OFFSET + 4],
        'word2': struct.unpack_from('<I', raw, USB_OTGCORE_CONFIG_TAIL_OFFSET + 8)[0],
    }
    return count, tuple(entries), tail


def gadget_function(name):
    """Return the :class:`GadgetFunctionDescriptor` for ``name``."""
    try:
        return GADGET_FUNCTION_TABLE[name]
    except KeyError:
        raise ValueError(f'unknown gadget function: {name!r}') from None


class UnsupportedUsbOtgCore(RuntimeError):
    def __init__(self, reason, **details):
        super().__init__(reason)
        self.details = {'reason': reason, 'device': '/dev/usb/otgcore', **details}


class GuestUsbOtgCore:
    """Emulates /dev/usb/otgcore character device (242:2)."""

    def __init__(self, address_limit=0x5f000000,
                 reply_policy=USB_OTGCORE_REPLY_POLICY_LEGACY,
                 function_policy=USB_OTGCORE_FUNCTION_POLICY_LEGACY,
                 configured_functions=None):
        if reply_policy not in USB_OTGCORE_REPLY_POLICIES:
            raise ValueError(f'unsupported usb otgcore reply policy: {reply_policy!r}')
        if function_policy not in USB_OTGCORE_FUNCTION_POLICIES:
            raise ValueError(f'unsupported usb otgcore function policy: {function_policy!r}')
        if configured_functions is None:
            configured_functions = ('mass-storage',)
        configured_functions = tuple(configured_functions)
        for name in configured_functions:
            if name not in GADGET_FUNCTION_TABLE:
                raise ValueError(f'unknown gadget function: {name!r}')
        self.address_limit = address_limit
        self.major = 242
        self.minor = 2
        self.owners = {}
        self.started = False
        self.port_desc = None
        self.config = None
        self.transactions = []
        self.reply_policy = reply_policy
        self.function_policy = function_policy
        self.configured_functions = configured_functions
        # Function selection results (empty until SET_CONFIG under the
        # descriptor-table policy); kernel-state mirrors for GET_INFO below.
        self.selected_functions = ()
        self.config_entries = ()
        self.config_tail = None
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
            if getattr(self, 'function_policy',
                       USB_OTGCORE_FUNCTION_POLICY_LEGACY) == \
                    USB_OTGCORE_FUNCTION_POLICY_DESCRIPTOR_TABLE:
                return self._configure_gadget_functions(cmd, raw)
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
                                      'selected_functions': list(
                                          getattr(self, 'selected_functions', ())),
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

    # ------------------------------------------- gadget function selection
    @staticmethod
    def _matches_otgcore_template(count, entries, tail, template):
        if template is None or count != template.entry_count:
            return False
        pairs = tuple((entry.io_type_a, entry.io_type_b) for entry in entries)
        if pairs != template.entry_io_type_pairs:
            return False
        for entry, fixed in zip(entries, template.fixed_entry_fields):
            if entry.byte_a != fixed['byte_4'] or entry.word_a != fixed['word_8']:
                return False
        return tail['word'] == template.tail_word

    def _store_otgcore_config(self, raw, count, entries, tail, selected):
        self.config = raw
        self.config_count = count
        self.config_entries = entries
        self.config_tail = tail
        self.selected_functions = tuple(selected)
        self.transactions.append({
            'operation': 'ioctl',
            'cmd': USB_OTGCORE_IOCTL_SET_CONFIG,
            'name': 'USB_OTGCORE_IOCTL_SET_CONFIG',
            'size': USB_OTGCORE_CONFIG_SIZE,
            'entry_count': count,
            'selected_functions': list(selected),
            'descriptor_resolution': ('mass-storage-template' if selected else 'no-functions'),
            'returned': 0,
        })

    def _configure_gadget_functions(self, cmd, raw):
        """SET_CONFIG under function_policy='descriptor-table'.

        Parses the pinned wire layout, validates the verified io-type domain,
        and selects functions through :data:`GADGET_FUNCTION_TABLE`.  Any
        descriptor that is not backed by retained evidence raises an explicit
        boundary; there is no silent success for an unknown function.
        """
        count, entries, tail = parse_otgcore_config(raw)
        entry_rows = [{
            'index': entry.index,
            'io_type_a': entry.io_type_a,
            'byte_4': entry.byte_a,
            'word_8': entry.word_a,
            'io_type_b': entry.io_type_b,
            'byte_16': entry.byte_b,
            'word_20': entry.word_b,
            'raw_hex': entry.raw.hex(),
        } for entry in entries]
        configured = tuple(getattr(self, 'configured_functions', ('mass-storage',)))
        common = {
            'cmd': cmd,
            'cmd_name': 'USB_OTGCORE_IOCTL_SET_CONFIG',
            'config_size': USB_OTGCORE_CONFIG_SIZE,
            'config_hex': raw.hex(),
            'entry_count': count,
            'entries': entry_rows,
            'tail': tail,
            'configured_functions': list(configured),
        }

        if count > USB_OTGCORE_CONFIG_MAX_ENTRIES:
            raise UnsupportedUsbOtgCore(
                'usb_otgcore_gadget_function_count_unsupported',
                **common,
                max_supported=USB_OTGCORE_CONFIG_MAX_ENTRIES,
                kernel_evidence=('vmlinux SET_CONFIG stores count in global+4/+12; '
                                 'GET_INFO accepts only 0..2'),
                missing_evidence=('no retained configuration with more than two '
                                  'otgcore descriptor entries'))

        for entry in entries:
            for io_type in (entry.io_type_a, entry.io_type_b):
                if io_type not in USB_OTGCORE_IO_TYPE_VALUES:
                    raise UnsupportedUsbOtgCore(
                        'usb_otgcore_gadget_io_type_unsupported',
                        **common,
                        entry_index=entry.index,
                        io_type=io_type,
                        valid_io_types=list(USB_OTGCORE_IO_TYPE_VALUES),
                        kernel_evidence=('vmlinux conv_io_type_otgcore2ups 0x602b607c is '
                                         'identity for 0..4 and prints '
                                         '"<3>usb_otgcore: error" then returns 0 above 4'),
                        missing_evidence=('the semantics of io-type values 0..4 are not '
                                          'retained; only the valid domain is verified'))

        unresolved = [name for name in configured
                      if GADGET_FUNCTION_TABLE[name].otgcore_template is None]
        if unresolved:
            missing = []
            for name in unresolved:
                missing.extend(f'{name}: {field}'
                               for field in GADGET_FUNCTION_TABLE[name].unresolved_fields)
            raise UnsupportedUsbOtgCore(
                'usb_otgcore_gadget_function_descriptor_unresolved',
                **common,
                unresolved_functions=unresolved,
                missing_fields=missing,
                descriptor_evidence={name: GADGET_FUNCTION_TABLE[name].evidence
                                     for name in unresolved})

        if count == 0:
            if configured:
                raise UnsupportedUsbOtgCore(
                    'usb_otgcore_gadget_function_selection_mismatch',
                    **common,
                    selected_functions=[],
                    expected='config entry count 0 for an empty function set')
            self._store_otgcore_config(raw, 0, entries, tail, ())
            return 0

        if not configured:
            raise UnsupportedUsbOtgCore(
                'usb_otgcore_gadget_function_selection_mismatch',
                **common,
                selected_functions=[],
                expected='an explicit function selection for a non-empty config')

        template = GADGET_FUNCTION_TABLE['mass-storage'].otgcore_template
        if configured == ('mass-storage',) and \
                self._matches_otgcore_template(count, entries, tail, template):
            self._store_otgcore_config(raw, count, entries, tail, ('mass-storage',))
            return 0

        raise UnsupportedUsbOtgCore(
            'usb_otgcore_gadget_function_descriptor_unknown',
            **common,
            selected_functions=[],
            expected_template={
                'entry_count': template.entry_count,
                'entry_io_type_pairs': [list(pair) for pair in
                                        template.entry_io_type_pairs],
                'fixed_entry_fields': list(template.fixed_entry_fields),
                'tail_word': template.tail_word,
                'mutable_fields': list(template.mutable_fields),
                'evidence': template.evidence,
            },
            missing_evidence=('the otgcore entry template for any non-baseline '
                              'function is not retained; the entry io types carry '
                              'no USB class/subclass code'))

    # ----------------------------------------------------------------- close
    def close(self, owner_id):
        if owner_id in self.owners:
            self.transactions.append({'operation': 'close', 'owner_id': owner_id})
            del self.owners[owner_id]
            return 0
        return -9  # -EBADF
