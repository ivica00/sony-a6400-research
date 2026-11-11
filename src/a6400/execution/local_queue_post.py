"""Pure planner for a libosal_uipc user-space LOCAL queue post (no execution).

Evidence (E0329/E0330/E0310; re-verified against the live and extracted
``libosal_uipc.so``: every function body cited here is byte-identical in the
live capture sha256 ``eecc322b...`` and the a6400 extracted build sha256
``b6ded35a...``):

* ``osal_snd_msg`` (Thumb 0x3C34, 272 B) is called with a bit-15 queue id and a
  message payload pointer.  Ids with bit 15 set take the process-local
  user-space path: ``get_msgq`` (0x3604 -> lookup 0x33C4 / create 0x341C)
  returns the queue object, the message *head* is ``payload - 0xC``, and the
  sender links it into the object's priority-ordered message list at
  ``+0xC``/``+0x10``.
* Queue-object layout (create 0x341C zero-fills the 0x20-byte object):
  ``+0x00`` lock word (osal_lock 0x4FBC: bit31 held + holder count),
  ``+0x04`` flags byte (bit0 broadcast mode for ids 0x4000-0x5FFF, bit3
  async/notify for ids 0x6000-0x7FFF, bit1 transient "dispatch in progress"),
  ``+0x08`` receiver-record list head (one-shot WAIT_CB wait nodes and
  persistent callback registrations share it), ``+0x0C`` message-list head,
  ``+0x10`` message-list tail (may stay stale after the last dequeue),
  ``+0x18`` sync-callback node, ``+0x1C`` async/notify field.
* Message head: ``+0x00`` next pointer, ``+0x05`` priority byte (low 6 bits;
  ``osal_get_msg_pri`` 0x4408 reads ``[payload-7] & 0x3F``).  The list is
  ordered by descending priority from the head: the send path appends at the
  tail when ``new <= tail_priority``, prepends when ``new > head_priority``,
  and otherwise inserts before the first successor whose priority is lower
  than the new message's.
* Send wake path: after insertion ``osal_snd_msg`` calls dispatcher 0x3848.
  With no receiver records the message simply stays queued.  With a one-shot
  WAIT_CB wait record (flags byte +0x0D bit 0x04) the dispatcher pops the head
  message, unlinks that record from ``+0x08``, and calls the record's
  dispatcher (0x32B0), which writes the payload to the waiter's out-slot
  (``*[record+0x18] = payload``) and calls ``wakeup`` (0x5100: store 1 at the
  futex word living at ``record+0x14``, then
  ``futex(record+0x14, FUTEX_WAKE_PRIVATE(0x81), 1)``).
  ``osal_rcv_msg_tmo`` (0x3ED8) re-checks that out-slot after the wake and
  returns the payload.

This module is a *planner*: ``reader`` is a host-supplied
``memory_reader(addr, size) -> bytes`` callable (typically the emulator's guest
memory reader).  The returned ordered write list and wake description must be
applied by the caller; nothing here executes, imports Unicorn/firmware, or
mutates memory.

Every entry point fails closed with ``ValueError`` when the queue, message or
waiter state is outside the verified path (unlocked object at rest with flags
0 and a consistent list; a single registered one-shot WAIT_CB head record for
dispatch) instead of guessing.
"""
from __future__ import annotations

import struct

# ---------------------------------------------------------------------------
# Layout constants (OBSERVED: libosal_uipc.so disassembly; provenance below).
# ---------------------------------------------------------------------------
HEAD_PAYLOAD_BIAS = -0x0C
QUEUE_OBJECT_SIZE = 0x20
QUEUE_OBJECT_FIELDS = {
    0x00: 'lock_word',
    0x04: 'flags',
    0x08: 'receiver_record_list_head',
    0x0C: 'message_head',
    0x10: 'message_tail',
    0x14: 'unverified_0x14',
    0x18: 'sync_callback_node',
    0x1C: 'async_notify_field',
    0x20: 'unverified_0x20',
}

QUEUE_FLAG_BROADCAST = 0x01
QUEUE_FLAG_DISPATCH_IN_PROGRESS = 0x02
QUEUE_FLAG_ASYNC_NOTIFY = 0x08
QUEUE_FLAG_KNOWN_MASK = (QUEUE_FLAG_BROADCAST
                         | QUEUE_FLAG_DISPATCH_IN_PROGRESS
                         | QUEUE_FLAG_ASYNC_NOTIFY)

