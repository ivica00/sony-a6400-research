"""Evidence-bound ZV-E10 usbg_video contract constants (E0319/E0316).

This module only describes the ZV-E10 2.03 UVC video kernel-driver ABI that was
decoded offline from `usbg_video.ko` (SHA-256 d385a051...).  It does not model
the driver's runtime behaviour and returns no fabricated success: the command
decoder is a pure ``_IOC``/legacy-command description and the context offsets
are the fields observed in `usbg_video_core_ioctl`.
"""

ZVE10_USBG_VIDEO_SHA256 = (
    'd385a051bf01b0e5ea37412623ae85cfe3cda76ab0d11e61d111994ca9fbf4fb')
ZVE10_USBG_VIDEO_SIZE = 20668

# ioctl dir bits as used by Linux `_IOC_DIR`.
USB_VIDEO_IOCTL_DIR_NONE = 0
USB_VIDEO_IOCTL_DIR_WRITE = 1
USB_VIDEO_IOCTL_DIR_READ = 2
USB_VIDEO_IOCTL_DIR_READ_WRITE = 3

# Decoded from usbg_video_core_ioctl:
#   0x1e20 ubfx type byte / 0x1e28 cmp #0xE0 / 0x1e38 cmp nr,#2
#   0x1ed0 ldr literal 0x4038e000  (56-byte read/write request)
#   0x217c movw #0xf006         (legacy numeric command)
#   0x21a8 ldr literal 0x4008f000 (8-byte write command)
ZVE10_USBG_VIDEO_IOCTL_COMMANDS = {
    0x4038E000: {
        'name': 'uvc_request_write',
        'dir': USB_VIDEO_IOCTL_DIR_READ_WRITE,
        'type': 0xE0,
        'nr': 0,
        'size': 0x38,
        'evidence': 'usbg_video_core_ioctl literal at 0x23c0',
    },
    0x4008F000: {
        'name': 'uvc_request_write_8',
        'dir': USB_VIDEO_IOCTL_DIR_WRITE,
        'type': 0xF0,
        'nr': 0,
        'size': 0x8,
        'evidence': 'usbg_video_core_ioctl literal at 0x23e4',
    },
    0x0000E001: {
        'name': 'legacy_command_e001',
        'dir': None,
        'type': None,
        'nr': None,
        'size': None,
        'evidence': 'usbg_video_core_ioctl movw r3,#0xe001 at 0x1ec0',
    },
}

# Per-file USB video context fields observed in usbg_video_core_ioctl (ARM
# r4 = file context).  Names are descriptive only; the semantics of each slot
# remain to be confirmed against libInfraUsbCmn's buffer API (E0316).
ZVE10_USBG_VIDEO_CONTEXT_FIELDS = {
    0x10: 'transfer_state_a',
    0x14: 'transfer_state_b',
    0x24: 'uvc_request_buffer_pointer',
    0x38: 'request_descriptor_word',
    0x3C: 'request_bRequestType',
    0x3D: 'request_bRequest',
    0x40: 'request_pointer_slot',
    0x44: 'request_index_or_mode',
    0x48: 'self_pointer',
    0x50: 'completion_slot_0',
    0x54: 'completion_slot_1',
    0x58: 'completion_slot_2',
    0x5C: 'completion_slot_3',
    0x60: 'completion_slot_4',
    0x64: 'completion_slot_5',
    0x68: 'completion_slot_6',
    0x6C: 'completion_slot_7',
}


