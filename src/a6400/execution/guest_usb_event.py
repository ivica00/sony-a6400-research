"""Guarded USB event kernel interface (/dev/usb/event).

Authentic Sony USB event driver contract evidenced by:
- vmlinux.bin udif_devnodes table at offset 0x3d2ba8 (VA 0x604daba8):
  name: "usb/event", dev_t: MKDEV(242, 0) -> Major 242, Minor 0
- vmlinux.bin file_operations at offset 0x3dcf38:
  open: 0x602b5a00, release: 0x602b56f8, unlocked_ioctl: 0x602b5814, read: 0x602b5d7c
- libInfraUsbCmn.so usb_event_start (0xc7a4), usb_event_stop (0xca1c),
  usb_event_enable (0xcb78), usb_event_disable (0xcc74)
- Ioctl commands:
  - 0x4004e101: USB_EVENT_IOCTL_ENABLE (_IOW(0xe1, 1, uint32))
  - 0x4004e102: USB_EVENT_IOCTL_DISABLE (_IOW(0xe1, 2, uint32))
  - 0x0000e103: USB_EVENT_IOCTL_STOP (_IO(0xe1, 3))

Record ABI (E0299, verified from vmlinux producer ``usb_event_add_queue`` VA
0x602b5c14 and ring writer VA 0x602b5b10; producer/ring behavior executed
offline in E0217).  A record is a 12-byte header plus an aligned payload:

    offset     size  field
    +0         4     context (u32 LE): registered context id, the gating key
    +4         4     callback (u32 LE): user-space Thumb callback echoed by the
                     kernel (non-zero)
    +8         1     subtype (u8)
    +9         1     payload_len (u8)
    +10        2     alignment bytes copied from the low two bytes of the
                     context word (not semantic)
    +12        len   opaque payload
    +12+len    0..3  tail alignment bytes, again copied from the context word

Total length is ``12 + len + ((-len) & 3)`` bytes, always a multiple of 4.
``enabled_events`` holds the registered *context ids* (checkpoint state:
``{0x2D568}`` from the ENABLE ioctl); it is not an event-subtype mask: the
kernel producer only queues a record when ``context`` is registered, and the
user-space consumer drops records whose context it did not register.
``read()`` is a raw ring byte stream (it returns ``min(count, used)`` bytes and
never filters individual records); each call to the kernel returns raw bytes,
wrap-aware.

Connect / Mass Storage semantics remain UNKNOWN: E0299 establishes the record
structure, the registered context ``0x0002D568`` and the callback
``0x52F3B0DD`` (``CUsbSvc::proc_kevent_otg``), but not which subtype/payload
means "USB connect / Mass Storage".  This module therefore deliberately offers
no connect-record factory: callers must pass the exact experiment bytes
(structurally valid, from ``build_usb_event_record`` if desired) and label them
as unverified.  Validation only enforces the verified ABI and the verified
context gating; it does not assign subtype semantics.

Strictly adheres to fail-closed semantics and user memory task limits (TASK_SIZE <= 0x5f000000).
"""
import hashlib
import struct

USB_EVENT_IOCTL_ENABLE = 0x4004e101
USB_EVENT_IOCTL_DISABLE = 0x4004e102
USB_EVENT_IOCTL_STOP = 0x0000e103

USB_EVENT_RECORD_HEADER_SIZE = 12
USB_EVENT_RECORD_MAX_PAYLOAD = 0xff
USB_EVENT_RECORD_ALIGNMENT = 4


def record_total_length(payload_len):
    """Exact verified on-wire record size for a payload length (E0299 ABI)."""
    return (USB_EVENT_RECORD_HEADER_SIZE + payload_len +
            ((-payload_len) & (USB_EVENT_RECORD_ALIGNMENT - 1)))


class UnsupportedUsbEvent(RuntimeError):
    def __init__(self, reason, **details):
        super().__init__(reason)
        self.details = {'reason': reason, 'device': '/dev/usb/event', **details}


def _require_u32(value, field):
    if not isinstance(value, int) or isinstance(value, bool):
        raise UnsupportedUsbEvent('usb_event_field_not_integer', field=field,
                                  value_type=type(value).__name__)
    if value < 0 or value > 0xffffffff:
        raise UnsupportedUsbEvent('usb_event_field_out_of_range', field=field, value=value)