MESSAGE_HEADER_SIZE = 0x0C
MESSAGE_NEXT_OFFSET = 0x00
MESSAGE_PRIORITY_OFFSET = 0x05
MESSAGE_PRIORITY_MASK = 0x3F

RECEIVER_RECORD_SIZE = 0x20
# Shared record layout: +0x00 next, +0x08 dispatcher, +0x0C activity,
# +0x0D flags, +0x14 a word interpreted per record kind (WAIT_CB: the futex
# word itself, whose address is record+0x14; callback registration: callback
# pointer), +0x18 a word interpreted per record kind (WAIT_CB: out-slot
# pointer; callback registration: user_data).  The meaning is therefore kept
# under raw field names here.
RECEIVER_RECORD_FIELDS = {
    0x00: 'next',
    0x08: 'dispatcher',
    0x0C: 'activity',
    0x0D: 'flags',
    0x14: 'futex_word_or_callback',
    0x18: 'out_slot_pointer_or_user_data',
}
RECORD_FLAG_SKIP = 0x02
RECORD_FLAG_DISPATCH_ONESHOT = 0x04
RECORD_FLAG_KNOWN_MASK = RECORD_FLAG_SKIP | RECORD_FLAG_DISPATCH_ONESHOT

FUTEX_WAKE_PRIVATE = 0x81
FUTEX_WAKE_COUNT = 1

MAX_QUEUE_MESSAGES = 4096
MAX_RECEIVER_RECORDS = 4096
MAX_PLAN_WRITES = 8

PROVENANCE = {
    'source': 'libosal_uipc.so (live capture sha256 '
              'eecc322b81ebf63b26829fb2e8beee43af56f571b0ffbfc16d234dee5063becf; '
              'a6400 extracted build sha256 '
              'b6ded35add9582413b401cf4db78ec2c9a201b632e78c2731d6bbb379249b3eb; '
              'cited function bodies are byte-identical in both builds)',
    'functions': {
        'osal_snd_msg': {'thumb_va': 0x3C34, 'size': 272,
                         'role': 'local send path: flags check, get_msgq, lock, '
                                 'priority insert at +0xC/+0x10, dispatch 0x3848'},
        'osal_rcv_msg_tmo': {'thumb_va': 0x3ED8, 'size': 276,
                             'role': 'receive path: dequeue head+0xC, or build a '
                                     'WAIT_CB record and sleep'},
        'get_msgq': {'thumb_va': 0x3604,
                     'role': 'lookup 0x33C4 or create 0x341C'},
        'queue_create': {'thumb_va': 0x341C,
                         'role': 'zero-fills the 0x20-byte object; flags bit0 for '
                                 'ids 0x4000-0x5FFF, bit3 for ids 0x6000-0x7FFF'},
        'dispatch': {'thumb_va': 0x3848,
                     'role': 'transient flags bit1, pop head, unlink one-shot '
                             'record, call record dispatcher, clear bit1'},
        'wait_record_dispatcher': {'thumb_va': 0x32B0,
                                   'role': 'write payload to *[record+0x18]; '
                                           'wakeup(record+0x14)'},
        'wakeup': {'thumb_va': 0x5100,
                   'role': 'store 1 at uaddr; futex(uaddr, 0x81, 1)'},
        'osal_get_msg_pri': {'thumb_va': 0x4408,
                             'role': 'priority = [payload-7] & 0x3F'},
        'osal_lock': {'thumb_va': 0x4FBC,
                      'role': 'lock word bit31 + count at object+0x00'},
        'osal_unlock': {'thumb_va': 0x502C},
        'reg_wait_record': {'thumb_va': 0x3A5C,
                            'role': 'append a record at object+0x08; immediate '
                                    'dispatch if a message head exists and flags '
                                    'bit1 is clear'},
    },
    'labels': {
        'HEAD_PAYLOAD_BIAS': 'OBSERVED: osal_snd_msg 0x3CA2 sub r5,r4,#0xC; '
                             'osal_rcv_msg_tmo 0x3F5C adds #0xC to the head',
        'QUEUE_OBJECT_FIELDS': 'OBSERVED: create 0x341C zero-fill plus sender/'
                               'receiver/dispatcher field reads',
        'MESSAGE_PRIORITY_OFFSET': 'OBSERVED: osal_snd_msg 0x3CB2/0x3CB4 '
                                   'ldrb [head+5]; osal_get_msg_pri [payload-7]',
        'RECEIVER_RECORD_FIELDS': 'OBSERVED: osal_rcv_msg_tmo 0x3F84..0x3F98 '
                                  '(memset 0x20; +8 dispatcher; +0xD=4; +0x18 '
                                  'out-slot; +0x14 futex) and dispatcher 0x32B0',
        'QUEUE_FLAG_DISPATCH_IN_PROGRESS': 'OBSERVED: dispatch 0x3848 orr/bic '
                                           '#2 around the synchronous handoff',
    },
}

