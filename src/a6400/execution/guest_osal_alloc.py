"""Pure planner for guest libosal message allocation (OSAL fblock / vpool).

Why: the E0335 audit (`artifacts/analysis/e0335-local-queue-object.md` §9,
`e0335-e0686-audit.json`) showed that an injected payload allocated from the
*emulator* UIPC pool is later freed by the original `UsbControl::RcvMsg` via
`osal_free_msg`, which pushes the foreign block onto the guest fblock free list
(`libosal+0xEF38` head became `0x503B3CE0`) and underflows the queue object's
`+0x06` u16 allocation counter to `0xFFFF`.  A guest-owned payload must be
allocated the way the original allocator does it.

Decoded from the live/extracted `libosal_uipc.so` (live capture sha256
``eecc322b...``; the a6400 extracted build body is byte-identical for every
function below — see PROVENANCE):

* `osal_valloc_msg_wait` (Thumb 0x3FEC): bit-15 local path; masks the queue id
  to 15 bits, rejects size > 0x1000 with -0x400, then calls the core
  `alloc_msg_by_queue` (0x361C).
* `alloc_msg_by_queue` (0x361C): lookup/create the queue object (0x33C4 /
  0x341C); with async/notify flag bit3 clear and no per-queue vpool override
  (`obj+0x1C == 0`) it allocates **fblock 0x20-byte blocks** when
  ``size <= 0x14`` and **global vpool** blocks otherwise.  It then increments
  the object's `+0x06` u16 counter and writes the 12-byte message header:
  ``+0x04`` size unit byte (0 for a 0x20 block, else rounded_size>>5),
  ``+0x05`` priority byte = 1 (bit7 sync marker cleared), ``+0x06`` u16
  refcount = 1, ``+0x08`` u32 source = 0xA5A5A5A5.  The allocator does **not**
  write the header next pointer ``+0x00`` (it keeps the stale free-list word);
  the send paths overwrite it, and this planner writes 0 explicitly so the
  produced message is the authentic "fresh message" form.
* fblock control object at ``libosal_base + 0xEF38`` (7 words): +0x00 lock,
  +0x04 free-list head, +0x08 wait list, +0x0C pool base, +0x10 pool size,
  +0x14 remaining bytes, +0x18 min remaining.  Every block is 0x20 bytes and
  the free list is LIFO via ``[block+0x00]``.  `alloc_fblock` (0x4BA4) pops the
  head, ``remaining -= 0x20``, updates ``min`` when smaller; `free_fblock`
  (0x4C60) pushes the block back and ``remaining += 0x20`` (no bounds check —
  this is the foreign-block hazard).
* global vpool object at ``libosal_base + 0xEFB8`` (7 words): +0x00 lock,
  +0x04 free-list head, +0x08 pool base, +0x0C pool size, +0x10 wait list,
  +0x14 free bytes, +0x18 min free.  `vpool_alloc` (0x4D80) first-fits the
  address-sorted free list (block header ``+0x04`` = block size, ``+0x00`` =
  next); an exact fit unlinks the block, a larger block is split at its end
  (``free_block.size -= request``; allocation = ``block + remaining_size``);
  ``free_bytes -= request`` and ``min`` updates when smaller.  `vpool_free`
  (0x4E6C) coalesces back.
* `osal_free_msg` (0x4088): decrements the header refcount, then decrements
  the queue counter and frees via `free_fblock` (unit byte 0) or `vpool_free`
  (unit byte > 0) — this is why the *header size unit* must be authentic.

This module is a pure planner: ``reader`` is a host-supplied
``memory_reader(addr, size) -> bytes`` callable; nothing executes, imports
Unicorn/firmware, or writes memory.  Every entry point fails closed with
``ValueError`` on unknown/unsupported allocator state (corrupted free lists,
foreign/out-of-pool blocks, waiting allocator queues, non-local queue ids,
per-queue vpool override, underflowed counters) instead of guessing.

Typical e0673 checkpoint values (read-only scratch reference): fblock control
``0x5003EF38`` lock 0, free head ``0x50431620``, pool ``0x50430000`` size
``0x38000``, remaining ``0x369E0``, min ``0x369C0``; global vpool
``0x5003EFB8`` free head ``0x50468000`` block size ``0x8000``, free bytes
``0x8000``, min ``0x7C40``; UsbControl queue object ``0x504305E0`` flags 0,
counter 0.  Addresses must be re-read per checkpoint; only the expressions are
durable.
"""
from __future__ import annotations

import struct

# ---------------------------------------------------------------------------
# Verified constants (OBSERVED from live libosal_uipc.so disassembly).
# ---------------------------------------------------------------------------
QUEUE_ID_USB_CONTROL_LOCAL = 0x00CA8192
QUEUE_ID_LOCAL_BIT = 0x8000
QUEUE_ID_TABLE_MASK = 0x7FFF          # osal_* lsl #0x11; lsr #0x11
QUEUE_ID_SMALL_MAX = 0x3F             # direct table for masked id <= 0x3F
QUEUE_TABLE_OFFSET = 0xE928           # two-level/trie table base
QUEUE_TRIE_FIRST_LEVEL = 0x42         # ((m>>9)&0x3F)+0x42