def decode_usb_video_ioctl(command):
    """Describe a ZV-E10 usbg_video ioctl command without executing anything.

    Returns the known command description for the two decoded `_IOC` commands
    and the legacy `0xe001`; for an unknown command returns a dict with
    ``known`` False and the generic `_IOC` decomposition (or legacy value).
    """
    if command in ZVE10_USBG_VIDEO_IOCTL_COMMANDS:
        description = dict(ZVE10_USBG_VIDEO_IOCTL_COMMANDS[command])
        description['command'] = command
        description['known'] = True
        return description
    decomposed = {
        'command': command,
        'known': False,
        'dir': (command >> 30) & 0x3,
        'size': (command >> 16) & 0x3FFF,
        'type': (command >> 8) & 0xFF,
        'nr': command & 0xFF,
        'evidence': 'generic _IOC decomposition; not a decoded ZV-E10 command',
    }
    return decomposed


# ---------------------------------------------------------------------------
# Buffer/completion layout observed in usbg_video_call_user_cb /
# usbg_video_st_write_comp / uvc_transfer_dmac_cb (E0319 third pass).
#
# Scalar offsets only; field semantics that are not directly observable are
# labelled as hypotheses, not claims.
# ---------------------------------------------------------------------------
# call_user_cb: jump table selects [this_ex + slot] for event ids 0..7.
USBG_VIDEO_USER_CALLBACK_SLOTS = {
    0: 0x04, 1: 0x08, 2: 0x0C, 3: 0x10,
    4: 0x14, 5: 0x18, 6: 0x1C, 7: 0x20,
}
# st_write_comp: r4 points at the completed data object; [+0x2C] is read as a
# signed completion result (special values -0x54 / -0x68 are handled), and the
# object is matched by pointer against a global circular list (node +0/+4/+8).
USBG_VIDEO_DATA_INFO_FIELDS = {
    0x00: 'list_backlink_or_pointer',
    0x04: 'list_link_a_hypothesis',
    0x08: 'completion_callback_hypothesis',
    0x2C: 'completion_result_signed',
}
USBG_VIDEO_WRITE_COMP_LIST_NODE = {
    0x00: 'data_info_pointer',
    0x04: 'link_a',
    0x08: 'link_b',
}
# uvc_transfer_dmac_cb: r4 points at the DMA completion argument; [+8] is an
# optional callback invoked after the global transfer flag is set.
USBG_VIDEO_DMA_COMPLETION_FIELDS = {
    0x08: 'completion_callback_optional',
}
# usb_sync_alloc_phys_buffer / usb_sync_free_phys_buffer: observed memory fields
# on the physical-buffer descriptor argument (offsets only).
USBG_VIDEO_PHYS_BUFFER_FIELDS = {
    0x00: 'virtual_pointer',
    0x02: 'size_or_flags_hypothesis',
    0x04: 'physical_pointer_hypothesis',
    0x0C: 'cache_or_alignment_word',
    0x10: 'virtual_pointer_out_hypothesis',
    0x14: 'physical_pointer_out_hypothesis',
    0x16: 'flags_hypothesis',
}


def describe_usbg_video_buffer_contract():
    """Return the observed usbg_video buffer/completion slots (no behaviour)."""
    return {
        'user_callback_slots': dict(USBG_VIDEO_USER_CALLBACK_SLOTS),
        'data_info_fields': dict(USBG_VIDEO_DATA_INFO_FIELDS),
        'write_completion_list_node': dict(USBG_VIDEO_WRITE_COMP_LIST_NODE),
        'dma_completion_fields': dict(USBG_VIDEO_DMA_COMPLETION_FIELDS),
        'phys_buffer_fields': dict(USBG_VIDEO_PHYS_BUFFER_FIELDS),
        'evidence': 'usbg_video_call_user_cb/st_write_comp/uvc_transfer_dmac_cb/'
                    'usb_sync_alloc_phys_buffer/ usb_sync_free_phys_buffer; '
                    'hypothesis labels are explicit',
    }


