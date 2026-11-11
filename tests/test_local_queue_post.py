"""Tests for the pure libosal local-queue post planner (constructed fixtures).

No firmware, emulator or Unicorn is used: a fake guest-memory reader supplies
the queue object, message headers and WAIT_CB record.  The planner must be
deterministic, bounded, read-only and fail closed on states outside the
verified path.
"""
import struct
import unittest

from src.a6400.execution import local_queue_post as planner
from src.a6400.execution.local_queue_post import (
    FUTEX_WAKE_PRIVATE,
    HEAD_PAYLOAD_BIAS,
    MAX_PLAN_WRITES,
    QUEUE_OBJECT_SIZE,
    plan_local_post,
    render_post_plan,
    validate_local_queue_object,
)

BASE = 0x50000000
QUEUE = 0x50010000
MSG1_HEAD = 0x50011000
MSG2_HEAD = 0x50012000
MSG3_HEAD = 0x50013000
NEW_HEAD = 0x50014000
WAITER = 0x50015000
OTHER_RECORD = 0x50015100
OUT_SLOT = 0x50016000
FUTEX = WAITER + 0x14  # the WAIT_CB futex word lives at record+0x14
DISPATCHER = 0x50001234


class FakeGuestMemory:
    """Bounded guest-memory reader: reads below BASE or past the end fail."""

    def __init__(self, size=0x20000):
        self.base = BASE
        self.memory = bytearray(size)
        self.reads = []

    def write(self, address, data):
        offset = address - self.base
        self.memory[offset:offset + len(data)] = data

    def write_u32(self, address, value):
        self.write(address, struct.pack('<I', value))

    def read_u32(self, address):
        return struct.unpack('<I', self(address, 4))[0]

    def __call__(self, address, size):
        self.reads.append((address, size))
        offset = int(address) - self.base
        if offset < 0 or offset + size > len(self.memory):
            raise ValueError('unmapped guest address 0x%08x' % (address,))
        return bytes(self.memory[offset:offset + size])


def write_queue(reader, *, lock=0, flags=0, records=0, head=0, tail=0,
                field_0x14=0, sync_callback=0, async_notify=0, field_0x20=0):
    reader.write(QUEUE, struct.pack(
        '<IIIIIIIII', lock, flags, records, head, tail, field_0x14,
        sync_callback, async_notify, field_0x20))


def write_message(reader, head, *, next_head=0, priority=1):
    header = bytearray(0x0C)
    struct.pack_into('<I', header, 0, next_head)
    header[5] = priority & 0x3F
    reader.write(head, bytes(header))


def write_record(reader, record, *, next_record=0, flags=0x04,
                 dispatcher=DISPATCHER, activity=0,
                 futex_word=0, out_slot=OUT_SLOT):
    raw = bytearray(0x20)
    struct.pack_into('<I', raw, 0x00, next_record)
    struct.pack_into('<I', raw, 0x08, dispatcher)
    raw[0x0C] = activity
    raw[0x0D] = flags
    struct.pack_into('<I', raw, 0x14, futex_word)
    struct.pack_into('<I', raw, 0x18, out_slot)
    reader.write(record, bytes(raw))


def empty_queue(reader, **kwargs):
    write_queue(reader, **kwargs)


def payload_of(head):
    return head - HEAD_PAYLOAD_BIAS


