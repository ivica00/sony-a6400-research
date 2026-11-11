"""Decoded kernel-origin sync-callback packet formats (E0333).

Evidence-derived constants and pure decoders/builders for the two ``flags=1``
UIPC sync registrations in the live a6400 8.2.6.0 checkpoint
``boot-e0673-live-full2e.ckpt``:

=========================  ==========  ==============================
handle  queue              callback
=========================  ==========  ==============================
4109    0x00CA0288         UFW::AdjBase::funcOsalSyncCb
4110    0x00CA01A4         UsbControl::funcInputGetCb
=========================  ==========  ==============================

What is *verified* (offline: live-lib capture + checkpoint memory, see
``docs/evidence/0333-sync-callback-packet-format.md``):

* live ``libUsbControl.so`` (94,176 B, SHA-256 below) loads at
  ``0x56440000`` in the checkpoint; callback VA minus base equals the
  ``.dynsym`` function offset:
  - 4109: ``0x5644B0DF - 0x56440000 = 0xB0DF`` =
    ``_ZN3UFW7AdjBase14funcOsalSyncCbEPvS1_`` (156 B),
  - 4110: ``0x56452A87 - 0x56440000 = 0x12A87`` =
    ``_ZN10UsbControl14funcInputGetCbEPvS0_`` (108 B).
* the original ``libosal_uipc.so`` sync dispatcher (Thumb 0x3168, installed
  as ``[registration+8]``) calls
  ``callback(msg_payload, registered_user_data)`` where
  ``msg_payload = osal_message_head + 0xC``
  (``__osal_snd_sync_msg`` at 0x3DB0 -> ``[record+8]``; dispatcher
  instructions at 0x3178/0x317A/0x317E execute
  ``ldr r3,[r5,#0x14]; add r0,r6,#0xC; ldr r1,[r5,#0x18]; blx r3``).
* 4109's user_data is the static ``UsbAdjCmd`` instance in libUsbControl
  ``.bss`` (live 0x5645EA98 = base+0x1EA98, vptr ``_ZTV9UsbAdjCmd+8``,
  ``+4 = 0x0701``, ``+8 = handle 4109``, ``+0xC = queue 0x00CA0288``), built
  by ``UsbAdjCmd::UsbAdjCmd()`` at 0xFC90
  (``movw r1,#0x701``; queue literal ``0x00CA0288`` at file 0xFCB0;
  ``AdjBase::AdjBase(uint16,uint32)`` at 0xB1BC registers
  ``osal_reg_sync_msg_queue_cb(queue, &this+8, callback, this)``).
* 4110's user_data is the heap ``UsbControl`` singleton (live 0x2E1B0, vptr
  ``_ZTV10UsbControl+8``) created by ``UsbControl_Init`` (0x10255) and
  registered in ``UsbControl::PreInit`` (0x1045C): queue literal
  ``0x00CA01A4`` at 0x10498 -> ``&this+0xB4`` (holds handle 4110); the same
  function registers callback ``UsbControl::funcOsalSyncCb`` (0x1261C,
  forwards to ``UsbControl::preProcess`` 0x123B4) on the *local* queue
  ``0x00CA8192`` (bit 15 set) -> ``&this+0x84``.

Consequence (corrects the E0332 expectation): neither callback constructs an
``MWF::ObjMsg`` or posts into queue 0x00CA8192.  Both are synchronous packet
transforms: request bytes in, response bytes written back into the same
message buffer by ``funcOsalSyncCb`` (``memcpy(msg, response, 0x140)`` at
0xB166), then the OSAL sync sender unblocks.  The E0332 injection of an
ObjMsg envelope into 0x00CA0288 therefore hit the decoded mismatch path
(``ldrh [msg+0x18] != 0x0701 -> result byte 0x81``) and produced no
downstream message, exactly as observed.

The functions here are pure (no emulator, firmware, filesystem or network
access at import time) and fail closed with ``ValueError`` on any layout the
evidence does not cover.
"""

from __future__ import annotations

import struct

# ---------------------------------------------------------------------------
# Input provenance (no firmware files are read at import time).
# ---------------------------------------------------------------------------
#: live libUsbControl.so captured from the running 8.2.6.0 app
#: (artifacts/hardware/live-libs/capture-manifest.json).
LIVE_LIBUSBCONTROL_SHA256 = (
    'b5cea9d2c92a0b0810353900871fa2806ca3064aa5d8cf3ca7db5ddb6f3940e2')
