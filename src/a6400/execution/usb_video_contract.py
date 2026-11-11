"""Evidence-bound ZV-E10 usbg_video contract constants (E0319/E0316).

This module only describes the ZV-E10 2.03 UVC video kernel-driver ABI that was
decoded offline from `usbg_video.ko` (SHA-256 d385a051...).  It does not model
the driver's runtime behaviour and returns no fabricated success: the command
decoder is a pure ``_IOC``/legacy-command description and the context offsets
are the fields observed in `usbg_video_core_ioctl`.

The E0319 gap decoders below (context+0x2D count writer, 0xD0 request object,
0x24 DMA-info object, buffer table/blob semantics, JPEG/DMM frame source) are
also structural: every field whose meaning is not directly observed is labelled
``unresolved`` and every parser rejects short/mismatched input instead of
inventing defaults.
"""

import struct

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


# ---------------------------------------------------------------------------
# E0319 gap decoders (task-186).
#
# Gaps left open by E0319 §10/§11 and §9:
#   * context+0x2D buffer-table count writer (external)
#   * 0xD0 request object (context+0xAC)
#   * 0x24 DMA-info object (context+0xB0)
#   * buffer-table/blob contents (probe info +0x24/+0x30/+0x34)
#   * JPEG/DMM frame source
#
# Nothing below claims driver behaviour: structures are described field by
# field, unknown fields are labelled ``unresolved``, and builders/parsers are
# fail-closed (ValueError on short/mismatched/out-of-range input).
# ---------------------------------------------------------------------------
USB_VIDEO_CONTEXT_COUNT_WRITER = {
    'context_offset': USB_VIDEO_CONTEXT_COUNT_OFFSET,
    'writer': 'unresolved_external',
    'stores_in_module_text': 0,
    'checked_sources': ('usbg_video.ko .text', 'usbg_cmn.ko .text'),
    'context_zeroed_bytes': 0xC0,  # usbg_video_create_this zeroes the 0xC0 context
    'note': 'usbg_cmn_copy_probe_info reads count from context+0x2D; no store '
            '(or covering 32-bit store) exists in usbg_video/usbg_cmn text, so '
            'the writer is another module (kernel gadgetcore) or a copied user '
            'structure that was not located (E0319 §10/§11)',
}


def describe_usb_video_count_writer():
    """Return the context+0x2D count-writer boundary (no writer modelled)."""
    return dict(USB_VIDEO_CONTEXT_COUNT_WRITER)


# 0xD0 request object allocated by usbg_video_core_open; context+0xAC points at
# it.  No field semantics were decoded from the module text in E0319.
USB_VIDEO_REQUEST_OBJECT = {
    'context_offset': 0xAC,
    'size': 0xD0,
    'known_fields': {},
    'unknown_field_label': 'unresolved_word',
    'evidence': 'usbg_video_core_open (0x1AC8) allocates a 0xD0-byte request '
                'object and stores it at context+0xAC; contents undecoded',
}
# 0x24 DMA-info object allocated by usbg_video_core_open; context+0xB0 points at
# it.  E0319 §9 records field values [0]=1, [4]=1, [8]=adjusted physical,
# [0xC]/[0x10] literals; the literal values themselves stay unresolved.
USB_VIDEO_DMA_INFO_OBJECT = {
    'context_offset': 0xB0,
    'size': 0x24,
    'fields': {
        0x00: 'constant_1_observed',
        0x04: 'constant_1_observed',
        0x08: 'adjusted_physical_address',
        0x0C: 'unresolved_literal_word',
        0x10: 'unresolved_literal_word',
        0x14: 'unresolved_word',
        0x18: 'unresolved_word',
        0x1C: 'unresolved_word',
        0x20: 'unresolved_word',
    },
    'evidence': 'usbg_video_core_open (0x1AC8) object stores; literal values of '
                '+0xC/+0x10 are not present in the decoded notes',
}
# usbg_cmn_copy_probe_info copies count*2 bytes from user+0x24 into a kernel
# buffer; the per-entry meaning is not decoded (entry width is a hypothesis
# derived from the count*2 copy size).
USB_VIDEO_BUFFER_TABLE_ENTRY_SIZE = 2
USB_VIDEO_BUFFER_TABLE_MAX_ENTRIES = 0x100  # caller-supplied sanity cap
USB_VIDEO_BLOB_MAX_BYTES = 0x4000  # caller-supplied sanity cap