class LocalQueueObjectValidationTests(unittest.TestCase):
    def setUp(self):
        self.memory = FakeGuestMemory()

    def test_empty_queue_object_is_reported_ready(self):
        empty_queue(self.memory, tail=MSG1_HEAD)  # stale tail is tolerated
        queue = validate_local_queue_object(self.memory, QUEUE)
        self.assertTrue(queue['ready'])
        self.assertEqual(queue['object'], QUEUE)
        self.assertEqual(queue['lock'], 0)
        self.assertEqual(queue['flags'], 0)
        self.assertEqual(queue['message_head'], 0)
        self.assertTrue(queue['empty'])
        self.assertEqual(queue['messages'], [])
        self.assertEqual(queue['stale_tail'], MSG1_HEAD)
        self.assertEqual(queue['receiver_record_count'], 0)
        self.assertIn('provenance', queue)

    def test_locked_object_is_refused(self):
        empty_queue(self.memory, lock=0x80000001)
        with self.assertRaisesRegex(ValueError, 'queue_object_locked'):
            validate_local_queue_object(self.memory, QUEUE)

    def test_unknown_flag_bits_are_refused(self):
        empty_queue(self.memory, flags=0x10)
        with self.assertRaisesRegex(ValueError, 'queue_object_unknown_flags'):
            validate_local_queue_object(self.memory, QUEUE)

    def test_broadcast_mode_is_refused(self):
        empty_queue(self.memory, flags=0x01)
        with self.assertRaisesRegex(ValueError, 'broadcast_mode_unmodelled'):
            validate_local_queue_object(self.memory, QUEUE)

    def test_async_notify_mode_is_refused(self):
        empty_queue(self.memory, flags=0x08)
        with self.assertRaisesRegex(ValueError, 'async_notify_unmodelled'):
            validate_local_queue_object(self.memory, QUEUE)

    def test_dispatch_in_progress_is_refused(self):
        empty_queue(self.memory, flags=0x02)
        with self.assertRaisesRegex(ValueError, 'dispatch_in_progress'):
            validate_local_queue_object(self.memory, QUEUE)

    def test_message_chain_priorities_are_reported(self):
        write_message(self.memory, MSG1_HEAD, next_head=MSG2_HEAD, priority=5)
        write_message(self.memory, MSG2_HEAD, priority=3)
        empty_queue(self.memory, head=MSG1_HEAD, tail=MSG2_HEAD)
        queue = validate_local_queue_object(self.memory, QUEUE)
        self.assertEqual([message['priority'] for message in queue['messages']],
                         [5, 3])
        self.assertEqual([message['payload'] for message in queue['messages']],
                         [payload_of(MSG1_HEAD), payload_of(MSG2_HEAD)])

    def test_tail_must_be_the_last_message(self):
        write_message(self.memory, MSG1_HEAD, next_head=MSG2_HEAD, priority=5)
        write_message(self.memory, MSG2_HEAD, priority=3)
        empty_queue(self.memory, head=MSG1_HEAD, tail=MSG1_HEAD)
        with self.assertRaisesRegex(ValueError,
                                    'queue_message_tail_inconsistent'):
            validate_local_queue_object(self.memory, QUEUE)

    def test_message_list_cycle_is_refused(self):
        write_message(self.memory, MSG1_HEAD, next_head=MSG1_HEAD, priority=5)
        empty_queue(self.memory, head=MSG1_HEAD, tail=MSG1_HEAD)
        with self.assertRaisesRegex(ValueError, 'queue_message_list_cycle'):
            validate_local_queue_object(self.memory, QUEUE)

    def test_unreadable_message_head_is_refused(self):
        empty_queue(self.memory, head=0x60000000, tail=0x60000000)
        with self.assertRaisesRegex(ValueError, 'message header unreadable'):
            validate_local_queue_object(self.memory, QUEUE)

    def test_receiver_record_kinds_are_reported(self):
        write_record(self.memory, WAITER, next_record=OTHER_RECORD, flags=0x04)
        write_record(self.memory, OTHER_RECORD, flags=0x00,
                     futex_word=0x50002000, out_slot=0x50002004)
        empty_queue(self.memory, records=WAITER)
        queue = validate_local_queue_object(self.memory, QUEUE)
        self.assertEqual(queue['receiver_record_count'], 2)
        self.assertEqual([record['kind'] for record in queue['receiver_records']],
                         ['wait_cb_oneshot', 'callback_registration'])
        self.assertEqual(queue['receiver_records'][0]['field_0x14'], 0)
        self.assertEqual(queue['receiver_records'][0]['field_0x18'], OUT_SLOT)

    def test_unknown_receiver_record_flags_are_refused(self):
        write_record(self.memory, WAITER, flags=0x08)
        empty_queue(self.memory, records=WAITER)
        with self.assertRaisesRegex(ValueError, 'receiver_record_flags_unknown'):
            validate_local_queue_object(self.memory, QUEUE)

    def test_unreadable_object_is_refused(self):
        with self.assertRaisesRegex(ValueError, 'queue object unreadable'):
            validate_local_queue_object(self.memory, 0x60000000)

    def test_short_reader_reply_is_refused(self):
        with self.assertRaisesRegex(ValueError, 'expected'):
            validate_local_queue_object(lambda address, size: b'', QUEUE)

    def test_non_callable_reader_is_refused(self):
        with self.assertRaisesRegex(ValueError, 'reader must be a callable'):
            validate_local_queue_object(None, QUEUE)

    def test_misaligned_object_address_is_refused(self):
        with self.assertRaisesRegex(ValueError, 'not 4-byte aligned'):
            validate_local_queue_object(self.memory, QUEUE + 2)

    def test_constants_document_the_decoded_layout(self):
        self.assertEqual(HEAD_PAYLOAD_BIAS, -0x0C)
        self.assertEqual(QUEUE_OBJECT_SIZE, 0x20)
        self.assertEqual(planner.QUEUE_OBJECT_FIELDS[0x0C], 'message_head')
        self.assertEqual(planner.QUEUE_OBJECT_FIELDS[0x10], 'message_tail')
        self.assertEqual(planner.MESSAGE_PRIORITY_OFFSET, 0x05)
        self.assertEqual(FUTEX_WAKE_PRIVATE, 0x81)
        self.assertIn('osal_snd_msg', planner.PROVENANCE['functions'])
        self.assertIn('eecc322b', planner.PROVENANCE['source'])