_DEFAULT_UNKNOWN = (
    'queue-object fields +0x14/+0x20 are zero-initialised by create 0x341C but '
    'not decoded; they are recorded, never written',
    'async/notify send path (flags bit3, field +0x1C) and broadcast mode '
    '(flags bit0) are not modelled',
    'the record dispatcher call itself, the record activity byte (+0xC) and '
    'TLS identity word (+0x10) are original runtime side effects; the plan '
    'only performs the memory handoff the receiver re-checks (out-slot)',
    'no sender-side message allocation/serialization is modelled; the caller '
    'must supply the message header/payload already in guest memory',
)


# ---------------------------------------------------------------------------
# Reader helpers (fail closed on unreadable or malformed state).
# ---------------------------------------------------------------------------
def _read_bytes(reader, address, size, what):
    if not callable(reader):
        raise ValueError('reader must be a callable memory_reader(addr, size)')
    try:
        raw = reader(int(address), int(size))
    except Exception as error:
        raise ValueError('%s unreadable at 0x%08x: %s' % (what, address, error))
    if not isinstance(raw, (bytes, bytearray)) or len(raw) != size:
        raise ValueError('%s at 0x%08x returned %r bytes, expected %d'
                         % (what, address, 0 if raw is None else len(raw), size))
    return bytes(raw)


def _read_u32(reader, address, what):
    return struct.unpack('<I', _read_bytes(reader, address, 4, what))[0]


def _require_aligned(address, what):
    if not isinstance(address, int) or address <= 0:
        raise ValueError('%s must be a positive address, got %r' % (what, address))
    if address % 4:
        raise ValueError('%s 0x%08x is not 4-byte aligned' % (what, address))
    return address