LIVE_LIBUSBCONTROL_SIZE = 94176
#: live libosal_uipc.so captured in the same session.
LIVE_LIBOSAL_UIPC_SHA256 = (
    'eecc322b81ebf63b26829fb2e8beee43af56f571b0ffbfc16d234dee5063becf')
LIVE_LIBOSAL_UIPC_SIZE = 26644
#: libUsbControl load base recorded in the e0684 checkpoint mapping table
#: (``/usr/lib/libUsbControl.so`` text at 0x56440000, data page at
#: 0x5645E000, both in boot-e0673/e0684 checkpoints).
LIVE_LIBUSBCONTROL_BASE = 0x56440000
LIVE_LIBUSBCONTROL_DATA_BASE = 0x5645E000
#: libUsbControl .bss VA range (ELF VA 0x1EA7C..0x1EAC8).
LIVE_LIBUSBCONTROL_BSS_VA = 0x1EA7C
LIVE_LIBUSBCONTROL_BSS_END = 0x1EAC8

# ---------------------------------------------------------------------------
# Sync callback ABI (libosal_uipc 8.2.5.7 symbols; same offsets are used by the
# live libosal_uipc.so, whose dispatcher is reachable through
# ``[registration+8]`` = Thumb 0x3169).
# ---------------------------------------------------------------------------
#: callback(message_payload, user_data)
SYNC_CALLBACK_ABI = {
    'arg0': 'message_payload',
    'arg1': 'registered_user_data',
    'payload_from_message_head': 0x0C,
    'evidence': (
        'libosal_uipc.so internal dispatcher Thumb 0x3168: '
        'ldr r3,[r5,#0x14] (registered callback field), '
        'add r0,r6,#0xC (message head + 0xC = payload), '
        'ldr r1,[r5,#0x18] (registered user_data), blx r3'),
}
SYNC_DISPATCHER_THUMB_VA = 0x3168
OSAL_FINISH_SYNC_CB_THUMB_VA = 0x3D44
OSAL_SND_SYNC_MSG_THUMB_VA = 0x3DB0
OSAL_REG_SYNC_MSG_QUEUE_CB_THUMB_VA = 0x3AE0
OSAL_REG_MSG_QUEUE_CB_THUMB_VA = 0x4300
#: OSAL sync-callback record fields used by the dispatcher/registration.
OSAL_SYNC_CB_RECORD_FIELDS = {
    0x08: 'internal_dispatcher',
    0x0C: 'activity_count_u8',
    0x0D: 'flags_u8 (bit0 used, bit1, bit2, bit3 direct-cb)',
    0x10: 'owner_tls_pointer',
    0x14: 'registered_callback',
    0x18: 'registered_user_data',
}
#: The kernel lane is selected by bit 15 of the queue id: clear = kernel/UIPC
#: ioctl message (u_osal_*), set = process-local user-space queue object.
UIPC_LOCAL_QUEUE_BIT = 0x8000

# ---------------------------------------------------------------------------
# The two live registrations.
# ---------------------------------------------------------------------------
H4109_QUEUE = 0x00CA0288
H4109_HANDLE = 4109
H4109_CALLBACK_VA = 0x5644B0DF
H4109_CALLBACK_OFFSET = H4109_CALLBACK_VA - LIVE_LIBUSBCONTROL_BASE  # 0xB0DF
H4109_CALLBACK_SYMBOL = '_ZN3UFW7AdjBase14funcOsalSyncCbEPvS1_'
H4109_CALLBACK_SIZE = 156
H4109_USER_DATA = 0x5645EA98  # static UsbAdjCmd instance (BSS+0x1C)
H4109_UPDATE_OFFSET = H4109_USER_DATA - LIVE_LIBUSBCONTROL_BASE  # 0x1EA98
H4109_PACKET_ID = 0x0701
H4109_PACKET_CLASS = 'UFW::OsalRequestPacket (0x140-byte sync request)'

H4110_QUEUE = 0x00CA01A4
H4110_HANDLE = 4110
H4110_CALLBACK_VA = 0x56452A87
H4110_CALLBACK_OFFSET = H4110_CALLBACK_VA - LIVE_LIBUSBCONTROL_BASE  # 0x12A87
H4110_CALLBACK_SYMBOL = '_ZN10UsbControl14funcInputGetCbEPvS0_'
H4110_CALLBACK_SIZE = 108
H4110_USER_DATA = 188848  # 0x2E1B0 heap UsbControl singleton
H4110_PACKET_CLASS = 'UsbControl input-get sync message (>= 0x14 bytes)'

