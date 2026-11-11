"""Tests for the pure guest OSAL allocator planner (constructed fixtures).

No firmware, emulator or Unicorn is used: a fake guest-memory buffer supplies
the libosal queue table, fblock control, global vpool and queue object.  The
planner must be deterministic, bounded, read-only, and fail closed on foreign /
corrupted allocator state (the E0335 e0686 hazard).
"""
import struct
import unittest

from src.a6400.execution import guest_osal_alloc as planner
from src.a6400.execution.guest_osal_alloc import (
    FBLOCK_BLOCK_SIZE,
    FBLOCK_CONTROL_OFFSET,
    MAX_PLAN_WRITES,
    MESSAGE_PRIORITY,
    MESSAGE_REFCOUNT_INITIAL,
    OSAL_SOURCE_PLACEHOLDER,
    QUEUE_ALLOC_COUNTER_OFFSET,
    QUEUE_OBJECT_SIZE,
    QUEUE_TABLE_OFFSET,
    VPOOL_OFFSET,
    inspect_guest_allocator,
    lookup_local_queue,
    plan_message_alloc,
    render_alloc_plan,
)

MEMORY_BASE = 0x50000000
LIBOSAL = 0x50030000
QUEUE_TABLE = LIBOSAL + QUEUE_TABLE_OFFSET
FB_CTL = LIBOSAL + FBLOCK_CONTROL_OFFSET
VP_CTL = LIBOSAL + VPOOL_OFFSET
FB_POOL = 0x50430000
FB_POOL_SIZE = 0x100
VP_POOL = 0x50468000
VP_POOL_SIZE = 0x400
QUEUE_OBJ = 0x504305E0
TRIE0 = 0x50400000
TRIE1 = 0x50400100
TRIE2 = 0x50400200
QUEUE_ID = 0x00CA8192


class FakeGuestMemory:
    """Bounded byte-array guest memory; reads outside the mapping fail."""

    def __init__(self):
        self.base = MEMORY_BASE
        self.memory = bytearray(0x480000)
        self.reads = []

    def write(self, address, data):
        offset = address - self.base
        self.memory[offset:offset + len(data)] = data

    def write_u8(self, address, value):
        self.write(address, struct.pack('<B', value))

    def write_u16(self, address, value):
        self.write(address, struct.pack('<H', value))

    def write_u32(self, address, value):
        self.write(address, struct.pack('<I', value))

    def apply(self, writes):
        for address, data in writes:
            self.write(address, data)

    def __call__(self, address, size):
        self.reads.append((address, size))
        offset = int(address) - self.base
        if offset < 0 or offset + size > len(self.memory):
            raise ValueError('unmapped guest address 0x%08x' % (address,))
        return bytes(self.memory[offset:offset + size])


def write_fblock(memory, blocks, remaining=None, min_remaining=None,
                 lock=0, waiters=0):
    """Write the fblock control + a LIFO free list of 0x20-byte blocks."""
    if remaining is None:
        remaining = len(blocks) * FBLOCK_BLOCK_SIZE
    if min_remaining is None:
        min_remaining = remaining
    memory.write_u32(FB_CTL + 0x00, lock)
    memory.write_u32(FB_CTL + 0x04, blocks[0] if blocks else 0)
    memory.write_u32(FB_CTL + 0x08, waiters)
    memory.write_u32(FB_CTL + 0x0C, FB_POOL)
    memory.write_u32(FB_CTL + 0x10, FB_POOL_SIZE)
    memory.write_u32(FB_CTL + 0x14, remaining)
    memory.write_u32(FB_CTL + 0x18, min_remaining)
    for index, block in enumerate(blocks):
        next_block = blocks[index + 1] if index + 1 < len(blocks) else 0
        memory.write_u32(block, next_block)
        memory.write_u32(block + 0x04, 0x11111111)  # stale free-list content