# ---------------------------------------------------------------------------
# Register/unregister ABI decoded in E0319 section 8 (third pass follow-up).
# ---------------------------------------------------------------------------
USB_VIDEO_PROBE_INFO_SIZE = 0x38  # 56-byte user block checked by copy_from_user
USB_VIDEO_REGISTER_COMMAND = 0x4038E000
USB_VIDEO_UNREGISTER_LEGACY_COMMAND = 0x0000E001
USB_VIDEO_PROBE_INFO_FIELDS = {
    0x24: 'buffer_table_pointer',   # count*2 bytes copied to context+0x24
    0x30: 'blob_pointer',           # copied to context+0x30 (0 => no blob)
    0x34: 'blob_length',
}
# usbg_cmn.ko functions are byte-identical between a6400 8.2.5.7 and ZV-E10
# 2.03 (same size and SHA-256 in both trees), so the probe-info ABI is already
# present in the a6400 firmware.
USB_CMN_COPY_PROBE_INFO_SHA256 = (
    '978608ceaa3560fb89af3d77738c9ff01cee6731ff0aebd504359fbaa4c47d7a')
USB_CMN_CLEAR_PROBE_INFO_SHA256 = (
    'ed16a3cb5ff777a0b0938ce2477b453779bbf6dfa5b1087043e385256055f2c9')


def parse_usb_video_probe_info(data):
    """Parse the 56-byte register-time probe/commit block (E0319).

    Observed copy path (usbg_cmn_copy_probe_info, byte-identical in a6400 and
    ZV-E10): access_ok(arg,0x38); copy_from_user 56 B; allocate count*2 bytes
    (count from context+0x2D) and copy from user+0x24; allocate user+0x34
    bytes and copy from user+0x30 (pointer 0 => clear and success).  Only the
    directly observed fields are returned.
    """
    if not isinstance(data, (bytes, bytearray)) or len(data) < USB_VIDEO_PROBE_INFO_SIZE:
        raise ValueError('usb_video probe info must be at least 0x38 bytes')
    data = bytes(data)
    return {
        'size': USB_VIDEO_PROBE_INFO_SIZE,
        'buffer_table_pointer': int.from_bytes(data[0x24:0x28], 'little'),
        'blob_pointer': int.from_bytes(data[0x30:0x34], 'little'),
        'blob_length': int.from_bytes(data[0x34:0x38], 'little'),
        'raw': data[:USB_VIDEO_PROBE_INFO_SIZE].hex(),
    }


# ---------------------------------------------------------------------------
# Gadgetcore driver registration + open() buffer layout (E0319 section 9).
# ---------------------------------------------------------------------------
USB_VIDEO_DRIVER_NAME = 'USB Gadget Video Device'
# context+0x38 is the usb_gadgetcore driver struct filled by the register ioctl.
USB_VIDEO_GADGETCORE_DRIVER_FIELDS = {
    0x38: 'driver_name_pointer',      # .rodata.str1.1 + 0x296
    0x3C: 'request_bRequestType',     # copied from context+0x24 buffer
    0x3D: 'request_bRequest',
    0x40: 'format_parameter_pointer', # .bss + 8 + 0x35
    0x44: 'driver_entry_count',       # value 2
    0x48: 'self_pointer',
}
USB_VIDEO_CORE_CALLBACKS = {
    0x50: {'name': 'core_cb_start', 'address': 0x10F0, 'size': 204},
    0x54: {'name': 'core_cb_stop', 'address': 0x0744, 'size': 388},
    0x58: {'name': 'core_cb_set_halt', 'address': 0x068C, 'size': 20},
    0x5C: {'name': 'core_cb_clear_halt', 'address': 0x06EC, 'size': 56},
    0x60: {'name': 'core_cb_nop', 'address': 0x067C, 'size': 16},
    0x64: {'name': 'core_cb_nop', 'address': 0x067C, 'size': 16},
    0x68: {'name': 'core_cb_nop', 'address': 0x067C, 'size': 16},
    0x6C: {'name': 'core_cb_class', 'address': 0x17B0, 'size': 708},
}
# usbg_video_core_open (0x1AC8) fields observed on the video context.
USB_VIDEO_OPEN_CONTEXT_FIELDS = {
    0x00: 'physical_buffer_virtual_pointer',
    0x04: 'physical_buffer_physical_pointer',
    0x08: 'iso_in_virtual_start',
    0x0C: 'iso_in_virtual_end',
    0xA0: 'phys_buffer_tag_or_handle',
    0xA4: 'phys_buffer_length',
    0xAC: 'request_object_0xd0_bytes',
    0xB0: 'dma_info_object_0x24_bytes',
}