#: Local queue registration made by UsbControl::PreInit in addition to 4110.
USB_CONTROL_LOCAL_SYNC_QUEUE = 0x00CA8192
USB_CONTROL_LOCAL_SYNC_CALLBACK = 0x1261C  # -> UsbControl::preProcess (0x123B4)
USB_CONTROL_LOCAL_SYNC_CALLBACK_SYMBOL = '_ZN10UsbControl14funcOsalSyncCbEPvS0_'

SYNC_CALLBACK_REGISTRATIONS = {
    H4109_HANDLE: {
        'queue': H4109_QUEUE,
        'queue_lane': 'kernel (bit15 clear)',
        'callback_va': H4109_CALLBACK_VA,
        'callback_offset': H4109_CALLBACK_OFFSET,
        'callback_symbol': H4109_CALLBACK_SYMBOL,
        'callback_demangled': 'UFW::AdjBase::funcOsalSyncCb(void*, void*)',
        'callback_size': H4109_CALLBACK_SIZE,
        'user_data': H4109_USER_DATA,
        'user_data_kind': (
            'static UsbAdjCmd instance at libUsbControl BSS+0x1C; '
            'vptr = _ZTV9UsbAdjCmd+8; object+4 = expected packet id 0x0701; '
            'object+8 = handle 4109; object+0xC = queue 0x00CA0288'),
        'flags': 1,
        'packet_class': H4109_PACKET_CLASS,
        'registration_site': (
            'UsbAdjCmd::UsbAdjCmd() 0xFC90 -> AdjBase::AdjBase(uint16,uint32) '
            '0xB1BC -> osal_reg_sync_msg_queue_cb(0x00CA0288, &obj+8, '
            'funcOsalSyncCb, obj)'),
    },
    H4110_HANDLE: {
        'queue': H4110_QUEUE,
        'queue_lane': 'kernel (bit15 clear)',
        'callback_va': H4110_CALLBACK_VA,
        'callback_offset': H4110_CALLBACK_OFFSET,
        'callback_symbol': H4110_CALLBACK_SYMBOL,
        'callback_demangled': 'UsbControl::funcInputGetCb(void*, void*)',
        'callback_size': H4110_CALLBACK_SIZE,
        'user_data': H4110_USER_DATA,
        'user_data_kind': (
            'heap UsbControl singleton at 0x2E1B0 (vptr _ZTV10UsbControl+8); '
            'handle stored at singleton+0xB4 by UsbControl::PreInit'),
        'flags': 1,
        'packet_class': H4110_PACKET_CLASS,
        'registration_site': (
            'UsbControl::PreInit 0x1045C -> osal_reg_sync_msg_queue_cb('
            '0x00CA01A4, &this+0xB4, funcInputGetCb, this)'),
    },
}


def describe_sync_callback(handle):
    """Return the decoded registration/method identity for one handle.

    Raises ValueError for any handle that is not one of the two decoded
    kernel-origin sync registrations.
    """
    if isinstance(handle, bool) or not isinstance(handle, int):
        raise ValueError(
            'sync callback handle must be an integer, got %r' % (handle,))
    try:
        return dict(SYNC_CALLBACK_REGISTRATIONS[handle])
    except KeyError:
        raise ValueError(
            'unknown sync callback handle %r; decoded handles are %s'
            % (handle, sorted(SYNC_CALLBACK_REGISTRATIONS))) from None


# ---------------------------------------------------------------------------
# h4109: UFW::AdjBase::funcOsalSyncCb / UsbAdjCmd packet format.
#
# Decoded from the live libUsbControl.so function at 0xB0DF (Thumb 0xB0DE):
#   0xB0E8 ldrh r2,[r0,#0x18]   ; request packet id
#   0xB0EA ldrh r3,[r1,#4]      ; object expected id (0x0701)
#   0xB0EC cmp  r2,r3
#   0xB0F0..0xB0F4 mismatch -> strb 0x81,[r0,#1]; return
#   0xB0F6..0xB100 memcpy(sp,msg,0x140)
#   0xB10C..0xB11C zero response header/payload (0x130 bytes at +0x10)
#   0xB120 ldrb r3,[r4]         ; request phase byte
#   0xB12A cmp  #1 / 0xB124 cmp #4 / 0xB126 cmp #0x10
#   0xB136/B144/B15A ldr r3,[r5] vtable of user_data object, slot +8/+0xC/+0x10
#   0xB148..0xB14E handler(r0=user_data, r1=request, r2=response)
#   0xB166 memcpy(msg,response,0x140)
# The user_data object's vtable is _ZTV9UsbAdjCmd (slot +8 =
# process_start_exec 0x100DA, +0xC = AdjBase::finish_send_data_exec 0xB0D2
# no-op, +0x10 = AdjBase::finish_receive_data_exec 0xB0D8 no-op).
# ---------------------------------------------------------------------------
ADJ_PACKET_SIZE = 0x140
ADJ_PHASE_OFFSET = 0x00
ADJ_RESULT_OFFSET = 0x01
ADJ_ECHO_OFFSET = 0x02
ADJ_HEADER_END = 0x10
ADJ_PACKET_ID_OFFSET = 0x18
ADJ_SUBCOMMAND_OFFSET = 0x1A
ADJ_ARG_OFFSET = 0x1C
ADJ_DATA_OFFSET = 0x1D
ADJ_RESPONSE_VALUE_OFFSET = 0x0C
ADJ_RESPONSE_PAYLOAD_OFFSET = 0x10
ADJ_PACKET_ID = H4109_PACKET_ID