def write_vpool(memory, blocks, pool_size=None, free_bytes=None, min_free=None,
                lock=0, waiters=0, pool_base=VP_POOL):
    """Write the global vpool control + an address-sorted free list."""
    if pool_size is None:
        pool_size = sum(size for _address, size in blocks)
    if free_bytes is None:
        free_bytes = sum(size for _address, size in blocks)
    if min_free is None:
        min_free = free_bytes
    memory.write_u32(VP_CTL + 0x00, lock)
    memory.write_u32(VP_CTL + 0x04, blocks[0][0] if blocks else 0)
    memory.write_u32(VP_CTL + 0x08, pool_base)
    memory.write_u32(VP_CTL + 0x0C, pool_size)
    memory.write_u32(VP_CTL + 0x10, waiters)
    memory.write_u32(VP_CTL + 0x14, free_bytes)
    memory.write_u32(VP_CTL + 0x18, min_free)
    for index, (address, size) in enumerate(blocks):
        next_block = blocks[index + 1][0] if index + 1 < len(blocks) else 0
        memory.write_u32(address, next_block)
        memory.write_u32(address + 0x04, size)


def write_queue_object(memory, address=QUEUE_OBJ, flags=0, alloc_flags=0,
                       counter=0, vpool_override=0):
    raw = bytearray(QUEUE_OBJECT_SIZE)
    raw[0x04] = flags
    raw[0x05] = alloc_flags
    struct.pack_into('<H', raw, 0x06, counter)
    struct.pack_into('<I', raw, 0x1C, vpool_override)
    memory.write(address, bytes(raw))


def write_queue_trie(memory, queue_id=QUEUE_ID, obj=QUEUE_OBJ):
    """Populate the libosal queue table exactly as lookup 0x33C4 walks it."""
    masked = queue_id & 0x7FFF
    if masked <= 0x3F:
        memory.write_u32(QUEUE_TABLE + 4 + 4 * masked, obj)
        return []
    i0 = ((masked >> 9) & 0x3F) + 0x42
    memory.write_u32(QUEUE_TABLE + 4 * i0, TRIE0)
    memory.write_u32(TRIE0 + 4 * ((masked >> 6) & 0x7), TRIE1)
    memory.write_u32(TRIE1 + 4 * ((masked >> 3) & 0x7), TRIE2)
    memory.write_u32(TRIE2 + 4 * (masked & 0x7), obj)
    return [TRIE0, TRIE1, TRIE2]


def default_fixture(memory, counter=0):
    write_fblock(memory, [FB_POOL, FB_POOL + 0x20,
                          FB_POOL + 0x40, FB_POOL + 0x60])
    write_vpool(memory, [(VP_POOL, VP_POOL_SIZE)])
    write_queue_trie(memory)
    write_queue_object(memory, counter=counter)
    return memory