QUEUE_OBJECT_SIZE = 0x20
QUEUE_FLAG_OFFSET = 0x04
QUEUE_ALLOC_FLAGS_OFFSET = 0x05
QUEUE_ALLOC_COUNTER_OFFSET = 0x06
QUEUE_VPOOL_OVERRIDE_OFFSET = 0x1C
QUEUE_OBJECT_FIELDS = {
    0x00: 'lock_word',
    0x04: 'flags',
    0x05: 'alloc_flags',
    0x06: 'alloc_counter_u16',
    0x08: 'receiver_record_list_head',
    0x0C: 'message_head',
    0x10: 'message_tail',
    0x14: 'broadcast_tail',
    0x18: 'sync_callback_node',
    0x1C: 'vpool_override',
}
QUEUE_FLAG_BROADCAST = 0x01
QUEUE_FLAG_DISPATCH_IN_PROGRESS = 0x02
QUEUE_FLAG_ASYNC_NOTIFY = 0x08
QUEUE_FLAG_KNOWN_MASK = (QUEUE_FLAG_BROADCAST
                         | QUEUE_FLAG_DISPATCH_IN_PROGRESS
                         | QUEUE_FLAG_ASYNC_NOTIFY)
QUEUE_ALLOC_FLAG_WAITED = 0x01        # set by alloc_msg_by_queue when it slept
QUEUE_ALLOC_FLAG_FAILED = 0x02        # set on allocation failure (-0x3FF)
QUEUE_ALLOC_FLAGS_KNOWN_MASK = (QUEUE_ALLOC_FLAG_WAITED
                                | QUEUE_ALLOC_FLAG_FAILED)

FBLOCK_CONTROL_OFFSET = 0xEF38
FBLOCK_CONTROL_SIZE = 0x1C
FBLOCK_BLOCK_SIZE = 0x20
FBLOCK_FIELDS = {
    0x00: 'lock_word',
    0x04: 'free_list_head',
    0x08: 'wait_list_head',
    0x0C: 'pool_base',
    0x10: 'pool_size',
    0x14: 'remaining_bytes',
    0x18: 'min_remaining',
}

VPOOL_OFFSET = 0xEFB8
VPOOL_CONTROL_SIZE = 0x1C
VPOOL_ALIGN = 8
VPOOL_FIELDS = {
    0x00: 'lock_word',
    0x04: 'free_list_head',
    0x08: 'pool_base',
    0x0C: 'pool_size',
    0x10: 'wait_list_head',
    0x14: 'free_bytes',
    0x18: 'min_free',
}
VPOOL_BLOCK_FIELDS = {0x00: 'next', 0x04: 'size'}

MESSAGE_HEADER_SIZE = 0x0C
MESSAGE_PAYLOAD_BIAS = 0x0C            # payload = head + 0xC
MESSAGE_NEXT_OFFSET = 0x00
MESSAGE_SIZE_UNIT_OFFSET = 0x04
MESSAGE_PRIORITY_OFFSET = 0x05
MESSAGE_REFCOUNT_OFFSET = 0x06
MESSAGE_SOURCE_OFFSET = 0x08
MESSAGE_PRIORITY = 0x01                # bit7 sync marker cleared
MESSAGE_REFCOUNT_INITIAL = 1
OSAL_SOURCE_PLACEHOLDER = 0xA5A5A5A5
SMALL_MESSAGE_MAX = 0x14               # fblock 0x20 block => 20-byte payload
MAX_VALLOC_SIZE = 0x1000               # osal_valloc_msg_wait rejects > 0x1000
MAX_PLAN_WRITES = 8

PROVENANCE = {
    'source': 'libosal_uipc.so (live capture sha256 '
              'eecc322b81ebf63b26829fb2e8beee43af56f571b0ffbfc16d234dee5063becf; '
              'a6400 extracted build sha256 '
              'b6ded35add9582413b401cf4db78ec2c9a201b632e78c2731d6bbb379249b3eb; '
              'allocator function bodies are byte-identical in both builds)',
    'functions': {
        'osal_valloc_msg_wait': {'thumb_va': 0x3FEC, 'size': 156,
                                 'role': 'local alloc entry: id mask, size '
                                         '<= 0x1000 check, core 0x361C call'},
        'alloc_msg_by_queue': {'thumb_va': 0x361C, 'size': 420,
                               'role': 'lookup/create queue object, fblock vs '
                                       'vpool choice, header + counter'},
        'osal_free_msg': {'thumb_va': 0x4088, 'size': 172,
                          'role': 'refcount decrement then guest free '
                                  '(fblock if size unit 0, else vpool)'},
        'alloc_fblock': {'thumb_va': 0x4BA4, 'size': 188,
                         'role': 'LIFO 0x20-byte free-list pop, remaining/min'},
        'free_fblock': {'thumb_va': 0x4C60, 'size': 68,
                        'role': 'push block, remaining += 0x20 (no bounds '
                                'check: E0335 hazard)'},
        'fblock_init': {'thumb_va': 0x4CA4, 'size': 112,
                        'role': 'control fields + initial 0x20 block chain'},
        'vpool_alloc': {'thumb_va': 0x4D80, 'size': 236,
                        'role': 'address-sorted first-fit, exact unlink or '
                                'end split, free_bytes/min'},
        'vpool_free': {'thumb_va': 0x4E6C, 'size': 146,
                       'role': 'coalescing insert, free_bytes += size'},
        'queue_lookup': {'thumb_va': 0x33C4,
                         'role': 'masked-id direct table (<=0x3F) or trie'},
        'queue_create': {'thumb_va': 0x341C,
                         'role': '0x20-byte queue object, flags by id range'},
    },
    'labels': {
        'FBLOCK_FIELDS': 'OBSERVED: fblock_init 0x4CA4 stores, alloc_fblock '
                         '0x4BA4 pops +0x04 and adjusts +0x14/+0x18',
        'VPOOL_FIELDS': 'OBSERVED: vpool_alloc 0x4D80 / vpool_free 0x4E6C '
                        'field reads/writes',
        'MESSAGE_HEADER': 'OBSERVED: alloc_msg_by_queue 0x36CA..0x36EA header '
                          'init; osal_free_msg 0x40BE..0x4120 uses +0x04/+0x06',
        'SMALL_MESSAGE_MAX': 'OBSERVED: alloc_msg_by_queue 0x36F2 cmp #0x14; '
                             'fblock blocks are 0x20 => 0x14-byte payload',
    },
}