USB_VIDEO_FRAME_SOURCE = {
    'status': 'unresolved',
    'kinds': {
        'jpeg': 'hypothesis: JPEG payload source; no producer decoded',
        'dmm': 'hypothesis: DMM media frame source; no producer decoded',
    },
    'evidence': 'no frame-source instruction or data structure was decoded in '
                'usbg_video.ko/usbg_cmn.ko; frame data flow is not modelled',
}


def _require_bytes(data, label):
    if not isinstance(data, (bytes, bytearray)):
        raise ValueError(f'{label} must be bytes')
    return bytes(data)


def parse_usb_video_request_object(data):
    """Parse the 0xD0-byte request object (all words labelled unresolved).

    ``usbg_video_core_open`` allocates it and stores the pointer at
    context+0xAC; E0319 did not decode any field, so every word is returned
    with the ``unresolved_word`` label and ``known_fields`` stays empty.
    """
    data = _require_bytes(data, 'usb_video request object')
    size = USB_VIDEO_REQUEST_OBJECT['size']
    if len(data) < size:
        raise ValueError('usb_video request object must be at least 0xD0 bytes')
    words = struct.unpack_from(f'<{size // 4}I', data, 0)
    return {
        'size': size,
        'context_offset': USB_VIDEO_REQUEST_OBJECT['context_offset'],
        'known_fields': {},
        'words': list(words),
        'labels': {offset: USB_VIDEO_REQUEST_OBJECT['unknown_field_label']
                   for offset in range(0, size, 4)},
        'semantics': 'unresolved',
    }


def parse_usb_video_dma_info_object(data):
    """Parse the 0x24-byte DMA-info object with the E0319 §9 labels."""
    data = _require_bytes(data, 'usb_video dma-info object')
    size = USB_VIDEO_DMA_INFO_OBJECT['size']
    if len(data) < size:
        raise ValueError('usb_video dma-info object must be at least 0x24 bytes')
    fields = {}
    for offset, label in USB_VIDEO_DMA_INFO_OBJECT['fields'].items():
        (value,) = struct.unpack_from('<I', data, offset)
        entry = {'label': label, 'value': value}
        if offset in (0x00, 0x04):
            entry['expectation'] = 1
        fields[offset] = entry
    return {
        'size': size,
        'context_offset': USB_VIDEO_DMA_INFO_OBJECT['context_offset'],
        'fields': fields,
        'raw': data[:size].hex(),
        'semantics': 'field labels observed in usbg_video_core_open; '
                     'literal values at +0xC/+0x10 unresolved',
    }


def parse_usb_video_buffer_table(data, expected_count,
                                 max_entries=USB_VIDEO_BUFFER_TABLE_MAX_ENTRIES):
    """Parse the count*2-byte buffer table copied from user+0x24.

    ``usbg_cmn_copy_probe_info`` allocates ``count*2`` bytes (count from
    context+0x2D) and copies the user table; the per-entry meaning is not
    decoded, so entries are exposed as 16-bit little-endian hypotheses.
    """
    data = _require_bytes(data, 'usb_video buffer table')
    if not isinstance(expected_count, int) or expected_count < 0:
        raise ValueError('expected_count must be a non-negative int')
    if expected_count > max_entries:
        raise ValueError('expected_count exceeds the caller-supplied max_entries')
    expected_bytes = expected_count * USB_VIDEO_BUFFER_TABLE_ENTRY_SIZE
    if len(data) != expected_bytes:
        raise ValueError(
            f'usb_video buffer table must be exactly {expected_bytes} bytes '
            f'for count {expected_count}, got {len(data)}')
    entries = [int.from_bytes(data[i:i + USB_VIDEO_BUFFER_TABLE_ENTRY_SIZE],
                              'little')
               for i in range(0, expected_bytes,
                              USB_VIDEO_BUFFER_TABLE_ENTRY_SIZE)]
    return {
        'count': expected_count,
        'entry_size': USB_VIDEO_BUFFER_TABLE_ENTRY_SIZE,
        'entries': entries,
        'entry_semantics': 'unresolved (u16 little-endian hypothesis from the '
                           'count*2 copy size)',
        'count_source': 'context+0x2D (external writer unresolved)',
    }