#: request phase byte -> (response type byte, vtable slot, handler class)
ADJ_PHASES = {
    0x01: {'name': 'process_start', 'response_type': 0x08, 'vtable_slot': 8,
           'handler_kind': 'UsbAdjCmd::process_start_exec'},
    0x04: {'name': 'finish_send_data', 'response_type': 0x08, 'vtable_slot': 0x0C,
           'handler_kind': 'AdjBase::finish_send_data_exec (no-op in UsbAdjCmd)'},
    0x10: {'name': 'finish_receive_data', 'response_type': 0x20,
           'vtable_slot': 0x10,
           'handler_kind': 'AdjBase::finish_receive_data_exec (no-op in UsbAdjCmd)'},
}
#: result byte written into response+1.
ADJ_RESULT_DISPATCHED = 0x80  # set by funcOsalSyncCb before dispatch
ADJ_RESULT_OK = 0x01          # handler reported success
ADJ_RESULT_ID_MISMATCH = 0x81  # packet id != object+4 (or handler arg reject)
ADJ_RESULT_ERROR = 0x82       # handler error / unknown phase
ADJ_RESULT_NAMES = {
    ADJ_RESULT_DISPATCHED: 'dispatched_no_handler_result',
    ADJ_RESULT_OK: 'ok',
    ADJ_RESULT_ID_MISMATCH: 'rejected',
    ADJ_RESULT_ERROR: 'error',
}

#: request+0x1A subcommand -> UsbAdjCmd::process_start_exec tail target
#: (tbb table at 0x100EA = 04 08 0c 10 14 18 1c; targets resolved through
#: .rel.plt: 0x9EF8, 0x9624, 0x9384, 0x98B4, 0x95FC, 0x949C, 0x9B24).
ADJ_SUBCOMMANDS = {
    0x01: {
        'name': 'usb_serial_dat_process_start',
        'offset': 0xFD79,
        'arg': 'req+0x1C: 0 -> serial-dat read path, 1 -> serial-dat write path',
    },
    0x02: {
        'name': 'usb_set_port_process_start',
        'offset': 0xFDA1,
        'arg': 'req+0x1C: port selector (1 << arg must intersect 0x0003FDFF)',
    },
    0x03: {
        'name': 'usb_get_port_process_start',
        'offset': 0xFE05,
        'arg': 'none (returns port in response+0xC, port data in response+0x10)',
    },
    0x04: {
        'name': 'usb_test_vbus_process_start',
        'offset': 0xFE71,
        'arg': 'req+0x1C mode 0/1/2; req+0x1D/0x1E extra bytes; response+0x10/0x11',
    },
    0x05: {
        'name': 'sysad_sel_process_start',
        'offset': 0xFFC5,
        'arg': 'req+0x1C byte selector (execSysAdSel)',
    },
    0x06: {
        'name': 'write_customer_hash256_process_start',
        'offset': 0x10041,
        'arg': 'req+0x1C: 64 hex chars (32-byte hash) + NUL, 0x41 bytes checked',
    },
    0x07: {
        'name': 'usb_buspower_supply_control_process_start',
        'offset': 0x100C1,
        'arg': 'req+0x1C byte 0/1 (execBsprwSpplyCtrl)',
    },
}

ADJ_FUNCTION_OFFSETS = {
    'UFW::AdjBase::funcOsalSyncCb': 0xB0DF,
    'UFW::AdjBase::AdjBase(uint16,uint32)': 0xB1BD,
    'UFW::AdjBase::finish_send_data_exec': 0xB0D3,
    'UFW::AdjBase::finish_receive_data_exec': 0xB0D9,
    'UsbAdjCmd::UsbAdjCmd()': 0xFC91,
    'UsbAdjCmd::process_start_exec': 0x100DB,
    'UsbControl_Init': 0x10255,
    'UsbControl::PreInit': 0x1045D,
    'UsbControl::preProcess': 0x123B5,
}