# ---------------------------------------------------------------------------
# Validators.
# ---------------------------------------------------------------------------
def validate_local_queue_object(reader, obj_addr):
    """Read and sanity-check a libosal user-space queue object.

    Returns a dict describing the object and its linked lists.  Raises
    ``ValueError`` (fail closed) for a locked/mid-dispatch object, unknown or
    unmodelled flag bits, unreadable/cyclic/overlong lists, or an unreachable
    tail.  Only the verified quiescent path (lock 0, flags 0) is accepted.
    """
    obj_addr = _require_aligned(obj_addr, 'queue object address')
    raw = _read_bytes(reader, obj_addr, QUEUE_OBJECT_SIZE, 'queue object')
    lock, flags_word = struct.unpack_from('<II', raw, 0x00)
    flags = flags_word & 0xFF
    records_head, message_head, message_tail = struct.unpack_from('<III', raw, 0x08)
    unverified_14, sync_callback_node, async_notify_field = \
        struct.unpack_from('<III', raw, 0x14)
    unverified_20 = None

    if lock != 0:
        raise ValueError(
            'queue_object_locked: lock word 0x%08x at 0x%08x (osal_lock keeps '
            'bit31 + holder count; a post may only be planned at rest)'
            % (lock, obj_addr))
    unknown = flags & ~QUEUE_FLAG_KNOWN_MASK
    if unknown:
        raise ValueError('queue_object_unknown_flags: 0x%02x at 0x%08x'
                         % (flags, obj_addr + 0x04))
    if flags & QUEUE_FLAG_BROADCAST:
        raise ValueError('queue_object_broadcast_mode_unmodelled: flags 0x%02x '
                         '(ids 0x4000-0x5FFF take the unmodelled bit0 path)'
                         % (flags,))
    if flags & QUEUE_FLAG_ASYNC_NOTIFY:
        raise ValueError('queue_object_async_notify_unmodelled: flags 0x%02x '
                         '(ids 0x6000-0x7FFF take the unmodelled bit3 path)'
                         % (flags,))
    if flags & QUEUE_FLAG_DISPATCH_IN_PROGRESS:
        raise ValueError('queue_object_dispatch_in_progress: flags 0x%02x '
                         '(transient dispatch bit set; queue is not at rest)'
                         % (flags,))

    messages = _walk_messages(reader, message_head)
    if messages:
        if message_tail != messages[-1]['head']:
            raise ValueError(
                'queue_message_tail_inconsistent: tail 0x%08x is not the last '
                'message head 0x%08x' % (message_tail, messages[-1]['head']))
        stale_tail = None
    else:
        # E0310/E0336: the tail slot may remain stale after the last dequeue.
        stale_tail = message_tail or None
    records = _walk_receiver_records(reader, records_head)

    return {
        'kind': 'libosal-local-queue-object',
        'object': obj_addr,
        'lock': lock,
        'flags': flags,
        'receiver_record_list_head': records_head,
        'message_head': message_head,
        'message_tail': message_tail,
        'stale_tail': stale_tail,
        'sync_callback_node': sync_callback_node,
        'async_notify_field': async_notify_field,
        'unverified_fields': {'0x14': unverified_14, '0x20': unverified_20},
        'empty': not messages,
        'messages': messages,
        'receiver_records': records,
        'receiver_record_count': len(records),
        'ready': True,
        'assumptions': [
            'queue object is at rest: lock word 0 and flags 0 (the verified '
            'osal_snd_msg path); transient dispatch bit1 is not set',
            'message list order is descending priority from the head; a '
            'non-empty list requires tail == last message head',
            'receiver-record list may hold one-shot WAIT_CB wait nodes '
            '(flags bit 0x04) and persistent callback registrations (flags 0); '
            'only the one-shot form is modelled for dispatch',
        ],
        'unknowns': list(_DEFAULT_UNKNOWN),
        'provenance': dict(PROVENANCE),
    }


def _walk_messages(reader, head):
    messages = []
    seen = set()
    address = head
    while address:
        _require_aligned(address, 'message head')
        if address in seen:
            raise ValueError('queue_message_list_cycle at 0x%08x' % (address,))
        if len(messages) >= MAX_QUEUE_MESSAGES:
            raise ValueError('queue_message_list_too_long (limit %d)'
                             % (MAX_QUEUE_MESSAGES,))
        seen.add(address)
        raw = _read_bytes(reader, address, MESSAGE_HEADER_SIZE, 'message header')
        next_head = struct.unpack_from('<I', raw, MESSAGE_NEXT_OFFSET)[0]
        priority = raw[MESSAGE_PRIORITY_OFFSET] & MESSAGE_PRIORITY_MASK
        messages.append({
            'head': address,
            'payload': address - HEAD_PAYLOAD_BIAS,
            'next': next_head,
            'priority': priority,
        })
        if next_head:
            _require_aligned(next_head, 'message next pointer')
        address = next_head
    return messages


def _walk_receiver_records(reader, records_head):
    records = []
    seen = set()
    address = records_head
    while address:
        _require_aligned(address, 'receiver record address')
        if address in seen:
            raise ValueError('queue_receiver_list_cycle at 0x%08x' % (address,))
        if len(records) >= MAX_RECEIVER_RECORDS:
            raise ValueError('queue_receiver_list_too_long (limit %d)'
                             % (MAX_RECEIVER_RECORDS,))
        seen.add(address)
        raw = _read_bytes(reader, address, RECEIVER_RECORD_SIZE,
                          'receiver record')
        flags = raw[0x0D]
        unknown = flags & ~RECORD_FLAG_KNOWN_MASK
        if unknown:
            raise ValueError('receiver_record_flags_unknown: 0x%02x at 0x%08x'
                             % (flags, address + 0x0D))
        next_record = struct.unpack_from('<I', raw, 0x00)[0]
        if next_record:
            _require_aligned(next_record, 'receiver record next pointer')
        if flags & RECORD_FLAG_DISPATCH_ONESHOT:
            kind = 'wait_cb_oneshot'
        elif flags & RECORD_FLAG_SKIP:
            kind = 'skip_marked'
        else:
            kind = 'callback_registration'
        records.append({
            'record': address,
            'kind': kind,
            'next': next_record,
            'flags': flags,
            'dispatcher': struct.unpack_from('<I', raw, 0x08)[0],
            'activity': raw[0x0C],
            'field_0x14': struct.unpack_from('<I', raw, 0x14)[0],
            'field_0x18': struct.unpack_from('<I', raw, 0x18)[0],
        })
        address = next_record
    return records