class LocalQueuePostPlanTests(unittest.TestCase):
    def setUp(self):
        self.memory = FakeGuestMemory()

    def test_empty_queue_link_plan_without_wake(self):
        empty_queue(self.memory)
        write_message(self.memory, NEW_HEAD, priority=1)
        plan = plan_local_post(self.memory, QUEUE, payload_of(NEW_HEAD))
        self.assertEqual(plan['kind'], 'libosal-local-queue-post')
        self.assertEqual(plan['insertion'], 'empty')
        self.assertEqual(plan['message']['head'], NEW_HEAD)
        self.assertEqual(plan['message']['priority'], 1)
        self.assertEqual([label['label'] for label in plan['write_provenance']],
                         ['message_next', 'queue_head', 'queue_tail'])
        self.assertEqual(plan['writes'], [
            (NEW_HEAD, struct.pack('<I', 0)),
            (QUEUE + 0x0C, struct.pack('<I', NEW_HEAD)),
            (QUEUE + 0x10, struct.pack('<I', NEW_HEAD)),
        ])
        self.assertEqual(plan['wake']['kind'], 'none')
        self.assertEqual(plan['wake']['wake_count'], 0)
        self.assertEqual(plan['delivery']['mode'], 'queued_for_future_receive')
        self.assertEqual(plan['flags']['before'], 0)
        self.assertEqual(plan['flags']['after'], 0)
        self.assertTrue(plan['assumptions'])

    def test_priority_is_read_from_the_message_header(self):
        empty_queue(self.memory)
        write_message(self.memory, NEW_HEAD, priority=42)
        plan = plan_local_post(self.memory, QUEUE, payload_of(NEW_HEAD))
        self.assertEqual(plan['message']['priority'], 42)

    def test_append_below_tail_priority(self):
        write_message(self.memory, MSG1_HEAD, priority=5)
        empty_queue(self.memory, head=MSG1_HEAD, tail=MSG1_HEAD)
        plan = plan_local_post(self.memory, QUEUE, payload_of(NEW_HEAD))
        self.assertEqual(plan['insertion'], 'append')
        self.assertEqual(plan['writes'], [
            (NEW_HEAD, struct.pack('<I', 0)),
            (MSG1_HEAD, struct.pack('<I', NEW_HEAD)),
            (QUEUE + 0x10, struct.pack('<I', NEW_HEAD)),
        ])
        self.assertEqual([label['label'] for label in plan['write_provenance']],
                         ['message_next', 'tail_next', 'queue_tail'])

    def test_prepend_above_head_priority(self):
        write_message(self.memory, MSG1_HEAD, priority=5)
        empty_queue(self.memory, head=MSG1_HEAD, tail=MSG1_HEAD)
        write_message(self.memory, NEW_HEAD, priority=9)
        plan = plan_local_post(self.memory, QUEUE, payload_of(NEW_HEAD))
        self.assertEqual(plan['insertion'], 'prepend')
        self.assertEqual(plan['writes'], [
            (NEW_HEAD, struct.pack('<I', MSG1_HEAD)),
            (QUEUE + 0x0C, struct.pack('<I', NEW_HEAD)),
        ])
        self.assertEqual([label['label'] for label in plan['write_provenance']],
                         ['message_next', 'queue_head'])

    def test_ordered_middle_insertion(self):
        write_message(self.memory, MSG1_HEAD, next_head=MSG2_HEAD, priority=9)
        write_message(self.memory, MSG2_HEAD, next_head=MSG3_HEAD, priority=5)
        write_message(self.memory, MSG3_HEAD, priority=1)
        empty_queue(self.memory, head=MSG1_HEAD, tail=MSG3_HEAD)
        write_message(self.memory, NEW_HEAD, priority=6)
        plan = plan_local_post(self.memory, QUEUE, payload_of(NEW_HEAD))
        self.assertEqual(plan['insertion'], 'ordered')
        self.assertEqual(plan['writes'], [
            (NEW_HEAD, struct.pack('<I', MSG2_HEAD)),
            (MSG1_HEAD, struct.pack('<I', NEW_HEAD)),
        ])
        self.assertEqual([label['label'] for label in plan['write_provenance']],
                         ['message_next', 'predecessor_next'])

    def test_equal_priority_inserts_before_lower_tail(self):
        # [6, 5, 4] + new 5: not <= tail(4), not > head(6); the walk stops
        # after the existing 5 and before 4 (decoded 0x3CE6..0x3CF6 order).
        write_message(self.memory, MSG1_HEAD, next_head=MSG2_HEAD, priority=6)
        write_message(self.memory, MSG2_HEAD, next_head=MSG3_HEAD, priority=5)
        write_message(self.memory, MSG3_HEAD, priority=4)
        empty_queue(self.memory, head=MSG1_HEAD, tail=MSG3_HEAD)
        write_message(self.memory, NEW_HEAD, priority=5)
        plan = plan_local_post(self.memory, QUEUE, payload_of(NEW_HEAD))
        self.assertEqual(plan['insertion'], 'ordered')
        self.assertEqual(plan['writes'], [
            (NEW_HEAD, struct.pack('<I', MSG3_HEAD)),
            (MSG2_HEAD, struct.pack('<I', NEW_HEAD)),
        ])

    def test_queued_plan_is_refused_when_receiver_records_exist(self):
        write_record(self.memory, WAITER)
        empty_queue(self.memory, records=WAITER)
        with self.assertRaisesRegex(
                ValueError, 'receiver_records_registered_but_no_waiter'):
            plan_local_post(self.memory, QUEUE, payload_of(NEW_HEAD))

    def test_message_overlapping_queue_object_is_refused(self):
        empty_queue(self.memory)
        with self.assertRaisesRegex(ValueError, 'message_overlaps_queue_object'):
            plan_local_post(self.memory, QUEUE, QUEUE + 0x0C)

    def test_misaligned_payload_is_refused(self):
        empty_queue(self.memory)
        with self.assertRaisesRegex(ValueError, 'not 4-byte aligned'):
            plan_local_post(self.memory, QUEUE, payload_of(NEW_HEAD) + 2)

    def test_unreadable_message_header_is_refused(self):
        empty_queue(self.memory)
        with self.assertRaisesRegex(ValueError, 'message header unreadable'):
            plan_local_post(self.memory, QUEUE, 0x60000010)

    def test_plan_is_deterministic(self):
        write_message(self.memory, MSG1_HEAD, next_head=MSG2_HEAD, priority=5)
        write_message(self.memory, MSG2_HEAD, priority=3)
        empty_queue(self.memory, head=MSG1_HEAD, tail=MSG2_HEAD)
        write_message(self.memory, NEW_HEAD, priority=4)
        first = plan_local_post(self.memory, QUEUE, payload_of(NEW_HEAD))
        second = plan_local_post(self.memory, QUEUE, payload_of(NEW_HEAD))
        self.assertEqual(first['writes'], second['writes'])
        self.assertEqual(first['write_provenance'], second['write_provenance'])
        self.assertEqual(first['wake'], second['wake'])
        self.assertEqual(first['insertion'], second['insertion'])

    def test_writes_are_bounded_aligned_and_unique(self):
        write_message(self.memory, MSG1_HEAD, next_head=MSG2_HEAD, priority=5)
        write_message(self.memory, MSG2_HEAD, priority=3)
        empty_queue(self.memory, head=MSG1_HEAD, tail=MSG2_HEAD)
        plan = plan_local_post(self.memory, QUEUE, payload_of(NEW_HEAD))
        self.assertLessEqual(len(plan['writes']), MAX_PLAN_WRITES)
        self.assertEqual(plan['bounded']['write_count'], len(plan['writes']))
        addresses = [address for address, _data in plan['writes']]
        self.assertEqual(len(addresses), len(set(addresses)))
        for address, data in plan['writes']:
            self.assertEqual(address % 4, 0)
            self.assertEqual(len(data), 4)

    def test_planner_is_read_only(self):
        write_message(self.memory, MSG1_HEAD, priority=5)
        empty_queue(self.memory, head=MSG1_HEAD, tail=MSG1_HEAD)
        before = bytes(self.memory.memory)
        plan_local_post(self.memory, QUEUE, payload_of(NEW_HEAD))
        validate_local_queue_object(self.memory, QUEUE)
        self.assertEqual(bytes(self.memory.memory), before)
        self.assertGreater(len(self.memory.reads), 0)

    def test_render_post_plan_lines(self):
        empty_queue(self.memory)
        plan = plan_local_post(self.memory, QUEUE, payload_of(NEW_HEAD))
        lines = render_post_plan(plan)
        self.assertIsInstance(lines, list)
        text = '\n'.join(lines)
        self.assertIn('libosal local-queue post plan', text)
        self.assertIn('0x%08x' % QUEUE, text)
        self.assertIn('insertion=empty', text)
        self.assertIn('message_next', text)
        self.assertIn('wake: none', text)
        self.assertIn('delivery: queued_for_future_receive', text)

    def test_module_imports_without_emulator_dependencies(self):
        self.assertFalse(hasattr(planner, 'unicorn'))
        self.assertEqual(planner.HEAD_PAYLOAD_BIAS, -0x0C)