def build_usb_event_record(context, callback, subtype, payload=b''):
    """Build one structurally valid record using the verified E0299 ABI.

    No subtype/payload semantics are assigned here: ``subtype`` and ``payload``
    are caller-supplied experiment inputs.  The two alignment regions are
    derived from the context word exactly as the kernel ring writer does
    (``usb_event_add_queue`` copies alignment bytes from the context word).
    """
    _require_u32(context, 'context')
    _require_u32(callback, 'callback')
    _require_u32(subtype, 'subtype')
    if subtype > 0xff:
        raise UnsupportedUsbEvent('usb_event_subtype_out_of_range', subtype=subtype)
    if context == 0:
        raise UnsupportedUsbEvent('usb_event_record_context_zero')
    if callback == 0:
        raise UnsupportedUsbEvent('usb_event_record_callback_zero')
    if not isinstance(payload, (bytes, bytearray, memoryview)):
        raise UnsupportedUsbEvent('usb_event_payload_not_bytes',
                                  payload_type=type(payload).__name__)
    payload = bytes(payload)
    if len(payload) > USB_EVENT_RECORD_MAX_PAYLOAD:
        raise UnsupportedUsbEvent('usb_event_payload_too_long', length=len(payload),
                                  maximum=USB_EVENT_RECORD_MAX_PAYLOAD)
    context_word = struct.pack('<I', context)
    header = (struct.pack('<II', context, callback) +
              bytes((subtype, len(payload))) + context_word[:2])
    tail_pad = context_word[:((-len(payload)) & (USB_EVENT_RECORD_ALIGNMENT - 1))]
    return header + payload + tail_pad


def validate_usb_event_record(record, registered_contexts=()):
    """Validate one record against the verified ABI and context gating.

    Returns the parsed field dictionary on success and raises
    :class:`UnsupportedUsbEvent` with an explicit reason otherwise.  The
    alignment bytes are required to match the context word, fail-closed: a
    record whose padding was not produced by the verified ring writer is
    refused rather than silently repaired.
    """
    if not isinstance(record, (bytes, bytearray, memoryview)):
        raise UnsupportedUsbEvent('usb_event_record_not_bytes',
                                  record_type=type(record).__name__)
    record = bytes(record)
    sha256 = hashlib.sha256(record).hexdigest()
    if not record:
        raise UnsupportedUsbEvent('usb_event_record_empty', bytes=0, sha256=sha256)
    if len(record) < USB_EVENT_RECORD_HEADER_SIZE:
        raise UnsupportedUsbEvent('usb_event_record_too_short', bytes=len(record),
                                  minimum=USB_EVENT_RECORD_HEADER_SIZE, sha256=sha256)
    if len(record) % USB_EVENT_RECORD_ALIGNMENT:
        raise UnsupportedUsbEvent('usb_event_record_unaligned', bytes=len(record),
                                  alignment=USB_EVENT_RECORD_ALIGNMENT, sha256=sha256)
    context = struct.unpack_from('<I', record, 0)[0]
    callback = struct.unpack_from('<I', record, 4)[0]
    subtype = record[8]
    payload_len = record[9]
    expected = record_total_length(payload_len)
    if len(record) != expected:
        raise UnsupportedUsbEvent('usb_event_record_length_mismatch', bytes=len(record),
                                  payload_len=payload_len, expected=expected, sha256=sha256)
    if context == 0:
        raise UnsupportedUsbEvent('usb_event_record_context_zero', sha256=sha256)
    if context not in set(registered_contexts):
        raise UnsupportedUsbEvent('usb_event_context_not_registered', context=context,
                                  registered=sorted(set(registered_contexts)), sha256=sha256)
    if callback == 0:
        raise UnsupportedUsbEvent('usb_event_record_callback_zero', sha256=sha256)
    context_word = struct.pack('<I', context)
    pad = record[10:12]
    if pad != context_word[:2]:
        raise UnsupportedUsbEvent('usb_event_record_pad_mismatch', pad=pad.hex(),
                                  expected=context_word[:2].hex(), sha256=sha256)
    tail_pad = record[12 + payload_len:]
    tail_expected = context_word[:((-payload_len) & (USB_EVENT_RECORD_ALIGNMENT - 1))]
    if tail_pad != tail_expected:
        raise UnsupportedUsbEvent('usb_event_record_tail_pad_mismatch',
                                  tail_pad=tail_pad.hex(), expected=tail_expected.hex(),
                                  sha256=sha256)
    return {
        'record': record,
        'bytes': len(record),
        'sha256': sha256,
        'context': context,
        'callback': callback,
        'subtype': subtype,
        'payload_len': payload_len,
        'payload': record[12:12 + payload_len],
        'pad': pad.hex(),
        'tail_pad': tail_pad.hex(),
    }