def _message_priority(reader, head):
    raw = _read_bytes(reader, head + MESSAGE_PRIORITY_OFFSET, 1,
                      'message priority')
    return raw[0] & MESSAGE_PRIORITY_MASK


# ---------------------------------------------------------------------------
# Planner.
# ---------------------------------------------------------------------------
def _insertion(obj_addr, messages, new_priority):
    """Mirror osal_snd_msg 0x3CA0..0x3D14 priority insertion.

    Returns ``(kind, next_pointer_value, links)`` where ``links`` is a list of
    ``{'label', 'address', 'evidence'}`` words that must be set to ``new_head``.
    """
    if not messages:
        return ('empty', 0, [
            {'label': 'queue_head', 'address': obj_addr + 0x0C,
             'evidence': 'osal_snd_msg 0x3D0A: queue+0x0C = message'},
            {'label': 'queue_tail', 'address': obj_addr + 0x10,
             'evidence': 'osal_snd_msg 0x3D0C: queue+0x10 = message'},
        ])
    tail = messages[-1]
    if new_priority <= tail['priority']:
        return ('append', 0, [
            {'label': 'tail_next', 'address': tail['head'],
             'evidence': 'osal_snd_msg 0x3CC4: tail.next = message '
                         '(new_priority <= tail_priority)'},
            {'label': 'queue_tail', 'address': obj_addr + 0x10,
             'evidence': 'osal_snd_msg 0x3D0C: queue+0x10 = message'},
        ])
    head = messages[0]
    if new_priority > head['priority']:
        return ('prepend', head['head'], [
            {'label': 'queue_head', 'address': obj_addr + 0x0C,
             'evidence': 'osal_snd_msg 0x3CD2/0x3CF6: queue+0x0C = message '
                         '(new_priority > head_priority)'},
        ])
    predecessor = messages[0]
    successor = None
    for candidate in messages[1:]:
        if new_priority > candidate['priority']:
            successor = candidate
            break
        predecessor = candidate
    if successor is None:
        # Unreachable for a consistent descending list (tail would be the
        # append case); fail closed rather than guess.
        raise ValueError('queue_insertion_unresolved')
    return ('ordered', successor['head'], [
        {'label': 'predecessor_next', 'address': predecessor['head'],
         'evidence': 'osal_snd_msg 0x3CE6..0x3CF6: predecessor.next = message '
                     '(descending priority walk)'},
    ])


