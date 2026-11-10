import hashlib
import struct
import unittest
from src.a6400.execution.guest_usb_event import (
    GuestUsbEvent,
    UnsupportedUsbEvent,
    USB_EVENT_IOCTL_ENABLE,
    USB_EVENT_IOCTL_DISABLE,
    USB_EVENT_IOCTL_STOP,
    USB_EVENT_RECORD_HEADER_SIZE,
    build_usb_event_record,
    record_total_length,
    validate_usb_event_record,
)

# E0299 verified values: the single registered context from the ENABLE ioctl and
# the user-space callback echoed by the kernel (CUsbSvc::proc_kevent_otg).
CONTEXT = 0x0002D568
CALLBACK = 0x52F3B0DD
# E0299 report candidate for the otgcore port-descriptor-shape record
# (subtype 2, len 0). Structurally verified only; it is NOT claimed to be the
# USB connect / Mass Storage trigger (semantics remain an open task-9 item).
CANDIDATE_SUBTYPE2 = bytes.fromhex('68d50200ddb0f352020068d5')


class TestGuestUsbEvent(unittest.TestCase):
    def setUp(self):
        self.dev = GuestUsbEvent()
        self.memory = bytearray(0x1000)
        self.base_addr = 0x100000

    def mem_read(self, addr, size):
        offset = addr - self.base_addr
        return bytes(self.memory[offset:offset+size])

    def mem_write(self, addr, data):
        offset = addr - self.base_addr
        self.memory[offset:offset+len(data)] = data

    def open_and_register(self, context=CONTEXT):
        owner = self.dev.open(flags=2)
        struct.pack_into('<I', self.memory, 0, context)
        ret = self.dev.ioctl(owner['owner_id'], USB_EVENT_IOCTL_ENABLE,
                             self.base_addr, self.mem_read, self.mem_write)
        self.assertEqual(ret, 0)
        return owner

    def test_open_close(self):
        self.assertEqual(self.dev.major, 242)
        self.assertEqual(self.dev.minor, 0)

        owner = self.dev.open(flags=2, caller_pid=1012, caller_tgid=1000)
        self.assertEqual(owner['owner_id'], 1)
        self.assertEqual(owner['flags'], 2)
        self.assertIn(1, self.dev.owners)

        self.dev.close(owner['owner_id'])
        self.assertNotIn(1, self.dev.owners)

    def test_invalid_owner_fails(self):
        with self.assertRaises(UnsupportedUsbEvent) as ctx:
            self.dev.ioctl(999, USB_EVENT_IOCTL_ENABLE, 0, self.mem_read, self.mem_write)
        self.assertEqual(ctx.exception.details['reason'], 'usb_event_invalid_owner_descriptor')

    def test_ioctl_enable_disable(self):
        owner = self.dev.open(flags=2)
        oid = owner['owner_id']

        # Write event ID 42 to user memory
        struct.pack_into('<I', self.memory, 0, 42)
        ret = self.dev.ioctl(oid, USB_EVENT_IOCTL_ENABLE, self.base_addr, self.mem_read, self.mem_write)
        self.assertEqual(ret, 0)
        self.assertIn(42, self.dev.enabled_events)

        # Disable event ID 42
        ret = self.dev.ioctl(oid, USB_EVENT_IOCTL_DISABLE, self.base_addr, self.mem_read, self.mem_write)
        self.assertEqual(ret, 0)
        self.assertNotIn(42, self.dev.enabled_events)

    def test_ioctl_stop(self):
        owner = self.dev.open(flags=2)
        oid = owner['owner_id']

        self.assertFalse(self.dev.stopped)
        ret = self.dev.ioctl(oid, USB_EVENT_IOCTL_STOP, 0, self.mem_read, self.mem_write)
        self.assertEqual(ret, 0)
        self.assertTrue(self.dev.stopped)

    def test_invalid_cmd_returns_einval(self):
        owner = self.dev.open(flags=2)
        oid = owner['owner_id']
        ret = self.dev.ioctl(oid, 0xdeadbeef, 0, self.mem_read, self.mem_write)
        self.assertEqual(ret, -22)

    def test_read_behavior(self):
        owner = self.dev.open(flags=2)
        oid = owner['owner_id']

        # When empty and not stopped: returns None (indicating blocking wait)
        res = self.dev.read(oid, 128, lambda data: None)
        self.assertIsNone(res)

        # When event pending: writes data and returns count
        test_event = b'\x01\x00\x00\x00\x04\x00\x00\x00'
        self.dev.pending_events.append(test_event)
        written = bytearray()
        res = self.dev.read(oid, 128, lambda data: written.extend(data))
        self.assertEqual(res, len(test_event))
        self.assertEqual(bytes(written), test_event)

        # When stopped: returns 0 (EOF)
        self.dev.stopped = True
        res = self.dev.read(oid, 128, lambda data: None)
        self.assertEqual(res, 0)

    def test_user_pointer_outside_task_limit(self):
        owner = self.dev.open(flags=2)
        oid = owner['owner_id']

        with self.assertRaises(UnsupportedUsbEvent) as ctx:
            self.dev.ioctl(oid, USB_EVENT_IOCTL_ENABLE, 0x5f000000, self.mem_read, self.mem_write)
        self.assertEqual(ctx.exception.details['reason'], 'user_pointer_outside_task_limit')