def describe_usbg_video_register_contract():
    """Return the register/open layout observed in usbg_video.ko (E0319)."""
    return {
        'register_command': USB_VIDEO_REGISTER_COMMAND,
        'unregister_command': USB_VIDEO_UNREGISTER_LEGACY_COMMAND,
        'probe_info_size': USB_VIDEO_PROBE_INFO_SIZE,
        'probe_info_fields': dict(USB_VIDEO_PROBE_INFO_FIELDS),
        'driver_name': USB_VIDEO_DRIVER_NAME,
        'gadgetcore_driver_fields': dict(USB_VIDEO_GADGETCORE_DRIVER_FIELDS),
        'core_callbacks': {offset: dict(row)
                           for offset, row in USB_VIDEO_CORE_CALLBACKS.items()},
        'open_context_fields': dict(USB_VIDEO_OPEN_CONTEXT_FIELDS),
        'evidence': 'usbg_video_core_ioctl relocations + usbg_video_core_open '
                    '(0x1AC8) disassembly; hypothesis names are explicit',
    }


# ---------------------------------------------------------------------------
# 0xF0 ioctl family = transfer path (E0319 section 10).
# Decoded from usbg_video_core_ioctl 0x20B4..0x23B0.
# ---------------------------------------------------------------------------
USB_VIDEO_TRANSFER_IOCTLS = {
    0x4008F000: {
        'name': 'set_dma_address',
        'size': 8,
        'effect': 'copy_from_user 8 B; context+0x14 = raw value, '
                  'context+0x10 = raw + 0x60000000 (>=0) or +0x20000000 (<0)',
    },
    0x0000F001: {
        'name': 'clear_dma_address',
        'size': 0,
        'effect': 'context+0x10 = context+0x14 = 0',
    },
    0x0000F002: {
        'name': 'transfer_log_status',
        'size': 0,
        'effect': 'reads global bytes +0x10/+0x11; logs via snprintf; '
                  'returns 0 or -0xF when the state bytes are not set',
    },
    0x0000F006: {
        'name': 'enable_transfer',
        'size': 0,
        'effect': 'context+0xCC = 1',
    },
    0x4008F003: {
        'name': 'write_transfer',
        'size': 8,
        'effect': 'calls helper 0x0D00 with the user pointer: copy_from_user '
                  '8 B, usbg_video_get_ep, mutex locks, queue/transfer bookkeeping',
    },
}
# The context byte +0x2D (buffer-table count read by copy_probe_info) is not
# written by usbg_video.ko text; create_this zeroes the 0xC0 context, so the
# writer stays an explicit boundary.
USB_VIDEO_CONTEXT_COUNT_OFFSET = 0x2D


def describe_usbg_video_transfer_contract():
    """Return the decoded 0xF0 transfer-ioctl family (no behaviour modelled)."""
    return {
        'transfer_ioctls': {command: dict(row)
                            for command, row in USB_VIDEO_TRANSFER_IOCTLS.items()},
        'context_count_offset': USB_VIDEO_CONTEXT_COUNT_OFFSET,
        'count_writer': 'unresolved',
        'evidence': 'usbg_video_core_ioctl 0x20B4..0x23B0 relocations and '
                    'disassembly; effects are instruction-level observations',
    }