def plan_local_post(reader, obj_addr, msg_payload_addr, waiter_addr=None):
    """Plan one libosal local-queue post; returns writes + wake description.

    ``reader(addr, size) -> bytes`` reads guest memory; nothing is executed or
    written.  The optional ``waiter_addr`` is the registered one-shot WAIT_CB
    record at the queue's ``+0x08`` head, which the decoded dispatcher would
    consume.  Without it the message is linked into the queue and no wake is
    planned (refused when receiver records exist, because the original send
    path would invoke/dispatch them).

    Returned dict::

        {
          'kind': 'libosal-local-queue-post',
          'queue': <validate_local_queue_object() result>,
          'message': {'payload', 'head', 'priority'},
          'insertion': 'empty'|'append'|'prepend'|'ordered',
          'writes': [(addr, bytes), ...],        # ordered, <= MAX_PLAN_WRITES
          'write_provenance': [{'label','evidence'}],
          'wake': {...},
          'delivery': {...},
          'flags': {...},
          'bounded': {...},
          'assumptions': [...],
          'unknowns': [...],
          'provenance': {...},
        }
    """
    queue = validate_local_queue_object(reader, obj_addr)
    payload = _require_aligned(msg_payload_addr, 'message payload address')
    head = payload + HEAD_PAYLOAD_BIAS
    _require_aligned(head, 'message head')
    _read_bytes(reader, head, MESSAGE_HEADER_SIZE, 'message header')
    priority = _message_priority(reader, head)
    if obj_addr <= head < obj_addr + QUEUE_OBJECT_SIZE:
        raise ValueError('message_overlaps_queue_object: head 0x%08x is inside '
                         'object 0x%08x' % (head, obj_addr))

    writes = []
    write_provenance = []

    def add_write(label, address, data, evidence):
        if len(data) != 4:
            raise ValueError('internal write is not one 32-bit word: %r'
                             % (label,))
        writes.append((int(address), bytes(data)))
        write_provenance.append({'label': label, 'evidence': evidence})

    flags_plan = {
        'before': queue['flags'],
        'after': queue['flags'],
        'writes': [],
        'transient': {'set': QUEUE_FLAG_DISPATCH_IN_PROGRESS,
                      'cleared': QUEUE_FLAG_DISPATCH_IN_PROGRESS,
                      'note': 'dispatch 0x3848 sets and clears bit1 around the '
                              'synchronous handoff; net zero for the atomic plan, '
                              'so no persistent flag write is planned'},
    }
    insertion = 'empty'

    if waiter_addr is None:
        if queue['receiver_records']:
            raise ValueError(
                'receiver_records_registered_but_no_waiter_supplied: queue '
                '0x%08x has %d receiver record(s) at +0x08; the decoded send '
                'path would dispatch/callback them, so a queued-only plan would '
                'diverge' % (obj_addr, len(queue['receiver_records'])))
        insertion, next_pointer, links = _insertion(
            obj_addr, queue['messages'], priority)
        add_write('message_next', head + MESSAGE_NEXT_OFFSET,
                  struct.pack('<I', next_pointer),
                  'osal_snd_msg 0x3CEE: new_message.next = link target')
        for link in links:
            add_write(link['label'], link['address'],
                      struct.pack('<I', head), link['evidence'])
        wake = {'kind': 'none',
                'reason': 'no_waiter_supplied (message stays queued for a '
                          'later osal_rcv_msg_tmo)',
                'futex_uaddr': None, 'expected_value': None,
                'value_write': None, 'futex_op': None, 'futex_op_value': None,
                'wake_count': 0}
        delivery = {'mode': 'queued_for_future_receive',
                    'delivered_payload': None, 'out_slot': None, 'waiter': None}
    else:
        waiter_addr = _require_aligned(waiter_addr, 'waiter record address')
        if not queue['empty']:
            raise ValueError(
                'waiter_dispatch_with_pending_messages_unmodelled: queue '
                '0x%08x already has message head 0x%08x; the decoded dispatcher '
                'pops the existing head, not this post'
                % (obj_addr, queue['message_head']))
        if queue['receiver_record_count'] != 1:
            raise ValueError(
                'receiver_record_set_unmodelled: queue 0x%08x has %d records; '
                'the verified dispatch model covers exactly one one-shot '
                'WAIT_CB record' % (obj_addr, queue['receiver_record_count']))
        if queue['receiver_record_list_head'] != waiter_addr:
            raise ValueError(
                'waiter_not_registered_head: queue+0x08 is 0x%08x, not the '
                'supplied waiter 0x%08x (dispatch 0x3848 unlinks only the '
                'registered head)' % (queue['receiver_record_list_head'],
                                      waiter_addr))
        record = _read_waiter_for_dispatch(reader, waiter_addr)
        # Queue was empty; insert then the decoded dispatcher pops the head and
        # delivers it to the one-shot waiter, leaving +0x10 stale at the
        # delivered message (observed E0310/E0336 post-dequeue tail state).
        add_write('message_next', head + MESSAGE_NEXT_OFFSET,
                  struct.pack('<I', 0),
                  'osal_snd_msg 0x3CEE: new_message.next = 0 (single message)')
        add_write('queue_head_after_dispatch', obj_addr + 0x0C,
                  struct.pack('<I', 0),
                  'osal_snd_msg 0x3D0A + dispatch 0x3882-0x3884: queue+0x0C = '
                  'message.next = 0 after the synchronous pop')
        add_write('queue_tail_after_dispatch', obj_addr + 0x10,
                  struct.pack('<I', head),
                  'dispatch does not update +0x10 when popping the head; the '
                  'tail stays stale at the delivered message (E0310/E0336)')
        add_write('receiver_list_unlink', obj_addr + 0x08,
                  struct.pack('<I', record['next']),
                  'dispatch 0x3890-0x3894: queue+0x08 = record.next (one-shot '
                  'WAIT_CB record consumed)')
        add_write('waiter_out_slot', record['out_slot'],
                  struct.pack('<I', payload),
                  'wait-record dispatcher 0x32B0: *[record+0x18] = head+0xC '
                  '(the payload osal_rcv_msg_tmo re-checks)')
        add_write('waiter_futex_word', record['futex_uaddr'],
                  struct.pack('<I', 1),
                  'wakeup 0x5100: store 1 at [record+0x14] before '
                  'futex(uaddr, FUTEX_WAKE_PRIVATE, 1)')
        wake = {
            'kind': 'futex_wake',
            'futex_uaddr': record['futex_uaddr'],
            'expected_value': 1,
            'value_write': 1,
            'futex_op': 'FUTEX_WAKE_PRIVATE',
            'futex_op_value': FUTEX_WAKE_PRIVATE,
            'wake_count': FUTEX_WAKE_COUNT,
            'waiter': waiter_addr,
            'waiter_out_slot': record['out_slot'],
            'delivered_payload': payload,
            'classification': 'OBSERVED wakeup 0x5100 (store 1 + futex wake); '
                              'osal_rcv_msg_tmo 0x3FB6 re-checks the out-slot '
                              'and returns the payload',
        }
        delivery = {
            'mode': 'dispatch_to_registered_waiter',
            'delivered_payload': payload,
            'out_slot': record['out_slot'],
            'waiter': waiter_addr,
            'waiter_dispatcher': record['dispatcher'],
            'note': 'the original dispatcher call and record activity/TLS '
                    'bookkeeping are runtime side effects; this plan only '
                    'performs the memory handoff the receiver re-checks',
        }

    _assert_bounded_writes(writes)
    return {
        'kind': 'libosal-local-queue-post',
        'queue': queue,
        'message': {'payload': payload, 'head': head, 'priority': priority},
        'insertion': insertion,
        'writes': writes,
        'write_provenance': write_provenance,
        'wake': wake,
        'delivery': delivery,
        'flags': flags_plan,
        'bounded': {'write_count': len(writes),
                    'max_writes': MAX_PLAN_WRITES,
                    'all_writes_32_bit': True},
        'assumptions': [
            'guest memory already contains the message header at payload-0xC '
            '(12 bytes; priority byte at head+5) supplied by the caller',
            'the queue object and its list nodes are at rest (lock 0, flags 0)',
            'a supplied waiter is the single registered one-shot WAIT_CB record '
            '(flags byte bit 0x04) at queue+0x08',
            'applying the ordered writes and then performing the described '
            'futex wake reproduces the decoded osal_snd_msg -> dispatch -> '
            'wake handoff; it is a labelled model, not a captured sender '
            'execution',
        ],
        'unknowns': list(_DEFAULT_UNKNOWN),
        'provenance': dict(PROVENANCE),
    }