class TestUsbEventRecordAbi(unittest.TestCase):
    """E0299 record layout: 12-byte header + aligned payload, pad from context."""

    def test_total_length_is_multiple_of_four(self):
        for payload_len in range(0, 256):
            total = record_total_length(payload_len)
            self.assertEqual(total, 12 + payload_len + ((-payload_len) & 3))
            self.assertEqual(total % 4, 0)
            self.assertGreaterEqual(total, USB_EVENT_RECORD_HEADER_SIZE)

    def test_build_matches_verified_candidate(self):
        record = build_usb_event_record(CONTEXT, CALLBACK, 2, b'')
        self.assertEqual(record, CANDIDATE_SUBTYPE2)
        self.assertEqual(len(record), 12)
        self.assertEqual(struct.unpack_from('<I', record, 0)[0], CONTEXT)
        self.assertEqual(struct.unpack_from('<I', record, 4)[0], CALLBACK)
        self.assertEqual(record[8], 2)
        self.assertEqual(record[9], 0)
        self.assertEqual(record[10:12], struct.pack('<I', CONTEXT)[:2])
        self.assertEqual(record[10:12], b'\x68\xd5')

    def test_build_pad_and_tail_pad_derived_from_context(self):
        context_word = struct.pack('<I', CONTEXT)
        for payload_len in range(0, 12):
            payload = bytes(range(payload_len))
            record = build_usb_event_record(CONTEXT, CALLBACK, 3, payload)
            self.assertEqual(len(record), record_total_length(payload_len))
            self.assertEqual(record[8], 3)
            self.assertEqual(record[9], payload_len)
            self.assertEqual(record[10:12], context_word[:2])
            self.assertEqual(record[12:12 + payload_len], payload)
            tail = record[12 + payload_len:]
            self.assertEqual(tail, context_word[:((-payload_len) & 3)])
            self.assertEqual(len(tail), (-payload_len) & 3)

    def test_build_rejects_zero_context_and_callback(self):
        with self.assertRaises(UnsupportedUsbEvent) as ctx:
            build_usb_event_record(0, CALLBACK, 2)
        self.assertEqual(ctx.exception.details['reason'], 'usb_event_record_context_zero')

        with self.assertRaises(UnsupportedUsbEvent) as ctx:
            build_usb_event_record(CONTEXT, 0, 2)
        self.assertEqual(ctx.exception.details['reason'], 'usb_event_record_callback_zero')

    def test_build_rejects_out_of_range_fields(self):
        with self.assertRaises(UnsupportedUsbEvent) as ctx:
            build_usb_event_record(CONTEXT, CALLBACK, 0x100)
        self.assertEqual(ctx.exception.details['reason'], 'usb_event_subtype_out_of_range')

        with self.assertRaises(UnsupportedUsbEvent) as ctx:
            build_usb_event_record(CONTEXT, CALLBACK, 2, bytes(256))
        self.assertEqual(ctx.exception.details['reason'], 'usb_event_payload_too_long')

        with self.assertRaises(UnsupportedUsbEvent) as ctx:
            build_usb_event_record('context', CALLBACK, 2)
        self.assertEqual(ctx.exception.details['reason'], 'usb_event_field_not_integer')

    def test_validate_accepts_candidate_for_registered_context(self):
        fields = validate_usb_event_record(CANDIDATE_SUBTYPE2, {CONTEXT})
        self.assertEqual(fields['context'], CONTEXT)
        self.assertEqual(fields['callback'], CALLBACK)
        self.assertEqual(fields['subtype'], 2)
        self.assertEqual(fields['payload_len'], 0)
        self.assertEqual(fields['bytes'], 12)
        self.assertEqual(fields['sha256'],
                         hashlib.sha256(CANDIDATE_SUBTYPE2).hexdigest())