class GuestUsbEvent:
    """Emulates /dev/usb/event character device (242:0)."""

    def __init__(self, address_limit=0x5f000000):
        self.address_limit = address_limit
        self.major = 242
        self.minor = 0
        self.owners = {}
        # Registered context ids (kernel ENABLE ioctl), not subtype masks.
        self.enabled_events = set()
        self.stopped = False
        # Raw pending ring chunks (byte stream consumed by read()).
        self.pending_events = []
        # Provenance for records queued through inject_record(); kept in
        # injection order and consumed as the raw stream is read.
        self.pending_records = []
        self.transactions = []

    @property
    def event_queue(self):
        """Raw pending ring bytes for poll readiness; empty while stopped."""
        if self.stopped:
            return []
        return list(getattr(self, 'pending_events', None) or [])

    def readable(self):
        """True when raw pending bytes exist and the device is not stopped."""
        return bool(getattr(self, 'pending_events', None)) and not self.stopped

    @property
    def pending_bytes(self):
        """Total raw bytes queued for read()."""
        return sum(len(chunk) for chunk in (getattr(self, 'pending_events', None) or []))

    @property
    def record_length(self):
        """Byte length of the next pending record, or None when none is pending."""
        records = getattr(self, 'pending_records', None) or []
        if records:
            return records[0].get('remaining', records[0].get('bytes'))
        pending = getattr(self, 'pending_events', None) or []
        return len(pending[0]) if pending else None

    def _ensure_injection_state(self):
        # Checkpoints written before the E0299 injection API do not carry the
        # provenance list; restoring one must not break injection or read().
        if not hasattr(self, 'pending_records'):
            self.pending_records = []

    def _note_consumed_stream(self, chunk, remaining_after):
        """Advance pending_records provenance for bytes just read from a chunk."""
        records = getattr(self, 'pending_records', None)
        if not records:
            return
        front = records[0]
        record = front.get('record')
        if not record:
            return
        if record != chunk and not (record.endswith(chunk) and
                                    front.get('remaining', len(record)) == len(chunk)):
            return
        if remaining_after == 0:
            records.pop(0)
        else:
            front['remaining'] = remaining_after
            front['consumed'] = len(record) - remaining_after

    def inject_record(self, record, source=None):
        """Queue one structurally verified /dev/usb/event record byte stream.

        The caller supplies the exact experiment bytes; this method never
        invents or repairs a record.  A record is accepted only when the
        device has an open owner, is not stopped, and the verified ABI holds:
        total ``12 + len + ((-len) & 3)`` bytes, a non-zero caller-supplied
        ``context`` that is registered through ``USB_EVENT_IOCTL_ENABLE``,
        a non-zero ``callback``, and alignment bytes equal to the low bytes of
        the context word.  Returns a decision dictionary with ``accepted``,
        ``reason`` (empty when accepted), ``bytes`` and ``sha256``; rejection
        never raises and never queues bytes.
        """
        self._ensure_injection_state()
        if not isinstance(record, (bytes, bytearray, memoryview)):
            result = {'accepted': False, 'reason': 'usb_event_record_not_bytes',
                      'bytes': None, 'sha256': None,
                      'record_type': type(record).__name__}
            self.transactions.append({'operation': 'inject_record', **result})
            return result
        raw = bytes(record)
        result = {'accepted': False, 'reason': '',
                  'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
        if self.stopped:
            result['reason'] = 'usb_event_device_stopped'
            self.transactions.append({'operation': 'inject_record', **result})
            return result
        if not self.owners:
            result['reason'] = 'usb_event_device_not_open'
            self.transactions.append({'operation': 'inject_record', **result})
            return result
        try:
            fields = validate_usb_event_record(raw, self.enabled_events)
        except UnsupportedUsbEvent as error:
            result.update({key: value for key, value in error.details.items()
                           if key not in ('reason', 'device')})
            result['reason'] = error.details['reason']
            self.transactions.append({'operation': 'inject_record', **result})
            return result

        self.pending_events.append(fields['record'])
        self.pending_records.append({
            'record': fields['record'],
            'bytes': fields['bytes'],
            'sha256': fields['sha256'],
            'context': fields['context'],
            'callback': fields['callback'],
            'subtype': fields['subtype'],
            'payload_len': fields['payload_len'],
            'payload': fields['payload'],
            'source': source,
            'consumed': 0,
            'remaining': fields['bytes'],
        })
        result.update({'accepted': True, 'context': fields['context'],
                       'callback': fields['callback'], 'subtype': fields['subtype'],
                       'payload_len': fields['payload_len']})
        self.transactions.append({'operation': 'inject_record', 'accepted': True,
                                  'bytes': result['bytes'], 'sha256': result['sha256'],
                                  'context': result['context'], 'subtype': result['subtype'],
                                  'payload_len': result['payload_len'], 'source': source})
        return result

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
            raise UnsupportedUsbEvent('usb_event_invalid_owner_descriptor', owner_id=owner_id)

        if cmd == USB_EVENT_IOCTL_ENABLE:
            if arg >= self.address_limit or arg == 0:
                raise UnsupportedUsbEvent('user_pointer_outside_task_limit', address=arg, limit=self.address_limit)
            raw = mem_read(arg, 4)
            event_id = struct.unpack('<I', raw)[0]
            self.enabled_events.add(event_id)
            self.transactions.append({'operation': 'ioctl', 'cmd': cmd, 'name': 'USB_EVENT_IOCTL_ENABLE',
                                      'event_id': event_id, 'returned': 0})
            return 0

        if cmd == USB_EVENT_IOCTL_DISABLE:
            if arg >= self.address_limit or arg == 0:
                raise UnsupportedUsbEvent('user_pointer_outside_task_limit', address=arg, limit=self.address_limit)
            raw = mem_read(arg, 4)
            event_id = struct.unpack('<I', raw)[0]
            self.enabled_events.discard(event_id)
            self.transactions.append({'operation': 'ioctl', 'cmd': cmd, 'name': 'USB_EVENT_IOCTL_DISABLE',
                                      'event_id': event_id, 'returned': 0})
            return 0

        if cmd == USB_EVENT_IOCTL_STOP:
            self.stopped = True
            self.transactions.append({'operation': 'ioctl', 'cmd': cmd, 'name': 'USB_EVENT_IOCTL_STOP',
                                      'returned': 0})
            return 0

        return -22  # -EINVAL

    def read(self, owner_id, count, mem_write):
        owner = self.owners.get(owner_id)
        if not owner:
            raise UnsupportedUsbEvent('usb_event_invalid_owner_descriptor', owner_id=owner_id)

        if self.stopped:
            self.transactions.append({'operation': 'read', 'bytes_read': 0, 'stopped': True})
            return 0  # EOF

        if not self.pending_events:
            # No events available; blocks waiting for hardware event
            return None

        if count is None or count <= 0:
            self.transactions.append({'operation': 'read', 'bytes_read': 0, 'count': count})
            return 0

        # Raw ring byte stream: return up to ``count`` bytes across pending
        # records without per-record filtering, keeping any remainder queued.
        written = 0
        while written < count and self.pending_events:
            chunk = self.pending_events[0]
            take = min(count - written, len(chunk))
            mem_write(chunk[:take])
            written += take
            remaining = len(chunk) - take
            if remaining == 0:
                self.pending_events.pop(0)
                self._note_consumed_stream(chunk, 0)
            else:
                self.pending_events[0] = chunk[take:]
                self._note_consumed_stream(chunk, remaining)
                break
        self.transactions.append({'operation': 'read', 'bytes_read': written})
        return written

    def close(self, owner_id):
        if owner_id in self.owners:
            del self.owners[owner_id]
            self.transactions.append({'operation': 'close', 'owner_id': owner_id})
        return 0