_DEFAULT_ASSUMPTIONS = (
    'allocator queues are empty and locks are at rest when planning; the '
    'original osal_lock/osal_unlock and vpool/fblock lock words are transient '
    'and are not part of the write plan',
    'the allocation is non-blocking: a full free list/pool would make the '
    'original allocator return -0x3FF (and set obj+0x05 bit1); this planner '
    'refuses instead of modelling the wait',
    'the message next pointer (+0x00) is not written by the allocator; the '
    'plan writes 0 to produce the fresh-message form the send paths expect',
    'the queue object belongs to the local (bit-15) path and has no per-queue '
    'vpool override at +0x1C',
)

_DEFAULT_UNKNOWNS = (
    'fblock/vpool free-list block content beyond next/size is unused by the '
    'verified path and is not modelled',
    'which delivery lane a physical producer uses (sync callback vs async '
    'queue post) is unobserved; the payload ownership requirement is the same',
    'the RcvMsg source filter acceptance for header +0x08 is not decoded; the '
    'authentic allocator placeholder 0xA5A5A5A5 is used by default and may be '
    'overridden by the caller for a labelled experiment',
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


def _require_aligned(address, alignment, what):
    if not isinstance(address, int) or address <= 0:
        raise ValueError('%s must be a positive address, got %r' % (what, address))
    if address % alignment:
        raise ValueError('%s 0x%08x is not %d-byte aligned'
                         % (what, address, alignment))
    return address


def _require_int(value, what):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError('%s must be an integer, got %r' % (what, value))
    return value


# ---------------------------------------------------------------------------
# Queue lookup (0x33C4) and queue-object validation.
# ---------------------------------------------------------------------------
def lookup_local_queue(reader, libosal_base, queue_id):
    """Resolve a bit-15 local queue id to its user-space queue object.

    Mirrors libosal lookup 0x33C4: direct table for masked id <= 0x3F, else a
    two-level trie rooted at ``libosal_base + 0xE928``.  Returns
    ``{'queue_id','masked_id','object','steps'}`` or raises ValueError when the
    id is not a local id or the table path is absent.
    """
    _require_aligned(queue_id, 1, 'queue id')
    if not queue_id & QUEUE_ID_LOCAL_BIT:
        raise ValueError('local_queue_id_required: 0x%08x has bit 15 clear '
                         '(kernel/UIPC path, not modelled)' % (queue_id,))
    masked = queue_id & QUEUE_ID_TABLE_MASK
    table = libosal_base + QUEUE_TABLE_OFFSET
    steps = []
    if masked <= QUEUE_ID_SMALL_MAX:
        address = table + 4 + 4 * masked
        value = _read_u32(reader, address, 'queue direct-table entry')
        steps.append({'kind': 'direct', 'index': masked, 'address': address,
                      'value': value})
        if value == 0:
            raise ValueError('queue_object_absent: direct-table entry 0x%08x '
                             'for masked id 0x%x is null' % (address, masked))
        return {'queue_id': queue_id, 'masked_id': masked, 'object': value,
                'steps': steps}
    i0 = ((masked >> 9) & 0x3F) + QUEUE_TRIE_FIRST_LEVEL
    address = table + 4 * i0
    value = _read_u32(reader, address, 'queue trie level 0')
    steps.append({'kind': 'trie0', 'index': i0, 'address': address,
                  'value': value})
    if value == 0:
        raise ValueError('queue_object_absent: trie level 0 null for masked '
                         'id 0x%x' % (masked,))
    for level, shift in (('trie1', 6), ('trie2', 3)):
        index = (masked >> shift) & 0x7
        address = value + 4 * index
        value = _read_u32(reader, address, 'queue %s' % (level,))
        steps.append({'kind': level, 'index': index, 'address': address,
                      'value': value})
        if value == 0:
            raise ValueError('queue_object_absent: %s null for masked id 0x%x'
                             % (level, masked))
    index = masked & 0x7
    address = value + 4 * index
    value = _read_u32(reader, address, 'queue trie leaf')
    steps.append({'kind': 'leaf', 'index': index, 'address': address,
                  'value': value})
    if value == 0:
        raise ValueError('queue_object_absent: leaf null for masked id 0x%x'
                         % (masked,))
    return {'queue_id': queue_id, 'masked_id': masked, 'object': value,
            'steps': steps}


def _inspect_queue_object(reader, lookup):
    address = lookup['object']
    _require_aligned(address, 4, 'queue object address')
    raw = _read_bytes(reader, address, QUEUE_OBJECT_SIZE, 'queue object')
    lock = struct.unpack_from('<I', raw, 0x00)[0]
    flags = raw[0x04]
    alloc_flags = raw[0x05]
    counter = struct.unpack_from('<H', raw, 0x06)[0]
    vpool_override = struct.unpack_from('<I', raw, 0x1C)[0]
    if lock != 0:
        raise ValueError('queue_object_locked: lock 0x%08x at 0x%08x'
                         % (lock, address))
    unknown = flags & ~QUEUE_FLAG_KNOWN_MASK
    if unknown:
        raise ValueError('queue_object_unknown_flags: 0x%02x at 0x%08x'
                         % (flags, address + 0x04))
    unknown = alloc_flags & ~QUEUE_ALLOC_FLAGS_KNOWN_MASK
    if unknown:
        raise ValueError('queue_alloc_flags_unknown: 0x%02x at 0x%08x'
                         % (alloc_flags, address + 0x05))
    if alloc_flags:
        raise ValueError('queue_alloc_flags_set: 0x%02x at 0x%08x (allocator '
                         'waited/failed markers are not a rest state)'
                         % (alloc_flags, address + 0x05))
    signed_counter = counter if counter < 0x8000 else counter - 0x10000
    if signed_counter < 0:
        raise ValueError('queue_alloc_counter_undercounted: u16 0x%04x at '
                         '0x%08x (foreign frees underflow this counter; the '
                         'E0335 audit saw 0xFFFF)' % (counter, address + 0x06))
    if counter == 0x7FFF:
        raise ValueError('queue_alloc_counter_overflow: u16 0x7fff at 0x%08x '
                         'would go negative' % (address + 0x06,))
    if not flags & QUEUE_FLAG_ASYNC_NOTIFY and vpool_override:
        raise ValueError('per_queue_vpool_unmodelled: obj+0x1C=0x%08x at '
                         '0x%08x (alloc_msg_by_queue 0x367C uses that vpool '
                         'instead of the global one)'
                         % (vpool_override, address + 0x1C))
    return {
        'queue_id': lookup['queue_id'],
        'masked_id': lookup['masked_id'],
        'object': address,
        'lookup_steps': lookup['steps'],
        'lock': lock,
        'flags': flags,
        'alloc_flags': alloc_flags,
        'alloc_counter_u16': counter,
        'vpool_override': vpool_override,
        'receiver_record_list_head': struct.unpack_from('<I', raw, 0x08)[0],
        'message_head': struct.unpack_from('<I', raw, 0x0C)[0],
        'message_tail': struct.unpack_from('<I', raw, 0x10)[0],
        'sync_callback_node': struct.unpack_from('<I', raw, 0x18)[0],
    }


# ---------------------------------------------------------------------------
# Allocator inspection.
# ---------------------------------------------------------------------------
def _inspect_fblock(reader, libosal_base):
    control = libosal_base + FBLOCK_CONTROL_OFFSET
    raw = _read_bytes(reader, control, FBLOCK_CONTROL_SIZE, 'fblock control')
    lock, free_head, wait_list, pool_base, pool_size, remaining, min_remaining = \
        struct.unpack('<7I', raw)
    if lock:
        raise ValueError('fblock_locked: lock 0x%08x at 0x%08x'
                         % (lock, control))
    if wait_list:
        raise ValueError('fblock_waiters_present: wait list 0x%08x at 0x%08x '
                         '(the original allocator would block)'
                         % (wait_list, control + 0x08))
    pool_base = _require_aligned(pool_base, FBLOCK_BLOCK_SIZE, 'fblock pool base')
    if not pool_size or pool_size % FBLOCK_BLOCK_SIZE:
        raise ValueError('fblock_pool_size_invalid: 0x%08x at 0x%08x'
                         % (pool_size, control + 0x10))
    if remaining > pool_size or remaining % FBLOCK_BLOCK_SIZE:
        raise ValueError('fblock_remaining_invalid: 0x%08x (pool 0x%08x) at '
                         '0x%08x' % (remaining, pool_size, control + 0x14))
    if min_remaining > remaining or min_remaining % FBLOCK_BLOCK_SIZE:
        raise ValueError('fblock_min_remaining_invalid: 0x%08x > remaining '
                         '0x%08x at 0x%08x'
                         % (min_remaining, remaining, control + 0x18))
    pool_end = pool_base + pool_size
    blocks = []
    seen = set()
    address = free_head
    max_blocks = pool_size // FBLOCK_BLOCK_SIZE
    while address:
        _require_aligned(address, FBLOCK_BLOCK_SIZE, 'fblock free block')
        if not pool_base <= address < pool_end:
            raise ValueError(
                'fblock_foreign_free_head: block 0x%08x outside guest pool '
                '0x%08x..0x%08x at control 0x%08x (E0335 audit hazard: a '
                'foreign UIPC-pool block was pushed onto this list)'
                % (address, pool_base, pool_end, control))
        if address in seen:
            raise ValueError('fblock_free_list_cycle at 0x%08x' % (address,))
        if len(blocks) >= max_blocks:
            raise ValueError('fblock_free_list_too_long (pool holds at most %d '
                             'blocks)' % (max_blocks,))
        seen.add(address)
        next_block = _read_u32(reader, address, 'fblock free block next')
        blocks.append({'address': address, 'next': next_block})
        address = next_block
    if len(blocks) * FBLOCK_BLOCK_SIZE != remaining:
        raise ValueError('fblock_remaining_mismatch: %d free blocks = 0x%x '
                         'bytes, remaining field 0x%x (control 0x%08x)'
                         % (len(blocks), len(blocks) * FBLOCK_BLOCK_SIZE,
                            remaining, control))
    return {
        'control_address': control,
        'lock': lock,
        'free_list_head': free_head,
        'wait_list_head': wait_list,
        'pool_base': pool_base,
        'pool_size': pool_size,
        'block_size': FBLOCK_BLOCK_SIZE,
        'remaining_bytes': remaining,
        'min_remaining': min_remaining,
        'free_block_count': len(blocks),
        'free_blocks': blocks,
    }


def _inspect_vpool(reader, libosal_base):
    control = libosal_base + VPOOL_OFFSET
    raw = _read_bytes(reader, control, VPOOL_CONTROL_SIZE, 'global vpool control')
    lock, free_head, pool_base, pool_size, wait_list, free_bytes, min_free = \
        struct.unpack('<7I', raw)
    if lock:
        raise ValueError('vpool_locked: lock 0x%08x at 0x%08x'
                         % (lock, control))
    if wait_list:
        raise ValueError('vpool_waiters_present: wait list 0x%08x at 0x%08x '
                         '(the original allocator would block)'
                         % (wait_list, control + 0x10))
    pool_base = _require_aligned(pool_base, VPOOL_ALIGN, 'vpool pool base')
    if not pool_size or pool_size % VPOOL_ALIGN:
        raise ValueError('vpool_pool_size_invalid: 0x%08x at 0x%08x'
                         % (pool_size, control + 0x0C))
    if free_bytes > pool_size or free_bytes % VPOOL_ALIGN:
        raise ValueError('vpool_free_bytes_invalid: 0x%08x (pool 0x%08x) at '
                         '0x%08x' % (free_bytes, pool_size, control + 0x14))
    if min_free > free_bytes or min_free % VPOOL_ALIGN:
        raise ValueError('vpool_min_free_invalid: 0x%08x > free 0x%08x at 0x%08x'
                         % (min_free, free_bytes, control + 0x18))
    pool_end = pool_base + pool_size
    blocks = []
    seen = set()
    address = free_head
    max_blocks = pool_size // VPOOL_ALIGN
    previous_end = pool_base
    while address:
        _require_aligned(address, VPOOL_ALIGN, 'vpool free block')
        if not pool_base <= address < pool_end:
            raise ValueError('vpool_free_block_outside_pool: 0x%08x not in '
                             '0x%08x..0x%08x' % (address, pool_base, pool_end))
        if address in seen:
            raise ValueError('vpool_free_list_cycle at 0x%08x' % (address,))
        if len(blocks) >= max_blocks:
            raise ValueError('vpool_free_list_too_long')
        if address < previous_end:
            raise ValueError('vpool_free_list_unsorted_or_overlapping at 0x%08x'
                             % (address,))
        seen.add(address)
        block_raw = _read_bytes(reader, address, 8, 'vpool free block header')
        next_block, block_size = struct.unpack('<II', block_raw)
        if block_size < VPOOL_ALIGN or block_size % VPOOL_ALIGN:
            raise ValueError('vpool_block_size_invalid: 0x%08x at 0x%08x'
                             % (block_size, address + 0x04))
        if address + block_size > pool_end:
            raise ValueError('vpool_block_beyond_pool: 0x%08x+0x%x > 0x%08x'
                             % (address, block_size, pool_end))
        blocks.append({'address': address, 'next': next_block,
                       'size': block_size})
        previous_end = address + block_size
        address = next_block
    total = sum(block['size'] for block in blocks)
    if total != free_bytes:
        raise ValueError('vpool_free_bytes_mismatch: free list sums to 0x%x, '
                         'free_bytes field 0x%x (control 0x%08x)'
                         % (total, free_bytes, control))
    return {
        'control_address': control,
        'lock': lock,
        'free_list_head': free_head,
        'pool_base': pool_base,
        'pool_size': pool_size,
        'wait_list_head': wait_list,
        'free_bytes': free_bytes,
        'min_free': min_free,
        'free_block_count': len(blocks),
        'free_blocks': blocks,
    }


def inspect_guest_allocator(reader, libosal_base,
                            queue_id=QUEUE_ID_USB_CONTROL_LOCAL):
    """Read and validate the guest OSAL message allocator state.

    Returns the fblock control, global vpool control, and the resolved local
    queue object (counter fields).  Fails closed on locked/waiting allocators,
    corrupted/foreign/cyclic free lists, counter underflow, non-address-sorted
    vpool lists, or a missing/non-local queue object.
    """
    _require_aligned(libosal_base, 4, 'libosal base')
    fblock = _inspect_fblock(reader, libosal_base)
    vpool = _inspect_vpool(reader, libosal_base)
    if fblock['pool_base'] + fblock['pool_size'] > vpool['pool_base']:
        raise ValueError('allocator_pools_overlap: fblock pool ends 0x%08x, '
                         'vpool starts 0x%08x'
                         % (fblock['pool_base'] + fblock['pool_size'],
                            vpool['pool_base']))
    lookup = lookup_local_queue(reader, libosal_base, queue_id)
    queue = _inspect_queue_object(reader, lookup)
    return {
        'kind': 'guest-osal-allocator',
        'libosal_base': libosal_base,
        'fblock': fblock,
        'vpool': vpool,
        'queue': queue,
        'assumptions': list(_DEFAULT_ASSUMPTIONS),
        'unknowns': list(_DEFAULT_UNKNOWNS),
        'provenance': dict(PROVENANCE),
    }


# ---------------------------------------------------------------------------
# Planner.
# ---------------------------------------------------------------------------
def _rounded_size(size):
    """alloc_msg_by_queue 0x3666: r8 = (size + 0x2B) & ~0x1F."""
    return (size + 0x2B) & ~0x1F


def _header_write_labels(units, source):
    return [
        {'label': 'message_next', 'fields': {'next': 0},
         'evidence': 'allocator leaves +0x00 stale; write 0 for the fresh '
                     'message form the send paths overwrite/link'},
        {'label': 'message_header',
         'fields': {'size_units': units, 'priority': MESSAGE_PRIORITY,
                    'refcount': MESSAGE_REFCOUNT_INITIAL, 'source': source},
         'evidence': 'alloc_msg_by_queue 0x36CA..0x36EA: strb unit,[head+4]; '
                     'byte[head+5]=(old&0xBF)|1 then bit7 cleared; strh 1 '
                     '[head+6]; str 0xA5A5A5A5 [head+8]'},
    ]


def _check_write_address(address, data):
    """Planned writes are guest memory writes: 4-byte aligned unless u16."""
    if not isinstance(address, int) or address <= 0:
        raise ValueError('planned write address must be positive, got %r'
                         % (address,))
    alignment = 4 if len(data) >= 4 else 2
    if address % alignment:
        raise ValueError('planned write address 0x%08x is not %d-byte aligned '
                         'for a %d-byte write' % (address, alignment, len(data)))


def plan_message_alloc(reader, libosal_base, size,
                       queue_id=QUEUE_ID_USB_CONTROL_LOCAL,
                       source=OSAL_SOURCE_PLACEHOLDER):
    """Plan one guest-allocator message allocation (fblock or global vpool).

    ``size`` is the requested message payload size (0..0x1000, the
    ``osal_valloc_msg_wait`` limit).  Returns an ordered, bounded write plan
    plus the resulting head/payload addresses and authentic message header; it
    never executes or writes.  The queue counter (`obj+0x06`) increment is
    planned for ``queue_id`` (default: UsbControl's process-local queue
    ``0x00CA8192``).

    Allocation choice (alloc_msg_by_queue 0x361C): ``size <= 0x14`` uses a
    0x20-byte fblock (payload capacity 0x14, size unit 0); larger sizes use
    the global vpool with ``rounded = (size+0x2B)&~0x1F`` and size unit
    ``rounded>>5`` (payload capacity ``rounded-0x0C``).
    """
    size = _require_int(size, 'message size')
    if size < 0 or size > MAX_VALLOC_SIZE:
        raise ValueError('message_size_out_of_range: %d (osal_valloc_msg_wait '
                         'accepts 0..0x%x)' % (size, MAX_VALLOC_SIZE))
    source = _require_int(source, 'message source id') & 0xFFFFFFFF
    state = inspect_guest_allocator(reader, libosal_base, queue_id=queue_id)
    queue = state['queue']
    fblock = state['fblock']
    vpool = state['vpool']
    flags = queue['flags']
    if (not flags & QUEUE_FLAG_ASYNC_NOTIFY) and queue['vpool_override']:
        raise ValueError('per_queue_vpool_unmodelled: queue 0x%08x overrides '
                         'the vpool at +0x1C=0x%08x'
                         % (queue['object'], queue['vpool_override']))
    use_fblock = size <= SMALL_MESSAGE_MAX
    writes = []
    write_provenance = []

    def add_write(label, address, data, evidence, fields=None):
        _check_write_address(address, data)
        writes.append((int(address), bytes(data)))
        entry = {'label': label, 'address': int(address),
                 'size': len(data), 'evidence': evidence}
        if fields:
            entry['fields'] = dict(fields)
        write_provenance.append(entry)

    counter = queue['alloc_counter_u16']
    counter_write = (queue['object'] + 0x06,
                     struct.pack('<H', (counter + 1) & 0xFFFF))
    counter_evidence = ('alloc_msg_by_queue 0x36A0..0x36AE: atomic u16 '
                        'obj+0x06 += 1 (osal_free_msg 0x40D8 decrements it)')
    if use_fblock:
        head = fblock['free_list_head']
        if head == 0:
            raise ValueError('fblock_free_list_empty: the original allocator '
                             'would return -0x3FF for size %d' % (size,))
        next_block = _read_u32(reader, head, 'fblock free block next')
        remaining = fblock['remaining_bytes'] - FBLOCK_BLOCK_SIZE
        add_write('fblock_pop', fblock['control_address'] + 0x04,
                  struct.pack('<I', next_block),
                  'alloc_fblock 0x4BBE-0x4BC6: free head = [block+0]',
                  {'old_head': head, 'new_head': next_block})
        add_write('fblock_remaining', fblock['control_address'] + 0x14,
                  struct.pack('<I', remaining),
                  'alloc_fblock 0x4BC0-0x4BCA: remaining -= 0x20',
                  {'remaining_before': fblock['remaining_bytes'],
                   'remaining_after': remaining})
        if remaining < fblock['min_remaining']:
            add_write('fblock_min_remaining', fblock['control_address'] + 0x18,
                      struct.pack('<I', remaining),
                      'alloc_fblock 0x4BC8-0x4BCE: min = min(min, remaining)',
                      {'min_before': fblock['min_remaining'],
                       'min_after': remaining})
        units = 0
        rounded = FBLOCK_BLOCK_SIZE
        capacity = FBLOCK_BLOCK_SIZE - MESSAGE_HEADER_SIZE
        allocator = 'fblock'
        allocator_detail = {
            'block_size': FBLOCK_BLOCK_SIZE,
            'payload_capacity': capacity,
            'reason': 'size <= 0x14 (alloc_msg_by_queue 0x36F2)',
        }
        pool_before = {'free_list_head': fblock['free_list_head'],
                       'remaining_bytes': fblock['remaining_bytes'],
                       'min_remaining': fblock['min_remaining']}
        pool_after = {'free_list_head': next_block,
                      'remaining_bytes': remaining,
                      'min_remaining': min(fblock['min_remaining'], remaining)}
    else:
        rounded = _rounded_size(size)
        units = rounded >> 5
        capacity = rounded - MESSAGE_HEADER_SIZE
        if rounded > vpool['pool_size']:
            raise ValueError('vpool_request_exceeds_pool: rounded 0x%x > pool '
                             '0x%x (vpool_alloc 0x4D98 returns 0/-0x3FF)'
                             % (rounded, vpool['pool_size']))
        predecessor = None
        current = vpool['free_list_head']
        chosen = None
        seen = set()
        while current:
            if current in seen:
                raise ValueError('vpool_free_list_cycle at 0x%08x' % (current,))
            seen.add(current)
            block_size = _read_u32(reader, current + 0x04,
                                   'vpool free block size')
            if block_size >= rounded:
                chosen = {'address': current, 'size': block_size,
                          'predecessor': predecessor}
                break
            predecessor = current
            current = _read_u32(reader, current, 'vpool free block next')
        if chosen is None:
            raise ValueError('vpool_no_block: no free block >= 0x%x (the '
                             'original allocator would return -0x3FF)' % (rounded,))
        block = chosen['address']
        next_block = _read_u32(reader, block, 'vpool free block next')
        free_bytes = vpool['free_bytes'] - rounded
        if chosen['size'] == rounded:
            link_from = (vpool['control_address'] + 0x04
                         if chosen['predecessor'] is None
                         else chosen['predecessor'])
            add_write('vpool_unlink', link_from, struct.pack('<I', next_block),
                      'vpool_alloc 0x4E52-0x4E56: exact fit, unlink the block',
                      {'unlinked_block': block, 'next': next_block})
            head = block
            allocator_detail = {
                'mode': 'exact-fit',
                'free_block': {'address': block, 'size': chosen['size']},
                'payload_capacity': capacity,
                'reason': 'size > 0x14 (alloc_msg_by_queue 0x370C)',
            }
        else:
            leftover = chosen['size'] - rounded
            add_write('vpool_split', block + 0x04, struct.pack('<I', leftover),
                      'vpool_alloc 0x4E44-0x4E46: split block at its end '
                      '(remaining size stays at the low address)',
                      {'free_block': block, 'size_before': chosen['size'],
                       'size_after': leftover})
            head = block + leftover
            allocator_detail = {
                'mode': 'split',
                'free_block': {'address': block, 'size_after': leftover},
                'payload_capacity': capacity,
                'reason': 'size > 0x14 (alloc_msg_by_queue 0x370C)',
            }
        add_write('vpool_free_bytes', vpool['control_address'] + 0x14,
                  struct.pack('<I', free_bytes),
                  'vpool_alloc 0x4E5C-0x4E62: free_bytes -= request',
                  {'free_bytes_before': vpool['free_bytes'],
                   'free_bytes_after': free_bytes})
        if free_bytes < vpool['min_free']:
            add_write('vpool_min_free', vpool['control_address'] + 0x18,
                      struct.pack('<I', free_bytes),
                      'vpool_alloc 0x4E5E-0x4E68: min = min(min, free_bytes)',
                      {'min_before': vpool['min_free'],
                       'min_after': free_bytes})
        allocator = 'vpool'
        pool_before = {'free_list_head': vpool['free_list_head'],
                       'free_bytes': vpool['free_bytes'],
                       'min_free': vpool['min_free']}
        pool_after = {'free_list_head': (next_block
                                         if chosen['size'] == rounded
                                         else vpool['free_list_head']),
                      'free_bytes': free_bytes,
                      'min_free': min(vpool['min_free'], free_bytes)}

    add_write('queue_alloc_counter', counter_write[0], counter_write[1],
              counter_evidence,
              {'counter_before': counter, 'counter_after': counter + 1})
    add_write('message_next', head + MESSAGE_NEXT_OFFSET,
              struct.pack('<I', 0),
              'fresh-message next pointer (the allocator leaves +0x00 stale; '
              'the queue send path overwrites it)',
              {'next': 0})
    add_write('message_header',
              head + MESSAGE_SIZE_UNIT_OFFSET,
              bytes([units & 0xFF, MESSAGE_PRIORITY,
                     MESSAGE_REFCOUNT_INITIAL & 0xFF,
                     (MESSAGE_REFCOUNT_INITIAL >> 8) & 0xFF,
                     source & 0xFF, (source >> 8) & 0xFF,
                     (source >> 16) & 0xFF, (source >> 24) & 0xFF]),
              'alloc_msg_by_queue 0x36CA..0x36EA: size unit byte, priority '
              'byte 1 (bit7 cleared), u16 refcount 1, u32 source',
              {'size_units': units, 'priority': MESSAGE_PRIORITY,
               'refcount': MESSAGE_REFCOUNT_INITIAL, 'source': source})

    if len(writes) > MAX_PLAN_WRITES:
        raise ValueError('alloc_plan_write_limit_exceeded: %d > %d'
                         % (len(writes), MAX_PLAN_WRITES))
    addresses = [address for address, _data in writes]
    if len(set(addresses)) != len(addresses):
        raise ValueError('alloc_plan_write_overlap')
    payload = head + MESSAGE_PAYLOAD_BIAS
    header = {
        'head': head,
        'next': 0,
        'size_units': units,
        'priority': MESSAGE_PRIORITY,
        'refcount': MESSAGE_REFCOUNT_INITIAL,
        'source': source,
        'payload': payload,
        'payload_capacity': capacity,
        'requested_size': size,
        'rounded_size': rounded,
    }
    return {
        'kind': 'guest-osal-message-alloc',
        'scope': 'pure planner; ordered writes must be applied by the caller',
        'libosal_base': libosal_base,
        'allocator': allocator,
        'allocator_detail': allocator_detail,
        'queue': {
            'queue_id': queue['queue_id'],
            'masked_id': queue['masked_id'],
            'object': queue['object'],
            'flags': queue['flags'],
            'alloc_counter_before': counter,
            'alloc_counter_after': counter + 1,
        },
        'message': header,
        'writes': writes,
        'write_provenance': write_provenance,
        'pool_before': pool_before,
        'pool_after': pool_after,
        'bounded': {'write_count': len(writes),
                    'max_writes': MAX_PLAN_WRITES,
                    'reads_only_otherwise': True},
        'assumptions': list(_DEFAULT_ASSUMPTIONS) + [
            'the authentic allocator header places the source placeholder '
            '0xA5A5A5A5 at head+0x08; a caller may override it for a labelled '
            'RcvMsg source-filter experiment',
        ],
        'unknowns': list(_DEFAULT_UNKNOWNS),
        'provenance': dict(PROVENANCE),
    }


# ---------------------------------------------------------------------------
# Rendering.
# ---------------------------------------------------------------------------
def render_alloc_plan(plan):
    """Render an allocation plan as deterministic human-readable report lines."""
    message = plan['message']
    queue = plan['queue']
    lines = [
        'guest OSAL message allocation plan (observe-only model, not executed)',
        '  allocator: %s (%s)' % (
            plan['allocator'],
            plan['allocator_detail'].get('reason',
                                         plan['allocator_detail'].get('mode'))),
        '  queue object 0x%08x (id 0x%08x, masked 0x%x): alloc counter '
        '0x%04x -> 0x%04x' % (
            queue['object'], queue['queue_id'], queue['masked_id'],
            queue['alloc_counter_before'], queue['alloc_counter_after']),
        '  message head 0x%08x payload 0x%08x: size_units=%d priority=%d '
        'refcount=%d source=0x%08x capacity=%d requested=%d' % (
            message['head'], message['payload'], message['size_units'],
            message['priority'], message['refcount'], message['source'],
            message['payload_capacity'], message['requested_size']),
        '  ordered writes (%d, bounded by %d):' % (
            len(plan['writes']), plan['bounded']['max_writes']),
    ]
    for index, (address, data) in enumerate(plan['writes']):
        provenance = plan['write_provenance'][index]
        lines.append('    [%d] 0x%08x <- %s  # %s (%s)' % (
            index, address, data.hex(), provenance['label'],
            provenance['evidence']))
    lines.append('  pool before: %s' % (
        ', '.join('%s=0x%08x' % (key, value)
                  for key, value in plan['pool_before'].items()),))
    lines.append('  pool after:  %s' % (
        ', '.join('%s=0x%08x' % (key, value)
                  for key, value in plan['pool_after'].items()),))
    for assumption in plan['assumptions']:
        lines.append('  assumption: %s' % (assumption,))
    return lines