def parse_usb_video_blob(data, max_bytes=USB_VIDEO_BLOB_MAX_BYTES):
    """Validate the probe-info blob bytes; content semantics stay unresolved.

    ``usbg_cmn_copy_probe_info`` allocates user+0x34 bytes and copies from
    user+0x30; a NULL user+0x30 clears the blob.  The content meaning is not
    decoded, so only a bounded length check plus the raw bytes are returned.
    """
    data = _require_bytes(data, 'usb_video blob')
    if not isinstance(max_bytes, int) or max_bytes < 0:
        raise ValueError('max_bytes must be a non-negative int')
    if len(data) > max_bytes:
        raise ValueError('usb_video blob exceeds max_bytes')
    return {
        'length': len(data),
        'data_hex': data.hex(),
        'semantics': 'unresolved (contents not decoded)',
        'max_bytes': max_bytes,
    }


def validate_usb_video_probe_info(data, buffer_count=None,
                                  max_blob_bytes=USB_VIDEO_BLOB_MAX_BYTES,
                                  max_entries=USB_VIDEO_BUFFER_TABLE_MAX_ENTRIES):
    """Parse the 56-byte register block and validate its cross-field bounds.

    This is a decoder, not a kernel-behaviour model: it returns the parsed
    fields plus explicit validation flags and never fabricates a successful
    register/commit.  ``buffer_count`` is the context+0x2D value when known
    (the writer is external/unresolved); a mismatch is reported, not corrected.
    """
    parsed = parse_usb_video_probe_info(data)
    if buffer_count is not None:
        if not isinstance(buffer_count, int) or buffer_count < 0:
            raise ValueError('buffer_count must be a non-negative int')
        if buffer_count > max_entries:
            raise ValueError('buffer_count exceeds the caller-supplied max_entries')
    blob_pointer = parsed['blob_pointer']
    blob_length = parsed['blob_length']
    if blob_pointer == 0 and blob_length != 0:
        raise ValueError('blob_pointer 0 with non-zero blob_length is inconsistent')
    if blob_pointer != 0 and blob_length > max_blob_bytes:
        raise ValueError('blob_length exceeds max_blob_bytes')
    expected_table_bytes = (buffer_count * USB_VIDEO_BUFFER_TABLE_ENTRY_SIZE
                            if buffer_count is not None else None)
    return {
        'probe_info': parsed,
        'buffer_count': buffer_count,
        'expected_buffer_table_bytes': expected_table_bytes,
        'blob_present': blob_pointer != 0,
        'blob_length': blob_length,
        'flags': {
            'buffer_table_size_checked': buffer_count is not None,
            'count_source': 'context+0x2D (external writer unresolved)',
        },
        'semantics': 'decoded register block only; no register/commit success '
                     'is modelled',
    }


def build_usb_video_phys_buffer_alloc_message(size):
    """Build the 0x18-byte alloc RPC message (E0319 §12 field layout)."""
    if not isinstance(size, int) or size < 0 or size > 0xFFFFFFFF:
        raise ValueError('size must fit u32')
    message = bytearray(0x18)
    struct.pack_into('<H', message, 0x00, USB_VIDEO_PHYS_BUFFER_RPC['alloc_opcode'])
    struct.pack_into('<H', message, 0x02, 0)
    struct.pack_into('<I', message, 0x04, size)
    struct.pack_into('<I', message, 0x08, 0)
    struct.pack_into('<I', message, 0x0C, 0xFFFFFFFF)
    struct.pack_into('<H', message, 0x14, 0)
    struct.pack_into('<H', message, 0x16, 1)
    return bytes(message)