class GuestAllocatorInspectionTests(unittest.TestCase):
    def setUp(self):
        self.memory = default_fixture(FakeGuestMemory())

    def test_valid_fixture_reports_fblock_vpool_and_queue(self):
        state = inspect_guest_allocator(self.memory, LIBOSAL)
        fblock = state['fblock']
        self.assertEqual(fblock['control_address'], FB_CTL)
        self.assertEqual(fblock['free_list_head'], FB_POOL)
        self.assertEqual(fblock['pool_base'], FB_POOL)
        self.assertEqual(fblock['pool_size'], FB_POOL_SIZE)
        self.assertEqual(fblock['remaining_bytes'], 0x80)
        self.assertEqual(fblock['min_remaining'], 0x80)
        self.assertEqual(fblock['free_block_count'], 4)
        self.assertEqual(fblock['block_size'], FBLOCK_BLOCK_SIZE)
        vpool = state['vpool']
        self.assertEqual(vpool['control_address'], VP_CTL)
        self.assertEqual(vpool['free_list_head'], VP_POOL)
        self.assertEqual(vpool['pool_base'], VP_POOL)
        self.assertEqual(vpool['free_bytes'], VP_POOL_SIZE)
        self.assertEqual(vpool['free_block_count'], 1)
        queue = state['queue']
        self.assertEqual(queue['object'], QUEUE_OBJ)
        self.assertEqual(queue['masked_id'], QUEUE_ID & 0x7FFF)
        self.assertEqual(queue['alloc_counter_u16'], 0)
        self.assertEqual([step['kind'] for step in queue['lookup_steps']],
                         ['trie0', 'trie1', 'trie2', 'leaf'])
        self.assertIn('provenance', state)

    def test_direct_table_queue_id(self):
        memory = FakeGuestMemory()
        default_fixture(memory)
        memory.write_u32(QUEUE_TABLE + 4 + 4 * 2, QUEUE_OBJ)
        lookup = lookup_local_queue(memory, LIBOSAL, 0x8002)
        self.assertEqual(lookup['object'], QUEUE_OBJ)
        self.assertEqual(lookup['masked_id'], 2)
        self.assertEqual([step['kind'] for step in lookup['steps']],
                         ['direct'])

    def test_non_local_queue_id_is_refused(self):
        with self.assertRaisesRegex(ValueError, 'local_queue_id_required'):
            inspect_guest_allocator(self.memory, LIBOSAL, queue_id=0x192)

    def test_absent_queue_object_is_refused(self):
        memory = FakeGuestMemory()
        write_fblock(memory, [FB_POOL])
        write_vpool(memory, [(VP_POOL, VP_POOL_SIZE)])
        with self.assertRaisesRegex(ValueError, 'queue_object_absent'):
            inspect_guest_allocator(memory, LIBOSAL)

    def test_locked_fblock_is_refused(self):
        write_fblock(self.memory, [FB_POOL], lock=0x80000001)
        with self.assertRaisesRegex(ValueError, 'fblock_locked'):
            inspect_guest_allocator(self.memory, LIBOSAL)

    def test_fblock_waiters_are_refused(self):
        write_fblock(self.memory, [FB_POOL], waiters=0x50010000)
        with self.assertRaisesRegex(ValueError, 'fblock_waiters_present'):
            inspect_guest_allocator(self.memory, LIBOSAL)

    def test_foreign_fblock_free_head_is_refused(self):
        # E0335 hazard: e0686 left a UIPC-pool block on the guest free list.
        write_fblock(self.memory, [0x503B3CE0])
        with self.assertRaisesRegex(ValueError, 'fblock_foreign_free_head'):
            inspect_guest_allocator(self.memory, LIBOSAL)

    def test_fblock_free_list_cycle_is_refused(self):
        write_fblock(self.memory, [FB_POOL, FB_POOL + 0x20])
        self.memory.write_u32(FB_POOL + 0x20, FB_POOL)  # cycle
        with self.assertRaisesRegex(ValueError, 'fblock_free_list_cycle'):
            inspect_guest_allocator(self.memory, LIBOSAL)

    def test_fblock_remaining_mismatch_is_refused(self):
        write_fblock(self.memory, [FB_POOL], remaining=0x40)
        with self.assertRaisesRegex(ValueError, 'fblock_remaining_mismatch'):
            inspect_guest_allocator(self.memory, LIBOSAL)

    def test_fblock_remaining_beyond_pool_is_refused(self):
        write_fblock(self.memory, [FB_POOL], remaining=FB_POOL_SIZE + 0x20,
                     min_remaining=0)
        with self.assertRaisesRegex(ValueError, 'fblock_remaining_invalid'):
            inspect_guest_allocator(self.memory, LIBOSAL)

    def test_fblock_min_above_remaining_is_refused(self):
        write_fblock(self.memory, [FB_POOL], remaining=0x20,
                     min_remaining=0x40)
        with self.assertRaisesRegex(ValueError, 'fblock_min_remaining_invalid'):
            inspect_guest_allocator(self.memory, LIBOSAL)

    def test_vpool_locked_and_waiting_are_refused(self):
        write_vpool(self.memory, [(VP_POOL, VP_POOL_SIZE)], lock=0x80000001)
        with self.assertRaisesRegex(ValueError, 'vpool_locked'):
            inspect_guest_allocator(self.memory, LIBOSAL)
        write_vpool(self.memory, [(VP_POOL, VP_POOL_SIZE)], waiters=0x50010000)
        with self.assertRaisesRegex(ValueError, 'vpool_waiters_present'):
            inspect_guest_allocator(self.memory, LIBOSAL)

    def test_vpool_free_bytes_mismatch_is_refused(self):
        write_vpool(self.memory, [(VP_POOL, VP_POOL_SIZE)],
                    free_bytes=VP_POOL_SIZE - 8)
        with self.assertRaisesRegex(ValueError, 'vpool_free_bytes_mismatch'):
            inspect_guest_allocator(self.memory, LIBOSAL)

    def test_vpool_beyond_pool_is_refused(self):
        write_vpool(self.memory, [(VP_POOL, VP_POOL_SIZE + 8)],
                    pool_size=VP_POOL_SIZE, free_bytes=VP_POOL_SIZE)
        with self.assertRaisesRegex(ValueError, 'vpool_block_beyond_pool'):
            inspect_guest_allocator(self.memory, LIBOSAL)

    def test_vpool_unsorted_list_is_refused(self):
        write_vpool(self.memory, [(VP_POOL + 0x100, 0x40),
                                  (VP_POOL, 0x40)],
                    pool_size=0x200, free_bytes=0x80)
        with self.assertRaisesRegex(ValueError, 'vpool_free_list_unsorted'):
            inspect_guest_allocator(self.memory, LIBOSAL)

    def test_allocator_pools_overlap_is_refused(self):
        write_fblock(self.memory, [FB_POOL + 0x20, FB_POOL + 0x40])
        write_vpool(self.memory, [(FB_POOL, 0x1000)], pool_base=FB_POOL,
                    pool_size=0x1000)
        with self.assertRaisesRegex(ValueError, 'allocator_pools_overlap'):
            inspect_guest_allocator(self.memory, LIBOSAL)

    def test_undercounted_queue_counter_is_refused(self):
        write_queue_object(self.memory, counter=0xFFFF)
        with self.assertRaisesRegex(ValueError, 'alloc_counter_undercounted'):
            inspect_guest_allocator(self.memory, LIBOSAL)

    def test_queue_alloc_failure_marker_is_refused(self):
        write_queue_object(self.memory, alloc_flags=0x02)
        with self.assertRaisesRegex(ValueError, 'queue_alloc_flags_set'):
            inspect_guest_allocator(self.memory, LIBOSAL)

    def test_per_queue_vpool_override_is_refused(self):
        write_queue_object(self.memory, vpool_override=0x50450000)
        with self.assertRaisesRegex(ValueError, 'per_queue_vpool_unmodelled'):
            inspect_guest_allocator(self.memory, LIBOSAL)

    def test_async_queue_flag_ignores_the_override_field(self):
        # alloc_msg_by_queue 0x366C skips the +0x1C check when flags bit3 is set.
        write_queue_object(self.memory, flags=0x08, vpool_override=0x50450000)
        state = inspect_guest_allocator(self.memory, LIBOSAL)
        self.assertEqual(state['queue']['flags'], 0x08)

    def test_unreadable_memory_is_refused(self):
        with self.assertRaisesRegex(ValueError, 'unreadable'):
            inspect_guest_allocator(FakeGuestMemory(), 0x60000000)