def decode_adj_request_packet(payload):
    """Decode the h4109 sync request packet (``OsalRequestPacket``, 0x140 B).

    Returns a dict with phase/result/packet-id/subcommand/argument fields and
    the decoded handler identity.  Raises ``ValueError`` when the buffer is
    shorter than the 0x140 bytes the callback copies, when the phase byte is
    not one of the three decoded phases, or (for phase 1) when the subcommand
    is outside the decoded 1..7 dispatch table.
    """
    raw = bytes(payload)
    if len(raw) < ADJ_PACKET_SIZE:
        raise ValueError(
            'h4109 request packet too short: %d < 0x140 bytes' % len(raw))
    phase = raw[ADJ_PHASE_OFFSET]
    if phase not in ADJ_PHASES:
        raise ValueError(
            'unknown h4109 request phase 0x%02x; decoded phases are %s'
            % (phase, sorted(ADJ_PHASES)))
    packet_id = struct.unpack_from('<H', raw, ADJ_PACKET_ID_OFFSET)[0]
    subcommand = struct.unpack_from('<H', raw, ADJ_SUBCOMMAND_OFFSET)[0]
    argument = raw[ADJ_ARG_OFFSET]
    info = ADJ_PHASES[phase]
    handler = None
    if phase == 0x01:
        if subcommand not in ADJ_SUBCOMMANDS:
            raise ValueError(
                'unknown h4109 subcommand 0x%04x; decoded subcommands are %s'
                % (subcommand, sorted(ADJ_SUBCOMMANDS)))
        handler = dict(ADJ_SUBCOMMANDS[subcommand])
    return {
        'packet_class': H4109_PACKET_CLASS,
        'packet_size': ADJ_PACKET_SIZE,
        'phase': phase,
        'phase_name': info['name'],
        'packet_id': packet_id,
        'expected_packet_id': ADJ_PACKET_ID,
        'id_matches': packet_id == ADJ_PACKET_ID,
        'subcommand': subcommand if phase == 0x01 else None,
        'subcommand_argument': argument if phase == 0x01 else None,
        'handler': handler,
        'response_type': info['response_type'],
        'response_value_offset': ADJ_RESPONSE_VALUE_OFFSET,
        'response_payload_offset': ADJ_RESPONSE_PAYLOAD_OFFSET,
    }


def decode_adj_response_packet(payload):
    """Decode the in-place h4109 response buffer written by the callback.

    The response reuses the request buffer: byte 0 is the response type, byte
    1 the result, bytes 2..0xF the echo/zeroed header and bytes 0x10..0x13F
    the handler payload (zeroed by the callback before dispatch).  Raises
    ``ValueError`` for short buffers or an unknown response type/result.
    """
    raw = bytes(payload)
    if len(raw) < ADJ_PACKET_SIZE:
        raise ValueError(
            'h4109 response packet too short: %d < 0x140 bytes' % len(raw))
    response_type = raw[0x00]
    valid_types = {info['response_type'] for info in ADJ_PHASES.values()}
    valid_types.add(0x00)  # unknown phase default branch
    if response_type not in valid_types:
        raise ValueError(
            'unknown h4109 response type 0x%02x; decoded types are %s'
            % (response_type, sorted(valid_types)))
    result = raw[ADJ_RESULT_OFFSET]
    if result not in ADJ_RESULT_NAMES:
        raise ValueError(
            'unknown h4109 result byte 0x%02x; decoded results are %s'
            % (result, sorted(ADJ_RESULT_NAMES)))
    return {
        'response_type': response_type,
        'result': result,
        'result_name': ADJ_RESULT_NAMES[result],
        'echo': struct.unpack_from('<H', raw, ADJ_ECHO_OFFSET)[0],
        'response_value': struct.unpack_from('<I', raw, ADJ_RESPONSE_VALUE_OFFSET)[0],
        'response_payload': raw[ADJ_RESPONSE_PAYLOAD_OFFSET:ADJ_PACKET_SIZE],
    }