# ---------------------------------------------------------------------------
# Endpoint-list setup by core_cb_start (E0319 section 11).
# core_cb_start(0x10F0) receives (driver, ep_id, count, list): stores ep_id at
# this_ex+0x9C, then calls usbg_cmn_make_ep_list(context, ep_id, count, list).
# usbg_cmn_make_ep_list (0x2BC, 128 B) writes the context fields below.
# ---------------------------------------------------------------------------
USB_VIDEO_EP_LIST_CONTEXT_FIELDS = {
    0xB2: 'ep_id_byte',
    0xB4: 'ep_list_pointer',   # kmalloc(count*4) + copy of endpoint descriptors
    0xB8: 'ep_count_byte',
}
USB_VIDEO_THIS_EX_EP_ID_OFFSET = 0x9C


def describe_usbg_video_endpoint_list_contract():
    """Return the core_cb_start/usbg_cmn_make_ep_list layout (no behaviour)."""
    return {
        'callback': 'core_cb_start',
        'callback_va': 0x10F0,
        'make_ep_list_va': 0x2BC,
        'make_ep_list_size': 128,
        'context_fields': dict(USB_VIDEO_EP_LIST_CONTEXT_FIELDS),
        'this_ex_ep_id_offset': USB_VIDEO_THIS_EX_EP_ID_OFFSET,
        'context_count_offset': USB_VIDEO_CONTEXT_COUNT_OFFSET,
        'count_writer': 'unresolved (no store in usbg_video/usbg_cmn text)',
        'evidence': 'usbg_video core_cb_start + usbg_cmn_make_ep_list '
                    'disassembly (a6400 usbg_cmn make_ep_list identical '
                    'symbol/size)',
    }


# ---------------------------------------------------------------------------
# usb_sync_alloc_phys_buffer / usb_sync_free_phys_buffer = OSAL RPC (E0319 s12)
# usbg_video.ko local copies: alloc 0x2988 (292 B), free 0x2AAC (228 B).
# Message size 0x18; dynamic-id calls osal_dynamic_id(0x2a=42 acquire,
# 0x4a=74 release); reply status at +2, length at +4, physical at +0x10,
# virtual at +0x14.
# ---------------------------------------------------------------------------
USB_VIDEO_PHYS_BUFFER_RPC = {
    'message_size': 0x18,
    'alloc_opcode': 1,
    'free_opcode': 4,
    'reply_status_offset': 0x02,
    'reply_length_offset': 0x04,
    'reply_physical_offset': 0x10,
    'reply_virtual_offset': 0x14,
    'alloc_message_fields': {
        0x00: 'opcode_u16 (=1)',
        0x02: 'flags_u16 (=0)',
        0x04: 'size_u32',
        0x08: 'zero_u32',
        0x0C: 'timeout_u32 (=0xFFFFFFFF)',
        0x14: 'zero_u16',
        0x16: 'flags_u16 (=1)',
    },
    'free_message_fields': {
        0x00: 'opcode_u16 (=4)',
        0x02: 'handle_u16',
        0x14: 'zero_u16',
        0x16: 'flags_u16 (=2)',
    },
    'dynamic_id_acquire': 0x2A,
    'dynamic_id_release': 0x4A,
    'open_call_tag': 0x2DA,
    'open_call_size': 0x50E,
}


def describe_usbg_video_phys_buffer_rpc():
    """Return the decoded physical-buffer RPC ABI (no kernel call modelled)."""
    return {
        'rpc': {key: (dict(value) if isinstance(value, dict) else value)
                for key, value in USB_VIDEO_PHYS_BUFFER_RPC.items()},
        'functions': {
            'usb_sync_alloc_phys_buffer': {'va': 0x2988, 'size': 292},
            'usb_sync_free_phys_buffer': {'va': 0x2AAC, 'size': 228},
        },
        'open_usage': 'usbg_video_core_open calls alloc(tag=0x2DA, size=0x50E, '
                      '&length, &physical, &virtual)',
        'evidence': 'usbg_video.ko local copies + usbg_cmn.ko exports; '
                    'reply field offsets are instruction-level observations',
    }