class LocalQueueWaiterDispatchPlanTests(unittest.TestCase):
    def setUp(self):
        self.memory = FakeGuestMemory()
        self.memory.write_u32(OUT_SLOT, 0xFFFFFFFF)
        self.memory.write_u32(FUTEX, 0)
        write_record(self.memory, WAITER)
        empty_queue(self.memory, records=WAITER)

    def _plan(self, waiter=WAITER):
        return plan_local_post(self.memory, QUEUE, payload_of(NEW_HEAD),
                               waiter_addr=waiter)

    def test_waiter_dispatch_writes_ordered_handoff(self):
        plan = self._plan()
        self.assertEqual(plan['insertion'], 'empty')
        self.assertEqual([label['label'] for label in plan['write_provenance']], [
            'message_next',
            'queue_head_after_dispatch',
            'queue_tail_after_dispatch',
            'receiver_list_unlink',
            'waiter_out_slot',
            'waiter_futex_word',
        ])
        self.assertEqual(plan['writes'], [
            (NEW_HEAD, struct.pack('<I', 0)),
            (QUEUE + 0x0C, struct.pack('<I', 0)),
            (QUEUE + 0x10, struct.pack('<I', NEW_HEAD)),
            (QUEUE + 0x08, struct.pack('<I', 0)),
            (OUT_SLOT, struct.pack('<I', payload_of(NEW_HEAD))),
            (FUTEX, struct.pack('<I', 1)),
        ])
        self.assertEqual(plan['delivery']['mode'],
                         'dispatch_to_registered_waiter')
        self.assertEqual(plan['delivery']['delivered_payload'],
                         payload_of(NEW_HEAD))
        self.assertEqual(plan['delivery']['out_slot'], OUT_SLOT)
        self.assertEqual(plan['delivery']['waiter_dispatcher'], DISPATCHER)
        self.assertTrue(plan['bounded']['all_writes_32_bit'])

    def test_waiter_wake_description(self):
        plan = self._plan()
        wake = plan['wake']
        self.assertEqual(wake['kind'], 'futex_wake')
        self.assertEqual(wake['futex_uaddr'], FUTEX)
        self.assertEqual(wake['expected_value'], 1)
        self.assertEqual(wake['value_write'], 1)
        self.assertEqual(wake['futex_op'], 'FUTEX_WAKE_PRIVATE')
        self.assertEqual(wake['futex_op_value'], FUTEX_WAKE_PRIVATE)
        self.assertEqual(wake['wake_count'], 1)
        self.assertEqual(wake['waiter'], WAITER)
        self.assertEqual(wake['waiter_out_slot'], OUT_SLOT)
        self.assertEqual(wake['delivered_payload'], payload_of(NEW_HEAD))

    def test_waiter_plan_renders_wake_line(self):
        lines = render_post_plan(self._plan())
        text = '\n'.join(lines)
        self.assertIn('futex 0x%08x' % FUTEX, text)
        self.assertIn('FUTEX_WAKE_PRIVATE', text)
        self.assertIn('expected value 1', text)

    def test_waiter_with_pending_message_is_refused(self):
        write_message(self.memory, MSG1_HEAD, priority=5)
        write_queue(self.memory, records=WAITER, head=MSG1_HEAD, tail=MSG1_HEAD)
        with self.assertRaisesRegex(
                ValueError, 'waiter_dispatch_with_pending_messages'):
            self._plan()

    def test_waiter_must_be_the_registered_head(self):
        write_queue(self.memory, records=OTHER_RECORD)
        with self.assertRaisesRegex(ValueError, 'waiter_not_registered_head'):
            self._plan()

    def test_multiple_receiver_records_are_refused(self):
        write_record(self.memory, OTHER_RECORD)
        write_queue(self.memory, records=WAITER)
        write_record(self.memory, WAITER, next_record=OTHER_RECORD)
        with self.assertRaisesRegex(ValueError, 'receiver_record_set_unmodelled'):
            self._plan()

    def test_no_registered_waiter_is_refused(self):
        empty_queue(self.memory)
        with self.assertRaisesRegex(ValueError, 'receiver_record_set_unmodelled'):
            self._plan()

    def test_waiter_requires_one_shot_flag(self):
        write_record(self.memory, WAITER, flags=0x00)
        with self.assertRaisesRegex(ValueError, 'waiter_flags_unmodelled'):
            self._plan()

    def test_waiter_skip_flag_is_refused(self):
        write_record(self.memory, WAITER, flags=0x02)
        with self.assertRaisesRegex(ValueError, 'waiter_skip_flag_unmodelled'):
            self._plan()

    def test_waiter_dispatcher_is_required(self):
        write_record(self.memory, WAITER, dispatcher=0)
        with self.assertRaisesRegex(ValueError, 'waiter_dispatcher_missing'):
            self._plan()

    def test_waiter_out_slot_must_be_readable(self):
        write_record(self.memory, WAITER, out_slot=0x60000000)
        with self.assertRaisesRegex(ValueError, 'waiter out-slot'):
            self._plan()

    def test_waiter_out_slot_must_be_aligned(self):
        write_record(self.memory, WAITER, out_slot=OUT_SLOT + 2)
        with self.assertRaisesRegex(ValueError, 'not 4-byte aligned'):
            self._plan()

    def test_waiter_plan_is_deterministic_and_read_only(self):
        before = bytes(self.memory.memory)
        first = self._plan()
        second = self._plan()
        self.assertEqual(first['writes'], second['writes'])
        self.assertEqual(first['wake'], second['wake'])
        self.assertEqual(bytes(self.memory.memory), before)


if __name__ == '__main__':
    unittest.main()