class GuestAllocatorPlanTests(unittest.TestCase):
    def setUp(self):
        self.memory = default_fixture(FakeGuestMemory())

    def plan(self, size, **kwargs):
        return plan_message_alloc(self.memory, LIBOSAL, size, **kwargs)

    def test_small_message_uses_fblock_and_authentic_header(self):
        plan = self.plan(4)
        self.assertEqual(plan['kind'], 'guest-osal-message-alloc')
        self.assertEqual(plan['allocator'], 'fblock')
        message = plan['message']
        self.assertEqual(message['head'], FB_POOL)
        self.assertEqual(message['payload'], FB_POOL + 0x0C)
        self.assertEqual(message['size_units'], 0)
        self.assertEqual(message['payload_capacity'], 0x14)
        self.assertEqual(message['priority'], MESSAGE_PRIORITY)
        self.assertEqual(message['refcount'], MESSAGE_REFCOUNT_INITIAL)
        self.assertEqual(message['source'], OSAL_SOURCE_PLACEHOLDER)
        self.assertEqual(message['next'], 0)
        self.assertEqual(plan['queue']['alloc_counter_before'], 0)
        self.assertEqual(plan['queue']['alloc_counter_after'], 1)
        self.assertEqual([write['label'] for write in plan['write_provenance']],
                         ['fblock_pop', 'fblock_remaining',
                          'fblock_min_remaining', 'queue_alloc_counter',
                          'message_next', 'message_header'])
        self.assertEqual(plan['bounded']['write_count'], len(plan['writes']))
        self.assertLessEqual(len(plan['writes']), MAX_PLAN_WRITES)

    def test_fblock_plan_writes_pop_remaining_counter_and_header(self):
        plan = self.plan(4)
        self.assertEqual(plan['writes'], [
            (FB_CTL + 0x04, struct.pack('<I', FB_POOL + 0x20)),
            (FB_CTL + 0x14, struct.pack('<I', 0x60)),
            (FB_CTL + 0x18, struct.pack('<I', 0x60)),
            (QUEUE_OBJ + QUEUE_ALLOC_COUNTER_OFFSET, struct.pack('<H', 1)),
            (FB_POOL, struct.pack('<I', 0)),
            (FB_POOL + 0x04,
             bytes([0x00, 0x01, 0x01, 0x00, 0xA5, 0xA5, 0xA5, 0xA5])),
        ])

    def test_min_remaining_write_is_conditional(self):
        # new remaining = 0x40 - 0x20 = 0x20.  With min 0x40 it drops below the
        # minimum -> write; with min equal 0x20 the strict '<' compare does not.
        write_fblock(self.memory, [FB_POOL, FB_POOL + 0x20],
                     remaining=0x40, min_remaining=0x40)
        plan = self.plan(4)
        labels = [write['label'] for write in plan['write_provenance']]
        self.assertIn('fblock_min_remaining', labels)
        min_write = next(write for write in plan['writes']
                         if write[0] == FB_CTL + 0x18)
        self.assertEqual(min_write[1], struct.pack('<I', 0x20))
        write_fblock(self.memory, [FB_POOL, FB_POOL + 0x20],
                     remaining=0x40, min_remaining=0x20)
        plan = self.plan(4)
        self.assertNotIn('fblock_min_remaining',
                         [write['label'] for write in plan['write_provenance']])

    def test_size_boundary_0x14_vs_0x15(self):
        plan_small = self.plan(0x14)
        self.assertEqual(plan_small['allocator'], 'fblock')
        self.assertEqual(plan_small['message']['payload_capacity'], 0x14)
        plan_large = self.plan(0x15)
        self.assertEqual(plan_large['allocator'], 'vpool')
        self.assertEqual(plan_large['message']['size_units'], 2)
        self.assertEqual(plan_large['message']['payload_capacity'], 0x34)

    def test_large_message_uses_vpool_split(self):
        plan = self.plan(0x80)
        self.assertEqual(plan['allocator'], 'vpool')
        self.assertEqual(plan['allocator_detail']['mode'], 'split')
        message = plan['message']
        self.assertEqual(message['rounded_size'], 0xA0)
        self.assertEqual(message['size_units'], 5)
        self.assertEqual(message['payload_capacity'], 0xA0 - 0x0C)
        self.assertEqual(message['head'], VP_POOL + VP_POOL_SIZE - 0xA0)
        self.assertEqual(message['payload'], message['head'] + 0x0C)
        labels = [write['label'] for write in plan['write_provenance']]
        self.assertEqual(labels, ['vpool_split', 'vpool_free_bytes',
                                  'vpool_min_free', 'queue_alloc_counter',
                                  'message_next', 'message_header'])
        self.assertEqual(plan['writes'][0],
                         (VP_POOL + 0x04,
                          struct.pack('<I', VP_POOL_SIZE - 0xA0)))
        self.assertEqual(plan['writes'][1],
                         (VP_CTL + 0x14,
                          struct.pack('<I', VP_POOL_SIZE - 0xA0)))
        self.assertEqual(plan['writes'][2],
                         (VP_CTL + 0x18,
                          struct.pack('<I', VP_POOL_SIZE - 0xA0)))

    def test_vpool_exact_fit_unlinks_the_head(self):
        write_vpool(self.memory, [(VP_POOL, 0xA0)], pool_size=0xA0)
        plan = self.plan(0x80)
        self.assertEqual(plan['allocator_detail']['mode'], 'exact-fit')
        self.assertEqual(plan['message']['head'], VP_POOL)
        self.assertEqual([write['label'] for write in plan['write_provenance']],
                         ['vpool_unlink', 'vpool_free_bytes', 'vpool_min_free',
                          'queue_alloc_counter', 'message_next',
                          'message_header'])
        self.assertEqual(plan['writes'][0],
                         (VP_CTL + 0x04, struct.pack('<I', 0)))
        self.assertEqual(plan['writes'][1],
                         (VP_CTL + 0x14, struct.pack('<I', 0)))
        self.assertEqual(plan['writes'][2],
                         (VP_CTL + 0x18, struct.pack('<I', 0)))

    def test_vpool_exact_fit_unlinks_after_predecessor(self):
        write_vpool(self.memory, [(VP_POOL, 0x40),
                                  (VP_POOL + 0x40, 0xA0)])
        plan = self.plan(0x80)
        self.assertEqual(plan['allocator_detail']['mode'], 'exact-fit')
        self.assertEqual(plan['message']['head'], VP_POOL + 0x40)
        self.assertEqual(plan['writes'][0],
                         (VP_POOL, struct.pack('<I', 0)))

    def test_vpool_size_units_rounding(self):
        # (0x15+0x2B)&~0x1F = 0x40 -> 2 units; (0x35+0x2B)&~0x1F = 0x60 -> 3.
        self.assertEqual(self.plan(0x15)['message']['size_units'], 2)
        self.assertEqual(self.plan(0x34)['message']['size_units'], 2)
        self.assertEqual(self.plan(0x35)['message']['size_units'], 3)

    def test_source_override_is_recorded_in_header(self):
        plan = self.plan(4, source=0x12345678)
        self.assertEqual(plan['message']['source'], 0x12345678)
        header_write = plan['writes'][-1][1]
        self.assertEqual(header_write[0], 0)
        self.assertEqual(header_write[1], MESSAGE_PRIORITY)
        self.assertEqual(struct.unpack('<H', header_write[2:4])[0],
                         MESSAGE_REFCOUNT_INITIAL)
        self.assertEqual(struct.unpack('<I', header_write[4:8])[0], 0x12345678)

    def test_empty_fblock_free_list_is_refused(self):
        write_fblock(self.memory, [])
        with self.assertRaisesRegex(ValueError, 'fblock_free_list_empty'):
            self.plan(4)

    def test_no_vpool_block_is_refused(self):
        # request 0xA0 fits the pool size but no single free block is big enough
        write_vpool(self.memory, [(VP_POOL, 0x20)], pool_size=VP_POOL_SIZE)
        with self.assertRaisesRegex(ValueError, 'vpool_no_block'):
            self.plan(0x80)

    def test_vpool_request_beyond_pool_is_refused(self):
        with self.assertRaisesRegex(ValueError, 'vpool_request_exceeds_pool'):
            self.plan(0x1000)

    def test_size_range_is_validated(self):
        for size in (-1, 0x1001, 1.5, True, '4'):
            with self.subTest(size=size):
                with self.assertRaises(ValueError):
                    self.plan(size)

    def test_counter_overflow_is_refused(self):
        write_queue_object(self.memory, counter=0x7FFF)
        with self.assertRaisesRegex(ValueError, 'alloc_counter_overflow'):
            self.plan(4)

    def test_plan_is_deterministic(self):
        first = self.plan(0x80)
        second = self.plan(0x80)
        self.assertEqual(first['writes'], second['writes'])
        self.assertEqual(first['write_provenance'],
                         second['write_provenance'])
        self.assertEqual(first['message'], second['message'])

    def test_planner_is_read_only(self):
        before = bytes(self.memory.memory)
        self.plan(4)
        self.plan(0x80)
        inspect_guest_allocator(self.memory, LIBOSAL)
        self.assertEqual(bytes(self.memory.memory), before)
        self.assertGreater(len(self.memory.reads), 0)

    def test_writes_are_aligned_unique_and_bounded(self):
        for size in (4, 0x15, 0x80):
            with self.subTest(size=size):
                plan = self.plan(size)
                addresses = [address for address, _data in plan['writes']]
                self.assertEqual(len(addresses), len(set(addresses)))
                self.assertLessEqual(len(plan['writes']), MAX_PLAN_WRITES)
                for address, data in plan['writes']:
                    alignment = 4 if len(data) >= 4 else 2
                    self.assertEqual(address % alignment, 0)

    def test_applied_fblock_plan_leaves_a_consistent_allocator(self):
        plan = self.plan(4)
        self.memory.apply(plan['writes'])
        state = inspect_guest_allocator(self.memory, LIBOSAL)
        self.assertEqual(state['fblock']['free_list_head'], FB_POOL + 0x20)
        self.assertEqual(state['fblock']['remaining_bytes'], 0x60)
        self.assertEqual(state['fblock']['free_block_count'], 3)
        self.assertEqual(state['queue']['alloc_counter_u16'], 1)

    def test_applied_vpool_plan_leaves_a_consistent_allocator(self):
        plan = self.plan(0x80)
        self.memory.apply(plan['writes'])
        state = inspect_guest_allocator(self.memory, LIBOSAL)
        self.assertEqual(state['vpool']['free_bytes'], VP_POOL_SIZE - 0xA0)
        self.assertEqual(state['vpool']['free_blocks'],
                         [{'address': VP_POOL, 'next': 0,
                           'size': VP_POOL_SIZE - 0xA0}])
        self.assertEqual(state['queue']['alloc_counter_u16'], 1)

    def test_fblock_alloc_free_roundtrip_returns_to_original_state(self):
        original = inspect_guest_allocator(self.memory, LIBOSAL)
        plan = self.plan(4)
        self.memory.apply(plan['writes'])
        head = plan['message']['head']
        current = inspect_guest_allocator(self.memory, LIBOSAL)
        self.memory.apply([
            (head + 0x06, struct.pack('<H', 0)),  # osal_free_msg refcount -> 0
            (QUEUE_OBJ + 0x06, struct.pack('<H', 0)),  # counter decrement
            (head, struct.pack('<I', current['fblock']['free_list_head'])),
            (FB_CTL + 0x04, struct.pack('<I', head)),  # free_fblock push
            (FB_CTL + 0x14,
             struct.pack('<I', current['fblock']['remaining_bytes']
                         + FBLOCK_BLOCK_SIZE)),
        ])
        reverted = inspect_guest_allocator(self.memory, LIBOSAL)
        self.assertEqual(reverted['fblock']['free_list_head'],
                         original['fblock']['free_list_head'])
        self.assertEqual(reverted['fblock']['remaining_bytes'],
                         original['fblock']['remaining_bytes'])
        self.assertEqual(reverted['fblock']['free_block_count'],
                         original['fblock']['free_block_count'])
        self.assertEqual(reverted['queue']['alloc_counter_u16'], 0)

    def test_vpool_alloc_free_roundtrip_returns_to_original_state(self):
        original = inspect_guest_allocator(self.memory, LIBOSAL)
        plan = self.plan(0x80)
        self.memory.apply(plan['writes'])
        current = inspect_guest_allocator(self.memory, LIBOSAL)
        # The allocation was split from the single low free block, so freeing
        # it coalesces back into that block (vpool_free 0x4EEC..0x4EFA).
        self.memory.apply([
            (plan['message']['head'] + 0x06, struct.pack('<H', 0)),
            (QUEUE_OBJ + 0x06, struct.pack('<H', 0)),
            (VP_POOL + 0x04,
             struct.pack('<I', current['vpool']['free_bytes']
                         + plan['message']['rounded_size'])),
            (VP_CTL + 0x14,
             struct.pack('<I', current['vpool']['free_bytes']
                         + plan['message']['rounded_size'])),
        ])
        reverted = inspect_guest_allocator(self.memory, LIBOSAL)
        self.assertEqual(reverted['vpool']['free_bytes'],
                         original['vpool']['free_bytes'])
        self.assertEqual(reverted['vpool']['free_blocks'],
                         original['vpool']['free_blocks'])
        self.assertEqual(reverted['queue']['alloc_counter_u16'], 0)

    def test_render_alloc_plan_lines(self):
        plan = self.plan(0x80)
        lines = render_alloc_plan(plan)
        self.assertIsInstance(lines, list)
        text = '\n'.join(lines)
        self.assertIn('guest OSAL message allocation plan', text)
        self.assertIn('allocator: vpool', text)
        self.assertIn('0x%08x' % plan['message']['head'], text)
        self.assertIn('size_units=5', text)
        self.assertIn('ordered writes', text)
        self.assertIn('assumption:', text)

    def test_module_imports_without_emulator_dependencies(self):
        self.assertFalse(hasattr(planner, 'unicorn'))
        self.assertEqual(planner.MESSAGE_PAYLOAD_BIAS, 0x0C)
        self.assertIn('eecc322b', planner.PROVENANCE['source'])


if __name__ == '__main__':
    unittest.main()