def _read_waiter_for_dispatch(reader, waiter_addr):
    raw = _read_bytes(reader, waiter_addr, RECEIVER_RECORD_SIZE, 'wait record')
    flags = raw[0x0D]
    unknown = flags & ~RECORD_FLAG_KNOWN_MASK
    if unknown:
        raise ValueError('receiver_record_flags_unknown: 0x%02x at 0x%08x'
                         % (flags, waiter_addr + 0x0D))
    if flags & RECORD_FLAG_SKIP:
        raise ValueError('waiter_skip_flag_unmodelled: flags 0x%02x at 0x%08x '
                         '(dispatch 0x3906 skips/frees such records)'
                         % (flags, waiter_addr))
    if not flags & RECORD_FLAG_DISPATCH_ONESHOT:
        raise ValueError('waiter_flags_unmodelled: 0x%02x at 0x%08x (the '
                         'verified one-shot dispatch path requires flag bit '
                         '0x04)' % (flags, waiter_addr))
    record = {
        'record': waiter_addr,
        'next': struct.unpack_from('<I', raw, 0x00)[0],
        'dispatcher': struct.unpack_from('<I', raw, 0x08)[0],
        'activity': raw[0x0C],
        'flags': flags,
        # The WAIT_CB futex word is the record field at +0x14 (do_sleep_tmo is
        # called with r0 = record+0x14; wakeup stores 1 there).  The record's
        # +0x18 word is the out-slot pointer the dispatcher stores to.
        'futex_uaddr': waiter_addr + 0x14,
        'futex_word_before': struct.unpack_from('<I', raw, 0x14)[0],
        'out_slot': struct.unpack_from('<I', raw, 0x18)[0],
    }
    _require_aligned(record['out_slot'], 'waiter out-slot')
    if not record['dispatcher']:
        raise ValueError('waiter_dispatcher_missing at 0x%08x' % (waiter_addr,))
    # The out-slot must be readable so the handoff cannot silently target
    # unmapped memory (the futex word is inside the record already read).
    _read_u32(reader, record['out_slot'], 'waiter out-slot')
    return record


