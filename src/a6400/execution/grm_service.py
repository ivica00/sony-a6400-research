"""Authentic Graphics Resource Manager (GRM-MA) service contract.

Verified against Sony firmware modules /usr/kmod/grm_ma.ko, /usr/kmod/dmm.ko,
userland library /usr/lib/libObj.so, and Evidence records E0044 through E0055.

Pool policies
-------------
``pool_policy='gl-common-only'`` (default) keeps the single verified
``gl_common`` pool contract used by the earlier milestones: every open/lookup
reports physical base 0x202e0000, size 0x02000000 and kernel handle 0x68a96220,
and all allocations come from that one pool. This path is unchanged.

``pool_policy='captured-e0044'`` is an explicit opt-in policy built from the six
captured allocator objects of E0044. Lookup answers are taken from the captured
reciprocal list (first name match in captured list order, matching
``ma_list_findbyname`` traversal); ``ma_dmm_open_impl`` answers only unit 0x280
(``gl_common``), because E0046 shows the original open path contains no name
lookup. Unknown names, units and allocation handles are reported as explicit
failures instead of being mapped to ``gl_common``. Allocation offsets are kept
per captured pool, because the captured objects are separate allocators.
"""

import struct
from typing import Any, Dict, List, NamedTuple, Optional

# Verified queue ID for synchronous GRM-MA requests (ma_init)
GRM_MA_SERVICE_QUEUE = 0x014c0424
DMM_SERVICE_QUEUE = 0x0061003c

# Verified gl_common allocation parameters (E0044, E0045, E0047, E0050)
GRM_POOL_PHYS_BASE = 0x202e0000
GRM_POOL_SIZE = 0x02000000       # 32 MiB
GRM_KERNEL_HANDLE = 0x68a96220    # Captured gl_common kernel object pointer
GRM_DMM_HANDLE = 0x0417          # SearchUnitTypeToHandle(0x280) handle
MA_ERR_NONE = 0                  # MA_ErrNone (0)
# E0045 negative control: an absent name returns status -9 with zero base/size/
# handle and no retain-count write. The captured-e0044 policy reuses this
# negative status for unit/handle refusals that have no executed evidence.
MA_ERR_NOT_FOUND = -9

# E0046: the startup-shaped original open uses unit 0x280 (gl_common) only.
GRM_UNIT_GL_COMMON = 0x0280

POOL_POLICY_GL_COMMON_ONLY = 'gl-common-only'
POOL_POLICY_CAPTURED_E0044 = 'captured-e0044'
POOL_POLICIES = (POOL_POLICY_GL_COMMON_ONLY, POOL_POLICY_CAPTURED_E0044)

# E0044 records each allocator object's physical address; embedded list links
# are cached kernel pointers equal to object physical + 0x60000000 + 0x14.
# The E0045 executed lookup returns gl_common's cached object pointer
# 0x68a96220, which agrees with 0x08a96220 + 0x60000000 and with E0044's
# cached link 0x68a96234. The same captured conversion is applied to the other
# captured objects to obtain their kernel handles.
CAPTURED_E0044_CACHED_OFFSET = 0x60000000


class CapturedPool(NamedTuple):
    """One E0044 allocator object as captured in the reciprocal list."""

    name: str
    object_physical: int
    phys_base: int
    pool_size: int

    @property
    def kernel_handle(self) -> int:
        return (self.object_physical + CAPTURED_E0044_CACHED_OFFSET) & 0xFFFFFFFF


# Captured E0044 reciprocal list, in traversal order from the candidate head's
# forward link. The two zero-named records are listed as E0044 labels them.
CAPTURED_E0044_POOLS = (
    CapturedPool('empty', 0x00B7F2A0, 0x23B16000, 0x96000),
    CapturedPool('mpMemoryHeap2', 0x08ABD560, 0x226E0000, 0x1A0000),
    CapturedPool('mpTextHeap', 0x08ABD5A0, 0x22880000, 0x200000),
    CapturedPool('mpMemoryHeap', 0x00B7F2E0, 0x222E0000, 0x400000),
    CapturedPool('empty', 0x00B7F360, 0x23A80000, 0x96000),
    CapturedPool('gl_common', 0x08A96220, 0x202E0000, 0x02000000),
)


def _captured_pool_by_name(name: str) -> Optional[CapturedPool]:
    """First captured list match, mirroring circular-list traversal order."""
    for pool in CAPTURED_E0044_POOLS:
        if pool.name == name:
            return pool
    return None


def _captured_pool_by_handle(handle: int) -> Optional[CapturedPool]:
    for pool in CAPTURED_E0044_POOLS:
        if pool.kernel_handle == handle:
            return pool
    return None