def build_usb_video_phys_buffer_free_message(handle):
    """Build the 0x18-byte free RPC message (E0319 §12 field layout)."""
    if not isinstance(handle, int) or not 0 <= handle <= 0xFFFF:
        raise ValueError('handle must fit u16')
    message = bytearray(0x18)
    struct.pack_into('<H', message, 0x00, USB_VIDEO_PHYS_BUFFER_RPC['free_opcode'])
    struct.pack_into('<H', message, 0x02, handle)
    struct.pack_into('<H', message, 0x14, 0)
    struct.pack_into('<H', message, 0x16, 2)
    return bytes(message)


def parse_usb_video_phys_buffer_reply(data):
    """Parse a 0x18-byte alloc/free reply (status/length/physical/virtual)."""
    data = _require_bytes(data, 'usb_video phys-buffer reply')
    size = USB_VIDEO_PHYS_BUFFER_RPC['message_size']
    if len(data) < size:
        raise ValueError('usb_video phys-buffer reply must be at least 0x18 bytes')
    rpc = USB_VIDEO_PHYS_BUFFER_RPC
    (status,) = struct.unpack_from('<H', data, rpc['reply_status_offset'])
    (length,) = struct.unpack_from('<H', data, rpc['reply_length_offset'])
    (physical,) = struct.unpack_from('<I', data, rpc['reply_physical_offset'])
    (virtual,) = struct.unpack_from('<I', data, rpc['reply_virtual_offset'])
    return {
        'size': size,
        'status_u16': status,
        'length_u16': length,
        'physical': physical,
        'virtual': virtual,
        'raw': data[:size].hex(),
        'semantics': 'reply field offsets are E0319 §12 instruction-level '
                     'observations; no kernel call is modelled',
    }


def usb_video_frame_source(kind):
    """Return the declared frame-source row for ``kind`` (never modelled).

    Both known kinds are hypotheses; an unknown kind raises ValueError so a
    caller cannot silently treat an arbitrary source as supported.
    """
    if kind not in USB_VIDEO_FRAME_SOURCE['kinds']:
        raise ValueError(f'unknown usb_video frame-source kind: {kind!r}')
    return {
        'kind': kind,
        'status': USB_VIDEO_FRAME_SOURCE['status'],
        'modelled': False,
        'note': USB_VIDEO_FRAME_SOURCE['kinds'][kind],
        'evidence': USB_VIDEO_FRAME_SOURCE['evidence'],
    }


def describe_usbg_video_gap_contract():
    """Aggregate the remaining E0319 gaps as an explicit, fail-closed report."""
    return {
        'context_count_writer': describe_usb_video_count_writer(),
        'request_object': {key: (dict(value) if isinstance(value, dict) else value)
                           for key, value in USB_VIDEO_REQUEST_OBJECT.items()},
        'dma_info_object': {
            'context_offset': USB_VIDEO_DMA_INFO_OBJECT['context_offset'],
            'size': USB_VIDEO_DMA_INFO_OBJECT['size'],
            'fields': dict(USB_VIDEO_DMA_INFO_OBJECT['fields']),
        },
        'buffer_table': {
            'entry_size': USB_VIDEO_BUFFER_TABLE_ENTRY_SIZE,
            'max_entries': USB_VIDEO_BUFFER_TABLE_MAX_ENTRIES,
            'semantics': 'unresolved (count*2 copy; per-entry meaning not '
                         'decoded)',
        },
        'blob': {
            'max_bytes': USB_VIDEO_BLOB_MAX_BYTES,
            'semantics': 'unresolved (user+0x30/+0x34 copy; contents not '
                         'decoded)',
        },
        'frame_source': {
            'status': USB_VIDEO_FRAME_SOURCE['status'],
            'kinds': dict(USB_VIDEO_FRAME_SOURCE['kinds']),
        },
        'evidence': 'E0319 §9-§12 instruction-level observations; fields that '
                    'were not decoded are labelled unresolved and parsers/'
                    'builders fail closed',
    }