def build_adj_request(phase, subcommand=None, argument=0, payload=b'',
                      payload_offset=ADJ_DATA_OFFSET, packet_id=ADJ_PACKET_ID):
    """Build a decoded h4109 request packet for a labelled experiment.

    This is the exact 0x140-byte ``OsalRequestPacket`` layout decoded in this
    module: phase byte at 0, zeroed header, packet id at 0x18, subcommand at
    0x1A, argument at 0x1C and caller bytes at ``payload_offset``.  It is a
    synthetic, explicitly labelled request (not a captured kernel message).
    Raises ``ValueError`` for any unsupported phase/subcommand/offset/length.
    """
    if phase not in ADJ_PHASES:
        raise ValueError('unsupported h4109 phase 0x%r' % (phase,))
    if not 0 <= int(argument) <= 0xFF:
        raise ValueError('h4109 argument must be a byte, got %r' % (argument,))
    data = bytes(payload)
    if phase == 0x01:
        if subcommand not in ADJ_SUBCOMMANDS:
            raise ValueError('unsupported h4109 subcommand %r' % (subcommand,))
    elif subcommand not in (None, 0):
        raise ValueError('subcommand only applies to phase 1')
    if payload_offset < 0 or payload_offset + len(data) > ADJ_PACKET_SIZE:
        raise ValueError(
            'payload range 0x%x..0x%x does not fit the 0x140-byte packet'
            % (payload_offset, payload_offset + len(data)))
    packet = bytearray(ADJ_PACKET_SIZE)
    packet[ADJ_PHASE_OFFSET] = phase
    struct.pack_into('<H', packet, ADJ_PACKET_ID_OFFSET, packet_id)
    if phase == 0x01:
        struct.pack_into('<H', packet, ADJ_SUBCOMMAND_OFFSET, subcommand)
        packet[ADJ_ARG_OFFSET] = int(argument)
    packet[payload_offset:payload_offset + len(data)] = data
    return bytes(packet)


def build_adj_process_start_request(subcommand, argument=0, payload=b'',
                                    payload_offset=ADJ_DATA_OFFSET):
    """Convenience wrapper: phase-1 request with the decoded packet id 0x0701."""
    return build_adj_request(0x01, subcommand=subcommand, argument=argument,
                             payload=payload, payload_offset=payload_offset)


# ---------------------------------------------------------------------------
# h4110: UsbControl::funcInputGetCb / input-get sync message.
#
# Decoded from the live libUsbControl.so function at 0x12A87 (Thumb 0x12A86):
#   0x12A8E osal_msg_size(msg); reject if <= 0x13 (log BlogWrite(0x67,7,3,0x14))
#   0x12AA0 ldr r3,[msg]; reject if != 0 (log tag 0x30)
#   0x12AA4 keyPhys2LocalCode(this, msg+4) (0x129D9: table [this+0xB8],
#          count [this+0xBC], 8-byte entries {local code, phys code})
#   0x12AB2 when (local-1) <= 3 -> GetJackStatus(this, 1..4) (0x127B9 reads
#          this+0xCC/0xD0/0xD4/0xD8), else error log tag 0x2A
#   0x12AC8 str r0,[msg+0xC]  -> status written into the message
# The live key table (checkpoint heap 0x2E318, 4 entries) is
#   0x07000001->1, 0x07000002->2, 0x07000003->3, 0x07000004->4.
# ---------------------------------------------------------------------------
INPUT_GET_MIN_MESSAGE_SIZE = 0x14  # osal_msg_size must be > 0x13
INPUT_GET_WORD0_OFFSET = 0x00
INPUT_GET_PHYS_CODE_OFFSET = 0x04
INPUT_GET_STATUS_OFFSET = 0x0C
INPUT_GET_KEY_TABLE_OFFSET = 0xB8
INPUT_GET_KEY_COUNT_OFFSET = 0xBC
JACK_STATUS_FIELDS = {
    1: 0xCC,
    2: 0xD0,
    3: 0xD4,
    4: 0xD8,
}
#: live phys->local key mapping read from the checkpoint (this+0xB8 table).
KEY_PHYS_TO_LOCAL = {
    0x07000001: 1,
    0x07000002: 2,
    0x07000003: 3,
    0x07000004: 4,
}


def phys_key_to_local_code(phys_code):
    """Map a physical key code through the decoded live table.

    Raises ValueError for codes that are not in the decoded table; the
    original callback logs and writes no status for such codes.
    """
    try:
        return KEY_PHYS_TO_LOCAL[int(phys_code)]
    except (KeyError, TypeError):
        raise ValueError(
            'unknown physical key code %r; decoded codes are %s'
            % (phys_code, sorted(KEY_PHYS_TO_LOCAL))) from None