class TestUsbEventInjection(unittest.TestCase):
    def setUp(self):
        self.dev = GuestUsbEvent()
        self.memory = bytearray(0x1000)
        self.base_addr = 0x100000

    def mem_read(self, addr, size):
        offset = addr - self.base_addr
        return bytes(self.memory[offset:offset+size])

    def mem_write(self, addr, data):
        offset = addr - self.base_addr
        self.memory[offset:offset+len(data)] = data

    def open_and_register(self, context=CONTEXT):
        owner = self.dev.open(flags=2)
        struct.pack_into('<I', self.memory, 0, context)
        self.assertEqual(self.dev.ioctl(owner['owner_id'], USB_EVENT_IOCTL_ENABLE,
                                        self.base_addr, self.mem_read, self.mem_write), 0)
        return owner

    def inject(self, record, **kwargs):
        return self.dev.inject_record(record, **kwargs)

    def test_inject_accepts_verified_record_and_records_provenance(self):
        owner = self.open_and_register()
        result = self.inject(CANDIDATE_SUBTYPE2, source='unit-test')

        self.assertTrue(result['accepted'])
        self.assertEqual(result['reason'], '')
        self.assertEqual(result['bytes'], 12)
        self.assertEqual(result['sha256'], hashlib.sha256(CANDIDATE_SUBTYPE2).hexdigest())
        self.assertEqual(result['context'], CONTEXT)
        self.assertEqual(result['callback'], CALLBACK)
        self.assertEqual(result['subtype'], 2)

        self.assertTrue(self.dev.readable())
        self.assertFalse(self.dev.stopped)
        self.assertEqual(self.dev.record_length, 12)
        self.assertEqual(self.dev.pending_bytes, 12)
        self.assertEqual(self.dev.pending_events, [CANDIDATE_SUBTYPE2])
        self.assertTrue(self.dev.event_queue)
        self.assertEqual(len(self.dev.pending_records), 1)
        entry = self.dev.pending_records[0]
        self.assertEqual(entry['record'], CANDIDATE_SUBTYPE2)
        self.assertEqual(entry['context'], CONTEXT)
        self.assertEqual(entry['callback'], CALLBACK)
        self.assertEqual(entry['subtype'], 2)
        self.assertEqual(entry['payload_len'], 0)
        self.assertEqual(entry['source'], 'unit-test')
        self.assertEqual(entry['remaining'], 12)
        self.assertEqual(entry['sha256'], result['sha256'])

        # The injected record is served verbatim by read().
        written = bytearray()
        self.assertEqual(self.dev.read(owner['owner_id'], 64, written.extend), 12)
        self.assertEqual(bytes(written), CANDIDATE_SUBTYPE2)
        self.assertTrue(self.dev.transactions[-1]['operation'], 'read')

    def test_inject_rejects_unregistered_context(self):
        self.dev.open(flags=2)  # open but no ENABLE ioctl
        result = self.inject(CANDIDATE_SUBTYPE2)
        self.assertFalse(result['accepted'])
        self.assertEqual(result['reason'], 'usb_event_context_not_registered')
        self.assertEqual(result['context'], CONTEXT)
        self.assertEqual(self.dev.pending_events, [])
        self.assertEqual(self.dev.pending_records, [])
        self.assertFalse(self.dev.readable())
        self.assertIsNone(self.dev.record_length)
        self.assertFalse(self.dev.event_queue)

    def test_inject_rejects_when_device_not_open(self):
        result = self.inject(CANDIDATE_SUBTYPE2)
        self.assertFalse(result['accepted'])
        self.assertEqual(result['reason'], 'usb_event_device_not_open')

    def test_inject_rejects_after_stop(self):
        owner = self.open_and_register()
        self.dev.ioctl(owner['owner_id'], USB_EVENT_IOCTL_STOP, 0, self.mem_read, self.mem_write)
        result = self.inject(CANDIDATE_SUBTYPE2)
        self.assertFalse(result['accepted'])
        self.assertEqual(result['reason'], 'usb_event_device_stopped')
        self.assertFalse(self.dev.readable())

    def test_inject_rejects_disabled_context(self):
        owner = self.open_and_register()
        struct.pack_into('<I', self.memory, 0, CONTEXT)
        self.assertEqual(self.dev.ioctl(owner['owner_id'], USB_EVENT_IOCTL_DISABLE,
                                        self.base_addr, self.mem_read, self.mem_write), 0)
        result = self.inject(CANDIDATE_SUBTYPE2)
        self.assertFalse(result['accepted'])
        self.assertEqual(result['reason'], 'usb_event_context_not_registered')

    def test_inject_rejects_malformed_records(self):
        self.open_and_register()
        callback = struct.pack('<I', CALLBACK)
        context = struct.pack('<I', CONTEXT)
        cases = {
            'empty': (b'', 'usb_event_record_empty'),
            'too_short': (b'\x00' * 8, 'usb_event_record_too_short'),
            'unaligned': (CANDIDATE_SUBTYPE2 + b'\x00', 'usb_event_record_unaligned'),
            'length_mismatch': (CANDIDATE_SUBTYPE2[:9] + b'\x08' + CANDIDATE_SUBTYPE2[10:],
                                'usb_event_record_length_mismatch'),
            'context_zero': (context[:0] + bytes(4) + callback + b'\x02\x00' + bytes(2),
                             'usb_event_record_context_zero'),
            'callback_zero': (context + bytes(4) + b'\x02\x00' + context[:2],
                              'usb_event_record_callback_zero'),
            'pad_mismatch': (CANDIDATE_SUBTYPE2[:10] + b'\x01\x02'
                             + CANDIDATE_SUBTYPE2[12:], 'usb_event_record_pad_mismatch'),
            'not_bytes': ('not-a-record', 'usb_event_record_not_bytes'),
            'none': (None, 'usb_event_record_not_bytes'),
        }
        for name, (record, expected_reason) in cases.items():
            with self.subTest(case=name):
                result = self.inject(record)
                self.assertFalse(result['accepted'])
                self.assertEqual(result['reason'], expected_reason)
                self.assertEqual(self.dev.pending_events, [])
                self.assertEqual(self.dev.pending_records, [])

    def test_inject_rejects_tail_pad_mismatch(self):
        self.open_and_register()
        record = bytearray(build_usb_event_record(CONTEXT, CALLBACK, 1, b'\xaa'))
        self.assertEqual(len(record), 16)
        record[-1] ^= 0xff  # corrupt one tail alignment byte
        result = self.inject(bytes(record))
        self.assertFalse(result['accepted'])
        self.assertEqual(result['reason'], 'usb_event_record_tail_pad_mismatch')
        self.assertEqual(self.dev.pending_events, [])

    def test_read_returns_raw_stream_across_records(self):
        owner = self.open_and_register()
        first = build_usb_event_record(CONTEXT, CALLBACK, 2, b'')
        second = build_usb_event_record(CONTEXT, CALLBACK, 1, b'\xaa\xbb')
        self.assertTrue(self.inject(first)['accepted'])
        self.assertTrue(self.inject(second)['accepted'])
        expected = first + second
        self.assertEqual(self.dev.pending_bytes, len(expected))
        self.assertEqual(self.dev.record_length, len(first))

        # A short read returns a raw prefix and keeps the remainder queued.
        written = bytearray()
        self.assertEqual(self.dev.read(owner['owner_id'], 4, written.extend), 4)
        self.assertEqual(bytes(written), expected[:4])
        self.assertTrue(self.dev.readable())
        self.assertEqual(self.dev.pending_bytes, len(expected) - 4)

        # The following read continues the same raw stream across the boundary.
        written = bytearray()
        self.assertEqual(self.dev.read(owner['owner_id'], 4096, written.extend),
                         len(expected) - 4)
        self.assertEqual(bytes(written), expected[4:])
        self.assertFalse(self.dev.readable())
        self.assertIsNone(self.dev.record_length)
        self.assertIsNone(self.dev.read(owner['owner_id'], 16, lambda data: None))

    def test_read_does_not_filter_per_record(self):
        """Kernel read() returns raw ring bytes; it must not drop records."""
        owner = self.open_and_register()
        # Unknown context and even non-multiple-of-4 bytes appended directly to
        # the pending stream are still returned verbatim (no per-record filter).
        raw = b'\x11\x22\x33'
        self.dev.pending_events.append(raw)
        written = bytearray()
        self.assertEqual(self.dev.read(owner['owner_id'], 3, written.extend), 3)
        self.assertEqual(bytes(written), raw)

    def test_partial_read_keeps_record_provenance_until_consumed(self):
        owner = self.open_and_register()
        record = build_usb_event_record(CONTEXT, CALLBACK, 4, b'\x01\x02\x03')
        self.assertTrue(self.inject(record)['accepted'])
        self.assertEqual(self.dev.record_length, len(record))

        self.assertEqual(self.dev.read(owner['owner_id'], 5, lambda data: None), 5)
        self.assertEqual(self.dev.record_length, len(record) - 5)
        self.assertEqual(self.dev.pending_records[0]['remaining'], len(record) - 5)
        self.assertEqual(self.dev.pending_records[0]['consumed'], 5)

        self.assertEqual(self.dev.read(owner['owner_id'], 4096, lambda data: None),
                         len(record) - 5)
        self.assertEqual(self.dev.pending_records, [])
        self.assertFalse(self.dev.readable())

    def test_stopped_read_returns_eof_and_clears_poll_readiness(self):
        owner = self.open_and_register()
        self.assertTrue(self.inject(CANDIDATE_SUBTYPE2)['accepted'])
        self.assertTrue(self.dev.event_queue)
        self.dev.ioctl(owner['owner_id'], USB_EVENT_IOCTL_STOP, 0, self.mem_read, self.mem_write)
        self.assertEqual(self.dev.read(owner['owner_id'], 16, lambda data: None), 0)
        self.assertFalse(self.dev.readable())
        self.assertEqual(self.dev.event_queue, [])

    def test_injection_transaction_is_recorded(self):
        self.open_and_register()
        self.inject(CANDIDATE_SUBTYPE2)
        transaction = self.dev.transactions[-1]
        self.assertEqual(transaction['operation'], 'inject_record')
        self.assertTrue(transaction['accepted'])
        self.assertEqual(transaction['context'], CONTEXT)
        self.assertEqual(transaction['subtype'], 2)


if __name__ == '__main__':
    unittest.main()