def _captured_pool_by_unit(unit: int) -> Optional[CapturedPool]:
    """Only unit 0x280 has executed open-path evidence (E0046)."""
    if unit != GRM_UNIT_GL_COMMON:
        return None
    return _captured_pool_by_name('gl_common')


class GrmMaService:
    """Services synchronous UIPC requests to GRM-MA (queue 0x014c0424).

    Implements the authentic ma_user_sync_cb dispatch contract:
    - Opcode 1: ma_dmm_open_impl (unit 0x280 / gl_common)
    - Opcode 2: ma_dmm_close_impl
    - Opcode 7: ma_findbyname_impl (lookup gl_common)
    - Opcode 9: ma_malloc_impl (allocate buffer from gl_common pool)

    ``pool_policy`` selects the pool contract; see the module docstring. The
    default ``gl-common-only`` behaviour and all reply offsets are unchanged.
    """

    def __init__(self,
                 phys_base: int = GRM_POOL_PHYS_BASE,
                 pool_size: int = GRM_POOL_SIZE,
                 kernel_handle: int = GRM_KERNEL_HANDLE,
                 pool_policy: str = POOL_POLICY_GL_COMMON_ONLY):
        if pool_policy not in POOL_POLICIES:
            raise ValueError('Unknown GRM pool policy')
        if pool_policy == POOL_POLICY_CAPTURED_E0044 and (
                phys_base, pool_size, kernel_handle) != (
                    GRM_POOL_PHYS_BASE, GRM_POOL_SIZE, GRM_KERNEL_HANDLE):
            raise ValueError(
                'captured-e0044 policy uses the captured pool table; '
                'custom gl_common parameters are not supported')
        self.phys_base = phys_base
        self.pool_size = pool_size
        self.kernel_handle = kernel_handle
        self.pool_policy = pool_policy
        self.next_alloc_offset = 0
        # Captured-e0044 allocation offsets, keyed by captured object physical.
        self.pool_alloc_offsets: Dict[int, int] = {}
        self.events: List[Dict[str, Any]] = []

    def handle_uipc_sync_message(self, memory_reader, memory_writer, msg_ptr: int, alloc_size: int = 64) -> int:
        """Dispatches an incoming synchronous UIPC message to GRM-MA."""
        raw_msg = memory_reader(msg_ptr, min(alloc_size, 64))
        if len(raw_msg) < 4:
            return -1

        opcode = struct.unpack_from('<H', raw_msg, 0)[0]
        event: Dict[str, Any] = {'msg_ptr': msg_ptr, 'opcode': opcode}

        if opcode == 1:
            # Opcode 1: ma_dmm_open_impl(param_1 + 2, param_1 + 0xe)
            # param_1 + 2 (byte 4): unit (uint32)
            # param_1 + 4 (byte 8): name string (up to 16 bytes)
            # Reply written to param_1 + 0xe (byte 28):
            #   offset +28: status (0 = MA_ErrNone)
            #   offset +32: phys_base (0x202e0000)
            #   offset +36: size (32 MiB)
            #   offset +40: kernel_handle (0x68a96220)
            unit = struct.unpack_from('<I', raw_msg, 4)[0] if len(raw_msg) >= 8 else 0
            # (int)param_1 + 5 in ma_dmm_open_impl points to byte offset 9
            if len(raw_msg) > 9 and raw_msg[9] != 0:
                raw_name = raw_msg[9:25].split(b'\x00')[0]
            else:
                raw_name = raw_msg[8:24].split(b'\x00')[0] if len(raw_msg) >= 24 else b''
            name_str = raw_name.decode('latin1', errors='ignore')

            if self.pool_policy == POOL_POLICY_CAPTURED_E0044:
                # E0046: the original open contains no name lookup; only unit
                # 0x280 has executed evidence. Do not fall back to gl_common
                # for any other unit.
                pool = _captured_pool_by_unit(unit)
                if pool is None:
                    if memory_writer:
                        memory_writer(msg_ptr + 28,
                                      struct.pack('<iIII', MA_ERR_NOT_FOUND, 0, 0, 0))
                    event.update({
                        'action': 'ma_dmm_open_impl_unsupported_unit',
                        'unit': f'0x{unit:04x}',
                        'name': name_str,
                        'status': MA_ERR_NOT_FOUND,
                        'pool_policy': POOL_POLICY_CAPTURED_E0044
                    })
                else:
                    reply = struct.pack('<IIII', MA_ERR_NONE, pool.phys_base,
                                        pool.pool_size, pool.kernel_handle)
                    if memory_writer:
                        memory_writer(msg_ptr + 28, reply)

                    event.update({
                        'action': 'ma_dmm_open_impl',
                        'unit': f'0x{unit:04x}',
                        'name': name_str,
                        'status': MA_ERR_NONE,
                        'phys_base': f'0x{pool.phys_base:08x}',
                        'pool_size': pool.pool_size,
                        'handle': f'0x{pool.kernel_handle:08x}',
                        'pool_name': pool.name,
                        'pool_policy': POOL_POLICY_CAPTURED_E0044
                    })
            else:
                reply = struct.pack('<IIII', MA_ERR_NONE, self.phys_base, self.pool_size, self.kernel_handle)
                if memory_writer:
                    memory_writer(msg_ptr + 28, reply)

                event.update({
                    'action': 'ma_dmm_open_impl',
                    'unit': f'0x{unit:04x}',
                    'name': name_str,
                    'status': MA_ERR_NONE,
                    'phys_base': f'0x{self.phys_base:08x}',
                    'pool_size': self.pool_size,
                    'handle': f'0x{self.kernel_handle:08x}'
                })

        elif opcode == 7:
            # Opcode 7: ma_findbyname_impl(param_1 + 2, param_1 + 10)
            # param_1 + 2 (byte 4): name string (16 bytes)
            # Reply written to param_1 + 10 (byte 20):
            #   offset +20: status (0 = MA_ErrNone)
            #   offset +24: phys_base
            #   offset +28: size
            #   offset +32: kernel_handle
            raw_name = raw_msg[4:20].split(b'\x00')[0] if len(raw_msg) >= 20 else b''
            name_str = raw_name.decode('latin1', errors='ignore')

            if self.pool_policy == POOL_POLICY_CAPTURED_E0044:
                pool = _captured_pool_by_name(name_str)
                if pool is None:
                    # E0045 negative control: absent name -> status -9, empty
                    # base/size/handle. Never substitute the gl_common row.
                    if memory_writer:
                        memory_writer(msg_ptr + 20,
                                      struct.pack('<iIII', MA_ERR_NOT_FOUND, 0, 0, 0))
                    event.update({
                        'action': 'ma_findbyname_impl_unknown_name',
                        'name': name_str,
                        'status': MA_ERR_NOT_FOUND,
                        'pool_policy': POOL_POLICY_CAPTURED_E0044
                    })
                else:
                    reply = struct.pack('<IIII', MA_ERR_NONE, pool.phys_base,
                                        pool.pool_size, pool.kernel_handle)
                    if memory_writer:
                        memory_writer(msg_ptr + 20, reply)

                    event.update({
                        'action': 'ma_findbyname_impl',
                        'name': name_str,
                        'status': MA_ERR_NONE,
                        'phys_base': f'0x{pool.phys_base:08x}',
                        'pool_size': pool.pool_size,
                        'handle': f'0x{pool.kernel_handle:08x}',
                        'pool_name': pool.name,
                        'pool_policy': POOL_POLICY_CAPTURED_E0044
                    })
            else:
                reply = struct.pack('<IIII', MA_ERR_NONE, self.phys_base, self.pool_size, self.kernel_handle)
                if memory_writer:
                    memory_writer(msg_ptr + 20, reply)

                event.update({
                    'action': 'ma_findbyname_impl',
                    'name': name_str,
                    'status': MA_ERR_NONE,
                    'phys_base': f'0x{self.phys_base:08x}',
                    'pool_size': self.pool_size,
                    'handle': f'0x{self.kernel_handle:08x}'
                })

        elif opcode == 9:
            # Opcode 9: ma_malloc_impl(param_1 + 2, param_1 + 8)
            # param_1 + 2 (byte 4): handle
            # param_1 + 4 (byte 8): alloc size
            # Reply written to param_1 + 8 (byte 16):
            #   offset +16: status (0 = MA_ErrNone)
            #   offset +20: allocated address (phys_base + offset)
            handle = struct.unpack_from('<I', raw_msg, 4)[0] if len(raw_msg) >= 8 else 0
            size = struct.unpack_from('<I', raw_msg, 8)[0] if len(raw_msg) >= 12 else 0

            if self.pool_policy == POOL_POLICY_CAPTURED_E0044:
                pool = _captured_pool_by_handle(handle)
                if pool is None:
                    if memory_writer:
                        memory_writer(msg_ptr + 16,
                                      struct.pack('<iI', MA_ERR_NOT_FOUND, 0))
                    event.update({
                        'action': 'ma_malloc_impl_unknown_handle',
                        'handle': f'0x{handle:08x}',
                        'req_size': size,
                        'status': MA_ERR_NOT_FOUND,
                        'pool_policy': POOL_POLICY_CAPTURED_E0044
                    })
                else:
                    # The captured objects are separate allocators, so each
                    # pool tracks its own allocation offset; a single global
                    # offset would move requests outside their declared pool.
                    offset = self.pool_alloc_offsets.get(pool.object_physical, 0)
                    alloc_addr = pool.phys_base + offset
                    # Align next allocation to 4096-byte page boundary
                    aligned_size = (size + 4095) & ~4095
                    self.pool_alloc_offsets[pool.object_physical] = offset + aligned_size

                    reply = struct.pack('<II', MA_ERR_NONE, alloc_addr)
                    if memory_writer:
                        memory_writer(msg_ptr + 16, reply)

                    event.update({
                        'action': 'ma_malloc_impl',
                        'handle': f'0x{handle:08x}',
                        'req_size': size,
                        'alloc_addr': f'0x{alloc_addr:08x}',
                        'status': MA_ERR_NONE,
                        'pool_name': pool.name,
                        'pool_offset': offset,
                        'pool_policy': POOL_POLICY_CAPTURED_E0044
                    })
            else:
                alloc_addr = self.phys_base + self.next_alloc_offset
                # Align next allocation to 4096-byte page boundary
                aligned_size = (size + 4095) & ~4095
                self.next_alloc_offset += aligned_size

                reply = struct.pack('<II', MA_ERR_NONE, alloc_addr)
                if memory_writer:
                    memory_writer(msg_ptr + 16, reply)

                event.update({
                    'action': 'ma_malloc_impl',
                    'handle': f'0x{handle:08x}',
                    'req_size': size,
                    'alloc_addr': f'0x{alloc_addr:08x}',
                    'status': MA_ERR_NONE
                })

        elif opcode == 2:
            # Opcode 2: ma_dmm_close_impl(param_1 + 2, param_1 + 4)
            # Reply written to param_1 + 4 (byte 8):
            #   offset +8: status (0 = MA_ErrNone)
            if memory_writer:
                memory_writer(msg_ptr + 8, struct.pack('<I', MA_ERR_NONE))

            event.update({
                'action': 'ma_dmm_close_impl',
                'status': MA_ERR_NONE
            })

        else:
            # Unsupported opcode
            event.update({
                'action': 'unsupported_opcode',
                'status': -1
            })

        self.events.append(event)
        return 0

    def handle_dmm_message(self, memory_reader, memory_writer, msg_ptr: int, uipc) -> Optional[Dict[str, Any]]:
        """Handles an asynchronous DMM service request (queue 0x0061003c).

        Verified against Sony firmware module /usr/kmod/dmm.ko (dmm_ctrl_AllocUnitNewHdlr)
        and libObj.so (dmpNative::InternalCmd::alloc_sync).
        """
        raw_req = memory_reader(msg_ptr, min(64, uipc.allocated_msgs.get(msg_ptr, 32)))
        if len(raw_req) < 24:
            return None

        opcode = struct.unpack_from('<H', raw_req, 0)[0]
        unit = struct.unpack_from('<I', raw_req, 4)[0]
        reply_queue = struct.unpack_from('<I', raw_req, 16)[0]
        req_id = struct.unpack_from('<H', raw_req, 20)[0]

        if reply_queue == 0:
            return None

        # Allocate reply message in shared UIPC pool
        reply_ptr = uipc.allocate_message(size=32)

        # Write sender queue ID at reply_ptr - 4 for osal_get_msg_src(reply_ptr) == 0x0061003c
        memory_writer(reply_ptr - 4, struct.pack('<I', DMM_SERVICE_QUEUE))

        # Build completion packet (dmm_comp):
        # offset 0: opcode (uint16)
        # offset 2: ret_code = 0 (int16, OSAL_ERR_OK)
        # offset 4: handle = GRM_DMM_HANDLE (0x0417)
        # offset 6: req_id = req_id (uint16, matching request)
        # offset 8: phys_base (uint32, 0x202e0000)
        # offset 12: size (uint32, 0x02000000)
        # offset 16 (0x10): phys_base (uint32, 0x202e0000) - consumed by this->mem.map
        # offset 20 (0x14): size (uint32, 0x02000000) - consumed by this->mem.map
        # offset 24: unused (uint32, 0)
        # offset 28: unused (uint32, 0)
        reply_data = struct.pack('<hhHHIIIIII', opcode, 0, GRM_DMM_HANDLE, req_id,
                                 self.phys_base, self.pool_size,
                                 self.phys_base, self.pool_size,
                                 0, 0)
        memory_writer(reply_ptr, reply_data)

        # Enqueue reply into caller's dynamic reply queue
        uipc.enqueue_message(reply_queue, reply_ptr)

        event = {
            'action': 'dmm_ctrl_AllocUnitNewHdlr',
            'queue': '0x0061003c',
            'reply_queue': f'0x{reply_queue:08x}',
            'opcode': opcode,
            'unit': f'0x{unit:08x}',
            'req_id': req_id,
            'handle': f'0x{GRM_DMM_HANDLE:04x}',
            'ret_code': 0,
            'reply_ptr': reply_ptr
        }
        self.events.append(event)
        return event