def _assert_bounded_writes(writes):
    if len(writes) > MAX_PLAN_WRITES:
        raise ValueError('plan_write_limit_exceeded: %d > %d'
                         % (len(writes), MAX_PLAN_WRITES))
    addresses = set()
    for address, data in writes:
        _require_aligned(address, 'planned write address')
        if len(data) != 4:  # every verified queue/link write is one word
            raise ValueError('plan_write_not_32_bit at 0x%08x' % (address,))
        if address in addresses:
            raise ValueError('plan_write_overlap at 0x%08x' % (address,))
        addresses.add(address)


# ---------------------------------------------------------------------------
# Rendering.
# ---------------------------------------------------------------------------
def render_post_plan(plan):
    """Render a post plan as deterministic human-readable report lines."""
    queue = plan['queue']
    message = plan['message']
    lines = [
        'libosal local-queue post plan (observe-only model, not executed)',
        '  queue object 0x%08x: flags=0x%02x lock=0x%08x '
        'receiver_records=0x%08x head=0x%08x tail=0x%08x' % (
            queue['object'], queue['flags'], queue['lock'],
            queue['receiver_record_list_head'], queue['message_head'],
            queue['message_tail']),
        '  message payload 0x%08x head 0x%08x priority=%d insertion=%s' % (
            message['payload'], message['head'], message['priority'],
            plan['insertion']),
        '  ordered writes (%d, bounded by %d):' % (
            len(plan['writes']), plan['bounded']['max_writes']),
    ]
    for index, (address, data) in enumerate(plan['writes']):
        provenance = plan['write_provenance'][index]
        lines.append('    [%d] 0x%08x <- %s  # %s (%s)' % (
            index, address, data.hex(), provenance['label'],
            provenance['evidence']))
    wake = plan['wake']
    if wake['kind'] == 'futex_wake':
        lines.append(
            '  wake: store %d at futex 0x%08x then FUTEX_WAKE_PRIVATE(0x%02x) '
            'x%d (expected value %d; waiter 0x%08x -> out-slot 0x%08x)' % (
                wake['value_write'], wake['futex_uaddr'],
                wake['futex_op_value'], wake['wake_count'],
                wake['expected_value'], wake['waiter'],
                wake['waiter_out_slot']))
    else:
        lines.append('  wake: none (%s)' % (wake['reason'],))
    delivered = plan['delivery']['delivered_payload']
    lines.append('  delivery: %s (payload %s)' % (
        plan['delivery']['mode'],
        '0x%08x' % delivered if delivered else 'queued'))
    lines.append('  flags: before=0x%02x after=0x%02x; transient bit '
                 'set/cleared=0x%02x' % (
                     plan['flags']['before'], plan['flags']['after'],
                     plan['flags']['transient']['set']))
    for assumption in plan['assumptions']:
        lines.append('  assumption: %s' % (assumption,))
    return lines