def decode_input_get_request(payload):
    """Decode the h4110 input-get sync message (>= 0x14 bytes).

    Returns ``accepted`` plus the mapped local code.  The callback itself
    rejects word0 != 0 and unmapped physical codes (with a debug log and no
    status write); those decoded rejections are reported as
    ``accepted=False`` with a reason, while a structurally undecodable buffer
    (< 0x14 bytes) raises ``ValueError``.
    """
    raw = bytes(payload)
    if len(raw) < INPUT_GET_MIN_MESSAGE_SIZE:
        raise ValueError(
            'h4110 input-get message too short: %d < 0x14 bytes' % len(raw))
    word0 = struct.unpack_from('<I', raw, INPUT_GET_WORD0_OFFSET)[0]
    phys_code = struct.unpack_from('<I', raw, INPUT_GET_PHYS_CODE_OFFSET)[0]
    result = {
        'packet_class': H4110_PACKET_CLASS,
        'message_size': len(raw),
        'word0': word0,
        'phys_code': phys_code,
        'status_offset': INPUT_GET_STATUS_OFFSET,
        'accepted': False,
        'local_code': None,
        'rejection': None,
    }
    if word0 != 0:
        result['rejection'] = 'word0_not_zero'
        return result
    local = KEY_PHYS_TO_LOCAL.get(phys_code)
    if local is None:
        result['rejection'] = 'phys_code_not_mapped'
        return result
    result['accepted'] = True
    result['local_code'] = local
    result['jack_status_offset'] = JACK_STATUS_FIELDS[local]
    return result


def decode_input_get_response(payload):
    """Read the h4110 status value written back into the message (+0x0C)."""
    raw = bytes(payload)
    if len(raw) < INPUT_GET_MIN_MESSAGE_SIZE:
        raise ValueError(
            'h4110 input-get message too short: %d < 0x14 bytes' % len(raw))
    return {
        'status': struct.unpack_from('<I', raw, INPUT_GET_STATUS_OFFSET)[0],
        'status_offset': INPUT_GET_STATUS_OFFSET,
    }


# ---------------------------------------------------------------------------
# Downstream path (decoded; no ObjMsg construction).
# ---------------------------------------------------------------------------
DOWNSTREAM_PATH = {
    'h4109': {
        'post': 'none (synchronous in-place response)',
        'sequence': (
            'funcOsalSyncCb: id check -> copy request to stack -> zero response '
            'header/payload -> dispatch vtable slot -> copy response back into '
            'the same message buffer (memcpy at 0xB166) -> return to '
            'libosal sync sender'),
        'handlers': 'UsbAdjCmd::process_start_exec 0x100DA (phase 1); '
                    'AdjBase::finish_*_data_exec no-ops (phases 4/0x10)',
        'no_objmsg': True,
        'no_msgsender': True,
        'evidence': '0xB0DF..0xB17A disassembly; vtable _ZTV9UsbAdjCmd '
                    '(process_start_exec 0x100DB, finish_* base no-ops)',
    },
    'h4110': {
        'post': 'none (status written into message+0xC)',
        'sequence': (
            'funcInputGetCb: size check -> word0 check -> phys->local map -> '
            'GetJackStatus -> str [msg+0xC]'),
        'no_objmsg': True,
        'no_msgsender': True,
        'evidence': '0x12A87..0x12AF2 disassembly',
    },
    'usb_control_local_0x00CA8192': {
        'post': 'UsbControl::funcOsalSyncCb 0x1261C swaps args and tail-calls '
                'UsbControl::preProcess 0x123B4 (the ObjMsg inbound lane)',
        'no_objmsg': False,
        'note': 'this is the registration that would carry ObjMsg work, but it '
                'is on the process-local queue (bit15 set), not a kernel queue',
    },
}


def describe_downstream_path(handle=None):
    """Return the decoded downstream-path evidence for one handle or all."""
    if handle is None:
        return dict(DOWNSTREAM_PATH)
    decoded = describe_sync_callback(handle)
    key = 'h%d' % int(handle)
    return {'registration': decoded, 'downstream': dict(DOWNSTREAM_PATH[key])}


def describe_sync_callback_packet_format():
    """Return the full decoded sync-callback packet evidence."""
    return {
        'live_libusbcontrol_sha256': LIVE_LIBUSBCONTROL_SHA256,
        'live_libusbcontrol_size': LIVE_LIBUSBCONTROL_SIZE,
        'live_libusbcontrol_base': LIVE_LIBUSBCONTROL_BASE,
        'sync_callback_abi': dict(SYNC_CALLBACK_ABI),
        'registrations': {str(h): dict(v) for h, v in
                          SYNC_CALLBACK_REGISTRATIONS.items()},
        'adj_packet': {
            'size': ADJ_PACKET_SIZE,
            'phase_offset': ADJ_PHASE_OFFSET,
            'result_offset': ADJ_RESULT_OFFSET,
            'packet_id_offset': ADJ_PACKET_ID_OFFSET,
            'packet_id': ADJ_PACKET_ID,
            'subcommand_offset': ADJ_SUBCOMMAND_OFFSET,
            'argument_offset': ADJ_ARG_OFFSET,
            'data_offset': ADJ_DATA_OFFSET,
            'response_value_offset': ADJ_RESPONSE_VALUE_OFFSET,
            'phases': {hex(k): dict(v) for k, v in ADJ_PHASES.items()},
            'results': {hex(k): v for k, v in ADJ_RESULT_NAMES.items()},
            'subcommands': {hex(k): dict(v) for k, v in ADJ_SUBCOMMANDS.items()},
        },
        'input_get_packet': {
            'min_size': INPUT_GET_MIN_MESSAGE_SIZE,
            'word0_offset': INPUT_GET_WORD0_OFFSET,
            'phys_code_offset': INPUT_GET_PHYS_CODE_OFFSET,
            'status_offset': INPUT_GET_STATUS_OFFSET,
            'key_phys_to_local': dict(KEY_PHYS_TO_LOCAL),
        },
        'downstream': describe_downstream_path(),
        'boundary': (
            'sync_callback_packet_format: the packet bytes are decoded from '
            'the live callback code, not captured from a real kernel sender.  '
            'E0332 models the kernel-origin delivery transport; subcommand '
            'field semantics are handler-derived, and the Backup_* device '
            'contracts behind subcommands 1..7 are outside this module'),
    }


__all__ = [
    'LIVE_LIBUSBCONTROL_SHA256', 'LIVE_LIBUSBCONTROL_SIZE',
    'LIVE_LIBOSAL_UIPC_SHA256', 'LIVE_LIBOSAL_UIPC_SIZE',
    'LIVE_LIBUSBCONTROL_BASE', 'LIVE_LIBUSBCONTROL_DATA_BASE',
    'SYNC_CALLBACK_ABI', 'SYNC_DISPATCHER_THUMB_VA',
    'OSAL_FINISH_SYNC_CB_THUMB_VA', 'OSAL_SND_SYNC_MSG_THUMB_VA',
    'OSAL_REG_SYNC_MSG_QUEUE_CB_THUMB_VA', 'OSAL_SYNC_CB_RECORD_FIELDS',
    'UIPC_LOCAL_QUEUE_BIT',
    'H4109_HANDLE', 'H4109_QUEUE', 'H4109_CALLBACK_VA',
    'H4109_CALLBACK_OFFSET', 'H4109_CALLBACK_SYMBOL', 'H4109_USER_DATA',
    'H4109_PACKET_ID', 'H4110_HANDLE', 'H4110_QUEUE', 'H4110_CALLBACK_VA',
    'H4110_CALLBACK_OFFSET', 'H4110_CALLBACK_SYMBOL', 'H4110_USER_DATA',
    'USB_CONTROL_LOCAL_SYNC_QUEUE', 'USB_CONTROL_LOCAL_SYNC_CALLBACK',
    'SYNC_CALLBACK_REGISTRATIONS', 'describe_sync_callback',
    'ADJ_PACKET_SIZE', 'ADJ_PHASE_OFFSET', 'ADJ_RESULT_OFFSET',
    'ADJ_PACKET_ID_OFFSET', 'ADJ_SUBCOMMAND_OFFSET', 'ADJ_ARG_OFFSET',
    'ADJ_DATA_OFFSET', 'ADJ_PACKET_ID', 'ADJ_PHASES', 'ADJ_RESULT_DISPATCHED',
    'ADJ_RESULT_OK', 'ADJ_RESULT_ID_MISMATCH', 'ADJ_RESULT_ERROR',
    'ADJ_RESULT_NAMES', 'ADJ_SUBCOMMANDS', 'ADJ_FUNCTION_OFFSETS',
    'decode_adj_request_packet', 'decode_adj_response_packet',
    'build_adj_request', 'build_adj_process_start_request',
    'INPUT_GET_MIN_MESSAGE_SIZE', 'INPUT_GET_PHYS_CODE_OFFSET',
    'INPUT_GET_STATUS_OFFSET', 'KEY_PHYS_TO_LOCAL', 'phys_key_to_local_code',
    'decode_input_get_request', 'decode_input_get_response',
    'describe_downstream_path', 'describe_sync_callback_packet_format',
]
