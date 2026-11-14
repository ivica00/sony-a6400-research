"""Partial /dev/uipc transport model; recipient services are separate contracts."""

import struct
from typing import Dict, List, Optional, Tuple
from src.a6400.execution.capped_log import CappedLog
from src.a6400.execution.guest_uipc_ids import KernelDynamicIds, UnsupportedDynamicId
from src.a6400.execution.uipc_kernel_queues import KERNEL_QUEUE_CENSUS

# Linux ARM ioctl commands recognized by osal_uipc.ko
UIPC_CMD_STAT_SEM = 0x80000000
UIPC_CMD_WAI_SEM_TMO = 0x80000001
UIPC_CMD_SIG_SEM = 0x80000002
UIPC_CMD_STAT_MSGQ = 0x80000003
UIPC_CMD_SND_MSG = 0x80000004
UIPC_CMD_SND_SYNC_MSG = 0x80000005
UIPC_CMD_SND_SYNC_DIRECT = 0x80000006
TIMER_COUNTER_QUEUE = 0x910042  # utimer_kif_counter: u64 microsecond counter
TIMER_DELAY_QUEUE = 0x910041    # utimer delay queue: wait until absolute u64 deadline at message +24
TIMER_OBJECT_QUEUE = 0x910040  # osal timer objects: op0 create .. op5 free
TIMER_OBJECT_EVENT_QUEUE_BASE = 0x00EE0000  # shortcut: synthetic per-object queue ids; real ids unknown
UIPC_CMD_RCV_MSG_TMO = 0x80000007
UIPC_CMD_REG_MSG_QUEUE_CB = 0x80000008
UIPC_CMD_UNREG_MSG_QUEUE_CB = 0x80000009
UIPC_CMD_VALLOC_MSG_WAIT = 0x8000000a
UIPC_CMD_FREE_MSG = 0x8000000b
UIPC_CMD_DYNAMIC_ID = 0x8000000c
UIPC_CMD_WAIT_CB = 0x8000000d
UIPC_CMD_SET_MSGQ_BROADCAST_MODE = 0x8000000e
UIPC_CMD_SET_MSGQ_LOG_MODE = 0x8000000f
UIPC_CMD_CONNECT = 0x80000010

# Default pool geometry from osal_uipc driver
DEFAULT_TOTAL_POOL_SIZE = 0x100000   # 1 MiB shared pool
DEFAULT_VPOOL_SIZE = 0x40000        # 256 KiB
DEFAULT_FBLOCK_SIZE = 0x8000        # 32 KiB
BACKUP_SERVICE_QUEUE = 0x003e014d
GRM_MA_SERVICE_QUEUE = 0x014c0424
DMM_SERVICE_QUEUE = 0x0061003c
MEDIA_COMMON_DRIVER_QUEUE = 0x00d9016e
# Queues whose consumer is a kernel module callback (not a user thread). In the real kernel snd_msg
# runs the callback in the sender's context and the callback frees the message.
KERNEL_CONSUMED_QUEUES = {0x008f013a: 'osal_ulogio.ko', 0x008f0139: 'osal_ulogio.ko'}
# Two listener threads serve 0x8f013a and one serves 0x8f0139. Op 0x8001 ("userspace started") sets
# the flag read back by sync op 0x8012 and then ends that listener.
ULOGIO_LISTENERS = {0x008f013a: 2, 0x008f0139: 1}
ULOGIO_SYNC_QUEUE = 0x008f013a
ULOGIO_OP_USERSPACE_STARTED = 0x8001
ULOGIO_OP_GET_STATE = 0x8012   # sync: reply +0x40 = started flag, +0x44 = status 0
# op 0x111 on the sync framework queue returns the 7-word boot-factor
# struct in the message: word0 = request code, word1 = boot key (KEY_* index; the kernel default is 2 = KEY_POWER).
UPM_FRAMEWORK_QUEUE = 0x00924127
UPM_OP_GET_BOOT_FACTOR = 0x111
# Kernel UIPC: sync send to a queue with no callback / pool exhaustion (user wrapper returns -errno).
UIPC_ERR_NO_CALLBACK = -1020
UIPC_ERR_POOL_EXHAUSTED = -1023
# Scheduler-only wait key; never exposed as a guest queue identifier.
CALLBACK_WAIT_KEY = -1

# E0303 opt-in: generic async-callback completion. The original kernel
# dynamic-ID descriptors (E0301 ARM controls) put ordinary queues in
# 0x6000..0x6fff and broadcast queues in 0x7000..0x7fff; a CONNECT callback
# control queue is type 0x2a/key 0x3f and is allocated from that ordinary
# dynamic pool (camera observation 0x003f6091, fresh model 0x003f6000).
KERNEL_E0303 = 'kernel-e0303'
CONNECT_CALLBACK_CONTROL_TYPE = 0x2a
CONNECT_CALLBACK_CONTROL_KEY = 0x3f
BROADCAST_QUEUE_RANGE = (0x7000, 0x8000)


class UnsupportedUipc(RuntimeError):
    def __init__(self, reason, **details):
        self.details = {'reason': reason, **details}
        super().__init__(reason)

class GuestUipc:
    """Models selected kernel character-device operations for /dev/uipc.
    
    Verified against Sony firmware module /usr/kmod/osal_uipc.ko and
    userland library /usr/lib/libosal_uipc.so. Recognizing the transport ABI
    does not establish recipient execution or a valid service reply.
    """
    # Class defaults so checkpoints pickled before these attributes existed still load.
    upm_boot_key = None   # opt-in: int boot key returned for the upm boot-factor request (None = reply left unmodelled)
    model_info_reply = None   # opt-in: entry count for the 0x1004 reply to the model-info sync callback on queue 0x870136 (None = no reply; G stays 0)
    capid_table_reply = None   # opt-in: physical address in the 0x1000 reply of the capture-ID-table service (queue 0x4015e); None = requests stay unanswered
    sync_direct_mode = 'return'   # 'yield': ask the interpreter to switch threads after snd_sync_direct
    yield_requested = False
    timer_service = 'off'         # 'emulated': queue 0x910042 counter reply, 0x910041 timed wait (interpreter blocks)
    timer_dirty = False           # an osal timer object was armed/stopped/freed: the interpreter re-syncs deadlines
    timer_wait = None             # absolute deadline (us) the interpreter must block the caller until
    now_us = 0                    # guest time (us), set by the interpreter before each ioctl

    def __init__(self,
                 total_pool_size: int = DEFAULT_TOTAL_POOL_SIZE,
                 vpool_size: int = DEFAULT_VPOOL_SIZE,
                 fblock_size: int = DEFAULT_FBLOCK_SIZE,
                 backup_service_policy: str = 'stop',
                 backup_service: Optional[object] = None,
                 graphics_service_policy: str = 'stop',
                 grm_service: Optional[object] = None,
                 media_service_policy: str = 'stop',
                 media_service: Optional[object] = None,
                 sync_callback_delivery_policy: str = 'unmodelled'):
        if backup_service_policy not in ('stop', 'unverified-ack', 'preset-backed'):
            raise ValueError('Unknown backup service policy')
        if graphics_service_policy not in ('stop', 'authentic-grm'):
            raise ValueError('Unknown graphics service policy')
        if media_service_policy not in ('stop', 'authentic-sd'):
            raise ValueError('Unknown media service policy')
        if sync_callback_delivery_policy not in ('unmodelled', 'kernel-origin'):
            raise ValueError('Unknown sync callback delivery policy')
        self.sync_callback_delivery_policy = sync_callback_delivery_policy
        self.media_service_policy = media_service_policy
        self.media_service = media_service
        if self.media_service_policy == 'authentic-sd' and self.media_service is None:
            from src.a6400.execution.guest_media_common import GuestMediaCommon
            self.media_service = GuestMediaCommon()
        self.backup_service_policy = backup_service_policy
        self.backup_service = backup_service
        if self.backup_service_policy == 'preset-backed' and self.backup_service is None:
            from src.a6400.execution.backup_service import BK4PresetState, PresetBackedBackupService
            self.backup_service = PresetBackedBackupService(BK4PresetState.load_default())
        self.graphics_service_policy = graphics_service_policy
        self.grm_service = grm_service
        if self.graphics_service_policy == 'authentic-grm' and self.grm_service is None:
            from src.a6400.execution.grm_service import GrmMaService
            self.grm_service = GrmMaService()
        self.total_pool_size = total_pool_size
        self.vpool_size = vpool_size
        self.fblock_size = fblock_size
        self.connected = False
        self.pool_base: Optional[int] = None
        self.allocated_msgs: Dict[int, int] = {} # msg_addr -> size
        self.next_offset = 0x20 # Keep header area reserved
        self.callbacks: Dict[int, Dict[str, object]] = {}
        self.semaphores: Dict[int, Dict[str, object]] = {}
        self.message_queues: Dict[int, List[int]] = {}
        self.next_dynamic_id = 0x80001001
        self.dynamic_ids: Dict[int, int] = {}
        self.transactions: List[Dict[str, object]] = []  # replaced by a CappedLog under --syscall-record-limit
        self.kernel_contract_revision = 1
        self.kernel_dynamic_ids = KernelDynamicIds()
        # E0303 generic completion bookkeeping (unused by earlier policies).
        self.connect_callback_control_queue: Optional[int] = None
        self.queue_consumer_cursor: Dict[int, int] = {}
        self.broadcast_message_deliveries: Dict[Tuple[int, int], set] = {}

    def handle_connect(self, memory_reader, memory_writer, arg_ptr: int) -> int:
        """Handles ioctl 0x80000010 (__k_4u_connect).
        
        arg_ptr points to struct { uint32_t cmd; void *buf; }.
        Kernel writes pool dimensions [total_pool_size, vpool_size, fblock_size, reserved].
        """
        raw_arg = memory_reader(arg_ptr, 8)
        _, buf_ptr = struct.unpack('<II', raw_arg)
        callback_control = 0
        if getattr(self, 'pool_options_policy', '') == 'kernel-e0301':
            if self.connected:
                raise UnsupportedUipc('uipc_repeated_connect_not_implemented')
            _, callback_control = self.kernel_dynamic_ids.allocate(0x2a, 0x3f)
        elif getattr(self, 'pool_options_policy', '') == KERNEL_E0303:
            # E0303: the CONNECT fourth word is never a constant. It is the
            # original dynamic-ID allocator's ordinary-queue slot for the
            # verified callback-control descriptor type 0x2a/key 0x3f. When
            # prior allocations occupy slots, the value changes accordingly.
            if self.connected:
                raise UnsupportedUipc('uipc_repeated_connect_not_implemented')
            result, callback_control = self.kernel_dynamic_ids.allocate(
                CONNECT_CALLBACK_CONTROL_TYPE, CONNECT_CALLBACK_CONTROL_KEY)
            if result != 0 or callback_control is None:
                raise UnsupportedUipc('uipc_connect_callback_control_alloc_failed',
                                      returned=result)
            self.connect_callback_control_queue = callback_control
        pool_info = struct.pack('<4I', self.total_pool_size, self.vpool_size, self.fblock_size, callback_control)
        memory_writer(buf_ptr, pool_info)
        self.connected = True
        self.transactions.append({'type': 'connect', 'total_pool': self.total_pool_size, 'buf_ptr': buf_ptr,
                                  'callback_control_queue': callback_control})
        return 0

    @property
    def kernel_pool_options(self):
        return getattr(self, 'pool_options_policy', 'legacy-empty') in (
            'kernel-e0300', 'kernel-e0301', KERNEL_E0303)

    def initialize_pool_options(self, memory_writer):
        """Write only k_uipc_init's verified option stores (E0300, opt-in).

        This is not the kernel allocator/RT-pool initialization. Bytes not
        explicitly stored by the original instructions are left untouched.
        """
        if not self.kernel_pool_options:
            return
        if self.pool_base is None or (self.total_pool_size, self.vpool_size,
                                      self.fblock_size) != (0x100000, 0x40000, 0x8000):
            raise UnsupportedUipc('kernel_pool_options_geometry_mismatch')
        memory_writer(self.pool_base, struct.pack('<5I', 0x100000, 0x20000,
                                                 0x40000, 0x8000, 4))
        memory_writer(self.pool_base + 0x15, b'\x01\x00')
        self.transactions.append({'type': 'pool_options', 'policy': self.pool_options_policy,
                                  'base': self.pool_base, 'proxy_threads': 4,
                                  'kernel_allocator_initialized': False})

    def _holes(self):
        holes = self.__dict__.get('free_blocks')
        if holes is None:  # old checkpoints: rebuild holes from the live set
            holes, pos = [], 0x20
            for a in sorted(self.allocated_msgs):
                raw = a - 12 - self.pool_base
                if raw > pos:
                    holes.append((pos, raw - pos))
                pos = raw + self.allocated_msgs[a] + 12
            if self.next_offset > pos:
                holes.append((pos, self.next_offset - pos))
            self.free_blocks = holes
        return holes

    def _pool_alloc(self, alloc_size: int) -> Optional[int]:
        """First-fit from freed holes, else bump; returns pool offset or None (ENOMEM)."""
        holes = self._holes()
        for i, (off, size) in enumerate(holes):
            if size >= alloc_size:
                if size == alloc_size:
                    del holes[i]
                else:
                    holes[i] = (off + alloc_size, size - alloc_size)
                return off
        if self.next_offset + alloc_size > self.total_pool_size:
            return None
        off = self.next_offset
        self.next_offset += alloc_size
        return off

    def _pool_free(self, msg_addr: int) -> None:
        holes = self._holes()  # before the pop: old checkpoints rebuild holes from the live set
        size = self.allocated_msgs.pop(msg_addr) + 12
        holes.append((msg_addr - 12 - self.pool_base, size))
        holes.sort()
        merged = [holes[0]]
        for off, sz in holes[1:]:
            if merged[-1][0] + merged[-1][1] == off:
                merged[-1] = (merged[-1][0], merged[-1][1] + sz)
            else:
                merged.append((off, sz))
        self.free_blocks = merged

    def _kernel_policy(self) -> bool:
        return getattr(self, 'pool_options_policy', '') in ('kernel-e0301', KERNEL_E0303)

    def _msg_op(self, memory_reader, msg_ptr: int) -> Optional[int]:
        try:
            return struct.unpack('<H', memory_reader(msg_ptr, 2))[0]
        except Exception:
            return None

    def _count(self, queue: int, what: str, op: Optional[int] = None) -> None:
        stats = self.__dict__.setdefault('queue_stats', {})  # checkpoints from before this field load fine
        key = '%#x/%s' % (queue, what) if op is None else '%#x/%s/op%#x' % (queue, what, op)
        stats[key] = stats.get(key, 0) + 1

    def handle_valloc_msg_wait(self, memory_reader, memory_writer, arg_ptr: int) -> int:
        """Handles ioctl 0x8000000a (__k_4u_valloc_msg_wait).
        
        arg_ptr points to struct { uint32_t pool_id; void *params; }.
        params points to struct { void **out_msg_ptr; uint32_t size; uint32_t flag; }.
        """
        if self.pool_base is None:
            return -14 # EFAULT / ENODEV before mmap

        raw_arg = memory_reader(arg_ptr, 8)
        pool_id, params_ptr = struct.unpack('<II', raw_arg)
        raw_params = memory_reader(params_ptr, 12)
        out_ptr_addr, req_size, flag = struct.unpack('<III', raw_params)

        # Authentic Sony OSAL UIPC allocation geometry:
        # Blocks are 32 bytes. Header occupies 12 bytes preceding user payload pointer.
        # If req_size <= 20, fits in single 32-byte block (num_blocks recorded as 0).
        # If req_size > 20, alloc_size = (req_size + 43) & ~31, num_blocks = alloc_size >> 5.
        if req_size <= 20:
            num_blocks = 0
            alloc_size = 32
        else:
            alloc_size = (req_size + 43) & ~31
            num_blocks = alloc_size >> 5

        off = self._pool_alloc(alloc_size)
        if off is None:
            return UIPC_ERR_POOL_EXHAUSTED if self._kernel_policy() else -12 # legacy: ENOMEM
        raw_addr = self.pool_base + off

        # Write authentic OSAL raw header (12 bytes):
        #   offset 0 (uint32): link/pool descriptor (0)
        #   offset 4 (uint8):  num_blocks (read by osal_msg_size at [msg_ptr - 8])
        #   offset 5 (uint8):  flags (1)
        #   offset 6 (uint16): ref_count (1, decremented by osal_free_msg at [msg_ptr - 6])
        #   offset 8 (uint32): magic / queue ID (0xa5a5a5a5 at [msg_ptr - 4])
        hdr = struct.pack('<IBBHI', 0, num_blocks, 1, 1, 0xa5a5a5a5)
        memory_writer(raw_addr, hdr)

        msg_addr = raw_addr + 12
        self.allocated_msgs[msg_addr] = alloc_size - 12

        # Write user-space pointer back to caller's destination
        memory_writer(out_ptr_addr, struct.pack('<I', msg_addr))
        self.transactions.append({
            'type': 'valloc',
            'pool_id': pool_id,
            'msg_addr': msg_addr,
            'raw_addr': raw_addr,
            'size': req_size,
            'num_blocks': num_blocks,
            'flag': flag
        })
        return 0

    def handle_snd_sync_msg(self, memory_reader, arg_ptr: int, memory_writer=None, tid=None) -> int:
        """Handles ioctl 0x80000005 (__k_4u_snd_sync_msg).
        
        arg_ptr points to struct { uint32_t target_queue; void *params; }.
        params points to struct { void *msg_ptr; uint32_t tmo; uint32_t flag; }.
        """
        raw_arg = memory_reader(arg_ptr, 8)
        target_queue, params_ptr = struct.unpack('<II', raw_arg)
        raw_params = memory_reader(params_ptr, 12)
        msg_ptr, tmo, flag = struct.unpack('<III', raw_params)

        if getattr(self, 'pool_options_policy', '') in ('kernel-e0301', KERNEL_E0303):
            sync = [(handle, cb) for handle, cb in self.callbacks.items()
                    if cb['queue'] == target_queue and cb['flags'] == 1]
            if sync:
                if len(sync) != 1 or tid is None or memory_writer is None:
                    raise UnsupportedUipc('uipc_sync_callback_identity_not_supplied', queue=target_queue)
                handle, cb = sync[0]
                if not cb['callback'] or msg_ptr not in self.allocated_msgs:
                    raise UnsupportedUipc('uipc_sync_callback_invalid_message_or_function',
                                          queue=target_queue, msg_ptr=msg_ptr)
                active = getattr(self, 'sync_callback_inflight', {})
                key = (tid, target_queue, msg_ptr)
                header_flags = memory_reader(msg_ptr - 7, 1)[0]
                if tmo:
                    if (active.get(key) != handle or tmo != cb['callback'] or flag != cb['user_data']
                            or not header_flags & 0x80):
                        raise UnsupportedUipc('uipc_sync_callback_completion_mismatch', queue=target_queue)
                    memory_writer(msg_ptr - 7, bytes([header_flags & 0x7f]))
                    del active[key]
                    self.transactions.append({'type': 'sync_cb_completion', 'queue': target_queue,
                                              'msg_ptr': msg_ptr, 'tid': tid, 'handle': handle})
                    return 0
                if key in active or header_flags & 0x80:
                    raise UnsupportedUipc('uipc_sync_callback_already_active', queue=target_queue)
                active[key] = handle
                self.sync_callback_inflight = active
                memory_writer(msg_ptr - 7, bytes([header_flags | 0x80]))
                memory_writer(params_ptr, struct.pack('<3I', msg_ptr, cb['callback'], cb['user_data']))
                self.transactions.append({'type': 'sync_cb_delivery', 'queue': target_queue,
                                          'msg_ptr': msg_ptr, 'callback': cb['callback'],
                                          'user_data': cb['user_data'], 'tid': tid, 'handle': handle})
                return 0

        op = self._msg_op(memory_reader, msg_ptr)
        self._count(target_queue, 'snd_sync_msg', op)
        if self._kernel_policy() and memory_writer is not None:
            if target_queue == ULOGIO_SYNC_QUEUE and op == ULOGIO_OP_GET_STATE                     and self.allocated_msgs.get(msg_ptr, 0) >= 0x48:
                started = int(bool(getattr(self, 'ulogio_started', False)))
                memory_writer(msg_ptr + 0x40, struct.pack('<II', started, 0))
                self.transactions.append({'type': 'snd_sync_msg', 'target_queue': target_queue,
                                          'msg_ptr': msg_ptr, 'op': op, 'ulogio_started': started,
                                          'classification': 'kernel sync handler: state flag + status 0 (other state bytes not modeled)'})
                return 0
            if (target_queue == UPM_FRAMEWORK_QUEUE and op == UPM_OP_GET_BOOT_FACTOR
                    and self.upm_boot_key is not None and self.allocated_msgs.get(msg_ptr, 0) >= 0x1c):
                memory_writer(msg_ptr + 4, struct.pack('<I', self.upm_boot_key))
                self.transactions.append({'type': 'snd_sync_msg', 'target_queue': target_queue, 'msg_ptr': msg_ptr,
                                          'op': op, 'upm_boot_key': self.upm_boot_key,
                                          'classification': 'boot-factor reply: only word1 (boot key) supplied, other words 0'})
                return 0
            if (target_queue not in KERNEL_QUEUE_CENSUS and target_queue not in KERNEL_CONSUMED_QUEUES
                    and target_queue not in (BACKUP_SERVICE_QUEUE, GRM_MA_SERVICE_QUEUE, DMM_SERVICE_QUEUE,
                                             MEDIA_COMMON_DRIVER_QUEUE)
                    and not any(cb['queue'] == target_queue for cb in self.callbacks.values())):
                self._count(target_queue, 'no_callback')
                self.transactions.append({'type': 'snd_sync_msg', 'target_queue': target_queue,
                                          'msg_ptr': msg_ptr, 'op': op, 'status': UIPC_ERR_NO_CALLBACK})
                return UIPC_ERR_NO_CALLBACK

        # Read message header/body preview
        msg_preview = memory_reader(msg_ptr, min(64, self.allocated_msgs.get(msg_ptr, 32)))
        if target_queue == BACKUP_SERVICE_QUEUE:
            if self.backup_service_policy == 'stop':
                words = list(struct.unpack('<' + 'I' * (len(msg_preview) // 4), msg_preview[:len(msg_preview) // 4 * 4]))
                raise UnsupportedUipc('backup_service_reply_not_supplied', queue=target_queue,
                                      msg_ptr=msg_ptr, timeout=tmo, flag=flag,
                                      request_words=words, preview_hex=msg_preview.hex(),
                                      replies_supplied=0)
            elif self.backup_service_policy == 'preset-backed':
                if self.backup_service is None:
                    raise UnsupportedUipc('backup_service_not_initialized')
                self.backup_service.handle_uipc_sync_message(
                    memory_reader, memory_writer, msg_ptr, self.allocated_msgs.get(msg_ptr, 64)
                )
        elif target_queue == MEDIA_COMMON_DRIVER_QUEUE:
            if self.media_service_policy == 'stop':
                words = list(struct.unpack('<' + 'I' * (len(msg_preview) // 4), msg_preview[:len(msg_preview) // 4 * 4]))
                raise UnsupportedUipc('media_service_reply_not_supplied', queue=target_queue,
                                      msg_ptr=msg_ptr, timeout=tmo, flag=flag,
                                      request_words=words, preview_hex=msg_preview.hex(),
                                      replies_supplied=0)
            elif self.media_service_policy == 'authentic-sd':
                if self.media_service is not None and memory_writer is not None:
                    self.media_service.handle_message(memory_reader, memory_writer, msg_ptr, self)
        elif target_queue == GRM_MA_SERVICE_QUEUE:
            if self.graphics_service_policy == 'stop':
                words = list(struct.unpack('<' + 'I' * (len(msg_preview) // 4), msg_preview[:len(msg_preview) // 4 * 4]))
                raise UnsupportedUipc('graphics_service_reply_not_supplied', queue=target_queue,
                                      msg_ptr=msg_ptr, timeout=tmo, flag=flag,
                                      request_words=words, preview_hex=msg_preview.hex(),
                                      replies_supplied=0)
            elif self.graphics_service_policy == 'authentic-grm':
                if self.grm_service is None:
                    raise UnsupportedUipc('grm_service_not_initialized')
                self.grm_service.handle_uipc_sync_message(
                    memory_reader, memory_writer, msg_ptr, self.allocated_msgs.get(msg_ptr, 64)
                )

        self.transactions.append({
            'type': 'snd_sync_msg',
            'target_queue': target_queue,
            'msg_ptr': msg_ptr,
            'tmo': tmo,
            'flag': flag,
            'preview_hex': msg_preview.hex(),
            'preview_ascii': msg_preview.decode('latin1', errors='replace')
        })
        if target_queue == BACKUP_SERVICE_QUEUE:
            if self.backup_service_policy == 'unverified-ack':
                self.transactions[-1]['classification'] = 'unverified acknowledgement; no backup service executed'
            elif self.backup_service_policy == 'preset-backed':
                self.transactions[-1]['classification'] = 'preset-backed verified preset; authentic operations and RAM mutations'
        elif target_queue == GRM_MA_SERVICE_QUEUE:
            if self.graphics_service_policy == 'authentic-grm':
                self.transactions[-1]['classification'] = 'authentic-grm verified gl_common pool and allocation'
        return 0

    def handle_free_msg(self, memory_reader, arg_ptr: int) -> int:
        """Handles ioctl 0x8000000b (__k_4u_free_msg).
        
        arg_ptr points to struct { uint32_t pool_id; void *msg_ptr; }.
        """
        raw_arg = memory_reader(arg_ptr, 8)
        pool_id, msg_ptr = struct.unpack('<II', raw_arg)
        if msg_ptr in self.allocated_msgs:
            self._pool_free(msg_ptr)
        self.transactions.append({
            'type': 'free_msg',
            'pool_id': pool_id,
            'msg_ptr': msg_ptr
        })
        return 0

    def handle_reg_msg_queue_cb(self, memory_reader, memory_writer, arg_ptr: int) -> int:
        """Handles ioctl 0x80000008 (__k_4u_reg_msg_queue_cb).
        
        arg_ptr points to struct { uint32_t queue; void *params; }.
        params points to struct { uint32_t *out_handle; uint32_t cb; uint32_t user_data; uint32_t flags; }.
        """
        raw_arg = memory_reader(arg_ptr, 8)
        queue, params_ptr = struct.unpack('<II', raw_arg)
        raw_params = memory_reader(params_ptr, 16)
        out_handle_ptr, cb, user_data, flags = struct.unpack('<IIII', raw_params)

        # max+1, not 0x1000+len: after an unregister, len-based ids collided with live handles.
        handle_id = max(self.callbacks, default=0xFFF) + 1
        memory_writer(out_handle_ptr, struct.pack('<I', handle_id))
        self.callbacks[handle_id] = {
            'queue': queue,
            'callback': cb,
            'user_data': user_data,
            'flags': flags
        }
        self.transactions.append({
            'type': 'reg_cb',
            'queue': queue,
            'handle': handle_id,
            'callback': cb,
            'user_data': user_data,
            'flags': flags
        })
        self.deliver_model_info_reply(memory_writer)
        return 0

    MODEL_INFO_REPLY_QUEUE = 0x870136

    def deliver_model_info_reply(self, memory_writer) -> bool:
        """Opt-in: queue the 0x1004 message (entry count at +0x14) that the model-info
        sync callback (registered on queue 0x870136) expects; the sender is an
        unmodelled service. count 0 makes the callback set G=2, else G=1."""
        if self.model_info_reply is None or self.pool_base is None:
            return False
        q = self.MODEL_INFO_REPLY_QUEUE
        if not any(cb['queue'] == q and cb['flags'] == 1 for cb in self.callbacks.values()):
            return False
        if getattr(self, '_model_info_reply_sent', False):
            return False
        msg = self.allocate_message(0x20, memory_writer)
        memory_writer(msg, struct.pack('<I', 0x1004) + bytes(0x1c))
        memory_writer(msg + 0x14, struct.pack('<I', self.model_info_reply))
        self.enqueue_message(q, msg)
        self._model_info_reply_sent = True
        self.transactions.append({'type': 'model_info_reply', 'queue': q, 'msg_ptr': msg,
                                  'count': self.model_info_reply})
        return True

    def handle_unreg_msg_queue_cb(self, memory_reader, arg_ptr: int) -> int:
        """Handles ioctl 0x80000009 (__k_4u_unreg_msg_queue_cb).

        E0306 observed the original call with a struct whose first two words are
        the registered queue id and the callback handle (0x4b024e / 0x104a,
        matching callbacks[4170]).  Only a registered, non-inflight callback is
        removed; identity mismatches stay explicit boundaries.
        """
        if getattr(self, 'pool_options_policy', '') not in ('kernel-e0301', KERNEL_E0303):
            raise UnsupportedUipc('uipc_unregister_requires_kernel_policy')
        raw_arg = memory_reader(arg_ptr, 8)
        queue, handle = struct.unpack('<II', raw_arg)
        registered = self.callbacks.get(handle)
        if registered is None or registered['queue'] != queue:
            raise UnsupportedUipc('uipc_unreg_callback_identity_not_supplied',
                                  queue=queue, handle=handle)
        inflight = getattr(self, 'callback_inflight', {})
        if any(entry.get('handle') == handle for entry in inflight.values()):
            raise UnsupportedUipc('uipc_unreg_callback_inflight', handle=handle)
        sync_inflight = getattr(self, 'sync_callback_inflight', {})
        if any(callback_handle == handle for callback_handle in sync_inflight.values()):
            raise UnsupportedUipc('uipc_unreg_callback_inflight', handle=handle)
        del self.callbacks[handle]
        self.transactions.append({'type': 'unreg_cb', 'queue': queue, 'handle': handle})
        return 0

    def handle_snd_sync_direct(self, memory_reader, arg_ptr: int, memory_writer=None) -> int:
        """Handles ioctl 0x80000006 (__k_4u_snd_sync_direct).
        
        arg_ptr points to struct { uint32_t queue; void *buf; }.
        buf begins with a 16-byte header [uint32_t total_size, f1, f2, f3]
        followed by (total_size - 16) payload bytes.
        """
        raw_arg = memory_reader(arg_ptr, 8)
        queue, buf_ptr = struct.unpack('<II', raw_arg)
        header = memory_reader(buf_ptr, 16)
        total_size, f1, f2, f3 = struct.unpack('<IIII', header)
        payload_len = total_size - 16 if total_size >= 16 else 0
        payload = memory_reader(buf_ptr + 16, payload_len) if payload_len else b''

        self.transactions.append({
            'type': 'snd_sync_direct',
            'queue': queue,
            'total_size': total_size,
            'payload_hex': payload.hex(),
            'payload_ascii': payload.decode('latin1', errors='replace')
        })
        if self.timer_service == 'emulated' and queue == TIMER_OBJECT_QUEUE and total_size >= 48 and memory_writer is not None:
            self._timer_object_op(buf_ptr, payload, memory_writer)
            return 0
        if self.timer_service == 'emulated' and queue in (TIMER_COUNTER_QUEUE, TIMER_DELAY_QUEUE):
            # Body = message +16 (evidence 0041); the client reads the u64 at message +24.
            if queue == TIMER_COUNTER_QUEUE and total_size >= 32 and memory_writer is not None:
                selector = struct.unpack('<I', payload[:4])[0]
                memory_writer(buf_ptr + 20, struct.pack('<i', 0 if selector in (0, 1) else -1024))
                if selector in (0, 1):
                    memory_writer(buf_ptr + 24, struct.pack('<Q', self.now_us))
            elif queue == TIMER_DELAY_QUEUE and total_size >= 40:
                deadline = struct.unpack('<Q', memory_reader(buf_ptr + 24, 8))[0]
                self.timer_wait = deadline if deadline > self.now_us else None
            return 0
        # Only the interpreter owns the thread switch; it consumes this after the ioctl returns.
        self.yield_requested = self.sync_direct_mode == 'yield'
        return 0

    def _timer_object_op(self, buf_ptr: int, payload: bytes, memory_writer) -> None:
        """Message +0x10 op, +0x14 reply status, +0x18 key, +0x20.. op args/replies."""
        # Arming records an absolute guest-time deadline; fire_timer() then posts the 0x18-byte body
        # {fn, arg, msg handle, key, period lo, hi} to the object's queue, where its registered callback runs.
        op, _status, key, _pad, a, b, c = struct.unpack('<7I', payload[:28])
        objs = self.__dict__.setdefault('timer_objects', {})
        status = 0
        if op == 0:
            key = max(objs, default=0) + 1
            objs[key] = {'queue': TIMER_OBJECT_EVENT_QUEUE_BASE + key, 'fn': 0, 'arg': 0, 'handle': 0, 'armed': None}
            memory_writer(buf_ptr + 0x18, struct.pack('<I', key))
            memory_writer(buf_ptr + 0x20, struct.pack('<I', objs[key]['queue']))
        elif key not in objs:
            status = 0xFFFFFC00  # -1024, the osal error code
        elif op == 1:
            objs[key].update(fn=a, arg=b, handle=c)
        elif op == 2:
            # shortcut: (a,b) is taken as a one-shot relative delay in us and c is ignored; periodic
            # use is unverified, upgrade when a trace shows c or a repeat.
            objs[key]['armed'] = (self.now_us + (a | (b << 32)), c)
            self.timer_dirty = True
            self.timer_armed_total = getattr(self, 'timer_armed_total', 0) + 1
        elif op == 3:
            objs[key]['armed'] = None
            self.timer_dirty = True
        elif op == 4:
            memory_writer(buf_ptr + 0x20, struct.pack('<II', objs[key]['queue'], objs[key]['handle']))
        elif op == 5:
            del objs[key]
            self.timer_dirty = True
        else:
            status = 0xFFFFFC00
        memory_writer(buf_ptr + 0x14, struct.pack('<I', status))
        self.transactions[-1].update(timer_object_op=op, key=key, status=status)

    def timer_deadlines(self) -> Dict[int, int]:
        """Armed osal timer objects as {key: absolute guest-time deadline (us)}."""
        return {key: obj['armed'][0] for key, obj in getattr(self, 'timer_objects', {}).items() if obj['armed']}

    def fire_timer(self, key: int, memory_writer) -> bool:
        """Expires one armed timer object: queues its 0x18-byte event body for the registered callback."""
        obj = getattr(self, 'timer_objects', {}).get(key)
        if obj is None or not obj['armed'] or self.pool_base is None:
            return False
        obj['armed'] = None  # one-shot
        msg = self.allocate_message(0x28, memory_writer=memory_writer)
        memory_writer(msg, struct.pack('<4I6I', 0x28, 0, 0, 0, obj['fn'], obj['arg'], obj['handle'], key, 0, 0))
        self.enqueue_message(obj['queue'], msg)
        self.timer_fired = getattr(self, 'timer_fired', 0) + 1
        self.transactions.append({'type': 'timer_fire', 'queue': obj['queue'], 'key': key, 'msg_ptr': msg})
        return True

    def handle_wai_sem_tmo(self, memory_reader, memory_writer, arg_ptr: int) -> int:
        """Handles ioctl 0x80000001 (__k_4u_wai_sem_tmo).
        
        arg_ptr points to struct { uint32_t sem_id; uint32_t timeout; }.
        """
        raw_arg = memory_reader(arg_ptr, 8)
        sem_id, timeout = struct.unpack('<II', raw_arg)
        if sem_id not in self.semaphores:
            self.semaphores[sem_id] = {'locked': False, 'owner': 0, 'waiters': 0}
        sem = self.semaphores[sem_id]
        if not sem['locked']:
            sem['locked'] = True
            sem['owner'] = 1000
            self.transactions.append({
                'type': 'wai_sem_tmo',
                'sem_id': sem_id,
                'timeout': timeout,
                'status': 'acquired'
            })
            return 0
        else:
            if timeout == 0:
                self.transactions.append({
                    'type': 'wai_sem_tmo',
                    'sem_id': sem_id,
                    'timeout': timeout,
                    'status': 'timeout'
                })
                return -1020
            sem['waiters'] += 1
            self.transactions.append({
                'type': 'wai_sem_tmo',
                'sem_id': sem_id,
                'timeout': timeout,
                'status': 'acquired_waiter'
            })
            return 0

    def handle_sig_sem(self, memory_reader, memory_writer, arg_ptr: int) -> int:
        """Handles ioctl 0x80000002 (__k_4u_sig_sem).
        
        arg_ptr points to struct { uint32_t sem_id; uint32_t reserved; }.
        """
        raw_arg = memory_reader(arg_ptr, 8)
        sem_id, _ = struct.unpack('<II', raw_arg)
        if sem_id not in self.semaphores:
            self.semaphores[sem_id] = {'locked': False, 'owner': 0, 'waiters': 0}
        sem = self.semaphores[sem_id]
        sem['locked'] = False
        sem['owner'] = 0
        if sem['waiters'] > 0:
            sem['waiters'] -= 1
        self.transactions.append({
            'type': 'sig_sem',
            'sem_id': sem_id,
            'status': 'signaled'
        })
        return 0

    def handle_stat_sem(self, memory_reader, memory_writer, arg_ptr: int) -> int:
        """Handles ioctl 0x80000000 (__k_4u_stat_sem).
        
        arg_ptr points to struct { uint32_t sem_id; void *out_stat_ptr; }.
        out_stat_ptr receives struct { uint32_t state; uint32_t owner; uint32_t waiters; }.
        """
        raw_arg = memory_reader(arg_ptr, 8)
        sem_id, out_stat_ptr = struct.unpack('<II', raw_arg)
        if sem_id not in self.semaphores:
            self.semaphores[sem_id] = {'locked': False, 'owner': 0, 'waiters': 0}
        sem = self.semaphores[sem_id]
        if out_stat_ptr != 0:
            state = 1 if sem['locked'] else 0
            owner = sem['owner']
            waiters = sem['waiters']
            memory_writer(out_stat_ptr, struct.pack('<III', state, owner, waiters))
        self.transactions.append({
            'type': 'stat_sem',
            'sem_id': sem_id,
            'out_stat_ptr': out_stat_ptr
        })
        return 0

    def handle_snd_msg(self, memory_reader, arg_ptr: int, memory_writer=None) -> int:
        """Handles ioctl 0x80000004 (__k_4u_snd_msg).
        
        arg_ptr points to struct { uint32_t queue; void *msg_ptr; }.
        """
        raw_arg = memory_reader(arg_ptr, 8)
        queue, msg_ptr = struct.unpack('<II', raw_arg)
        op = self._msg_op(memory_reader, msg_ptr)
        self._count(queue, 'snd_msg', op)
        if queue in KERNEL_CONSUMED_QUEUES:
            live = self.__dict__.setdefault('ulogio_listeners', dict(ULOGIO_LISTENERS))
            if live.get(queue, 1) > 0:
                if op == ULOGIO_OP_USERSPACE_STARTED:
                    self.ulogio_started = True
                    live[queue] = live.get(queue, 1) - 1  # the handler exits its listener thread
                if msg_ptr in self.allocated_msgs:
                    self._pool_free(msg_ptr)
                self.transactions.append({'type': 'snd_msg', 'queue': queue, 'msg_ptr': msg_ptr, 'op': op,
                                          'consumed_by': KERNEL_CONSUMED_QUEUES[queue]})
                return 0
            self._count(queue, 'queued_no_listener')  # every listener has exited: the message stays queued
        if queue == self.CAPID_QUEUE and self.capid_table_reply is not None and memory_writer is not None:
            if self._reply_capid(memory_reader, memory_writer, msg_ptr):
                return 0
        if queue not in self.message_queues:
            self.message_queues[queue] = []
        self.message_queues[queue].append(msg_ptr)

        msg_preview = b''
        try:
            msg_preview = memory_reader(msg_ptr, min(64, self.allocated_msgs.get(msg_ptr, 32)))
        except Exception:
            pass

        self.transactions.append({
            'type': 'snd_msg',
            'queue': queue,
            'msg_ptr': msg_ptr,
            'preview_hex': msg_preview.hex(),
        })

        if queue == MEDIA_COMMON_DRIVER_QUEUE:
            if self.media_service_policy == 'stop':
                words = list(struct.unpack('<' + 'I' * (len(msg_preview) // 4), msg_preview[:len(msg_preview) // 4 * 4]))
                raise UnsupportedUipc('media_service_reply_not_supplied', queue=queue,
                                      msg_ptr=msg_ptr, request_words=words, preview_hex=msg_preview.hex())
            elif self.media_service_policy == 'authentic-sd':
                if self.media_service is not None and memory_writer is not None:
                    media_event = self.media_service.handle_message(memory_reader, memory_writer, msg_ptr, self)
                    if media_event:
                        self.transactions[-1]['media_reply'] = media_event
                        self.transactions[-1]['classification'] = media_event.get('classification', 'media common reply')

        if queue == DMM_SERVICE_QUEUE:
            if self.graphics_service_policy == 'authentic-grm' and self.grm_service is not None and memory_writer is not None:
                dmm_event = self.grm_service.handle_dmm_message(memory_reader, memory_writer, msg_ptr, self)
                if dmm_event:
                    self.transactions[-1]['dmm_reply'] = dmm_event
                    self.transactions[-1]['classification'] = 'authentic-grm verified DMM allocation completion'
        return 0

    CAPID_QUEUE = 0x4015e
    CAPID_CMDS = (0x1000, 0x1001)   # 0x1000 returns the table address; 0x1001 follows from the same thread (reply shape assumed identical, unverified)

    def _reply_capid(self, memory_reader, memory_writer, msg_ptr: int) -> bool:
        """Opt-in: the capture-ID-table client sends {0, cmd} (0x18 bytes) to queue 0x4015e with its private reply
        queue id in the OSAL header word at msg-4, then blocks forever on that queue. Answer cmd 0x1000/0x1001 with
        {1, 0x1000, 0, phys}; the object mmaps /dev/mem at phys (the table stays zero-filled). Other commands stay queued."""
        reply_queue, = struct.unpack('<I', memory_reader(msg_ptr - 4, 4))
        cmd, = struct.unpack('<I', memory_reader(msg_ptr + 4, 4))
        self.__dict__.setdefault('capid_seen', []).append((reply_queue, memory_reader(msg_ptr, 0x18).hex()))
        if cmd not in self.CAPID_CMDS or not reply_queue or reply_queue == 0xa5a5a5a5:
            return False
        reply = self.allocate_message(0x18, memory_writer)
        memory_writer(reply, struct.pack('<IIII', 1, 0x1000, 0, self.capid_table_reply) + bytes(8))
        self.enqueue_message(reply_queue, reply)
        if msg_ptr in self.allocated_msgs:
            self._pool_free(msg_ptr)
        self.transactions.append({'type': 'capid_reply', 'queue': reply_queue, 'msg_ptr': reply, 'phys': self.capid_table_reply})
        return True

    def allocate_message(self, size: int = 64, memory_writer=None) -> int:
        """Allocates a message buffer with authentic OSAL header from the UIPC shared pool."""
        if self.pool_base is None:
            raise RuntimeError("Cannot allocate message before UIPC shared pool is mapped")
        if size <= 20:
            num_blocks = 0
            alloc_size = 32
        else:
            alloc_size = (size + 43) & ~31
            num_blocks = alloc_size >> 5
        off = self._pool_alloc(alloc_size)
        if off is None:
            raise MemoryError("UIPC shared pool exhausted")
        raw_addr = self.pool_base + off
        hdr = struct.pack('<IBBHI', 0, num_blocks, 1, 1, 0xa5a5a5a5)
        if memory_writer is not None:
            memory_writer(raw_addr, hdr)
        msg_addr = raw_addr + 12
        self.allocated_msgs[msg_addr] = alloc_size - 12
        return msg_addr

    def enqueue_message(self, queue: int, msg_addr: int) -> None:
        """Enqueues a message buffer address into target message queue."""
        if queue not in self.message_queues:
            self.message_queues[queue] = []
        self.message_queues[queue].append(msg_addr)

    def handle_rcv_msg_tmo(self, memory_reader, memory_writer, arg_ptr: int) -> int:
        """Handles ioctl 0x80000007 (__k_4u_rcv_msg_tmo).

        arg_ptr points to struct { uint32_t queue; uint32_t *p_out_msg; uint32_t out_msg; uint32_t timeout; }.
        """
        raw_arg = memory_reader(arg_ptr, 16)
        queue, p_out_msg, out_msg, timeout = struct.unpack('<IIII', raw_arg)
        msgs = self.message_queues.get(queue, [])
        tid = getattr(self, 'rcv_tid', None)
        deadlines = self.__dict__.setdefault('rcv_deadlines', {})  # tid -> guest-us expiry (--uipc-rcv-timeout modeled)
        if msgs:
            deadlines.pop(tid, None)
            msg = msgs.pop(0)
            target_dest = out_msg if out_msg != 0 else p_out_msg
            if target_dest != 0:
                memory_writer(target_dest, struct.pack('<I', msg))
            self.transactions.append({
                'type': 'rcv_msg_tmo',
                'queue': queue,
                'msg_ptr': msg,
                'status': 'received'
            })
            return 0
        else:
            if timeout == 0xFFFFFFFF:
                return None
            if timeout > 0 and getattr(self, 'rcv_timeout_policy', None) == 'modeled' and tid is not None:
                now = getattr(self, 'clock_us', 0)
                if tid not in deadlines:
                    # shortcut: timeout taken as ms (osal convention assumed, not measured); refine if a trace shows the unit.
                    deadlines[tid] = now + timeout * 1000
                if now < deadlines[tid]:
                    self.rcv_wait = deadlines[tid]  # the probe hands this to the scheduler as a timer deadline
                    return None
                deadlines.pop(tid)
                self.transactions.append({'type': 'rcv_msg_tmo', 'queue': queue, 'status': 'timeout_expired',
                                          'timeout': timeout})
                return -1022
            if timeout > 0 and getattr(self, 'pool_options_policy', '') in ('kernel-e0301', KERNEL_E0303):
                # No virtual-time model: a positive timeout blocks until a message
                # arrives; expiry is not modeled and is recorded explicitly.
                self.transactions.append({
                    'type': 'rcv_msg_tmo',
                    'queue': queue,
                    'status': 'blocked_timeout_not_modeled',
                    'timeout': timeout
                })
                return None
            self.transactions.append({
                'type': 'rcv_msg_tmo',
                'queue': queue,
                'status': 'timeout' if timeout == 0 else 'empty_queue'
            })
            return -1022  # OSAL_ERR_TIMEOUT (0xfffffc02)

    def handle_stat_msgq(self, memory_reader, memory_writer, arg_ptr: int) -> int:
        """Handles ioctl 0x80000003 (__k_4u_stat_msgq).
        
        arg_ptr points to struct { uint32_t queue; void *out_stat_ptr; }.
        """
        raw_arg = memory_reader(arg_ptr, 8)
        queue, out_stat_ptr = struct.unpack('<II', raw_arg)
        msgs = self.message_queues.get(queue, [])
        if out_stat_ptr != 0:
            count = len(msgs)
            memory_writer(out_stat_ptr, struct.pack('<III', count, 128, 0))
        self.transactions.append({
            'type': 'stat_msgq',
            'queue': queue,
            'count': len(msgs)
        })
        return 0

    def handle_dynamic_id(self, memory_reader, memory_writer, arg_ptr: int) -> int:
        """Handles ioctl 0x8000000c (__k_4u_dynamic_id).
        
        Authentic Linux kernel osal_uipc.ko ABI:
          arg_ptr points to struct { uint32_t cmd; void *params; }.
          params points to struct { uint32_t type; uint32_t key; uint32_t *out_id_ptr; }.
        Also accepts direct struct for test compatibility.
        """
        if getattr(self, 'pool_options_policy', '') == KERNEL_E0303:
            # E0303: every dynamic-ID request is served by the original
            # allocator geometry, for both the indirect [cmd,params_ptr] ABI and
            # the legacy direct struct. No synthetic/hardcoded receive id is
            # issued on this policy.
            raw_arg = memory_reader(arg_ptr, 12)
            w0, w1, w2 = struct.unpack('<III', raw_arg)
            is_indirect = False
            if 0x1000 <= w1 < 0xc0000000:
                try:
                    cand_type, cand_key, cand_out = struct.unpack('<III', memory_reader(w1, 12))
                    if 0x1000 <= cand_out < 0xc0000000:
                        type_val, key, out_ptr = cand_type, cand_key, cand_out
                        is_indirect = True
                except Exception:
                    pass
            if not is_indirect:
                type_val, key, out_ptr = w0, w1, w2
            try:
                if type_val & 0x40:
                    result = self.kernel_dynamic_ids.release(type_val, out_ptr)
                    self.transactions.append({'type': 'kernel_dynamic_id_free', 'type_val': type_val,
                                              'id': out_ptr, 'returned': result,
                                              'indirect': is_indirect})
                    return result
                if not out_ptr:
                    return -1024
                result, value = self.kernel_dynamic_ids.allocate(type_val, key)
                if result == 0 and value is not None:
                    memory_writer(out_ptr, struct.pack('<I', value))
                self.transactions.append({'type': 'kernel_dynamic_id_alloc', 'type_val': type_val,
                                          'key': key, 'allocated_id': value, 'returned': result,
                                          'indirect': is_indirect,
                                          'namespace': 'emulated-empty-kernel-allocator'})
                return result
            except UnsupportedDynamicId as error:
                raise UnsupportedUipc(str(error)) from error
        if getattr(self, 'pool_options_policy', '') == 'kernel-e0301':
            _, params = struct.unpack('<II', memory_reader(arg_ptr, 8))
            kind, key, output = struct.unpack('<3I', memory_reader(params, 12))
            try:
                if kind & 0x40:
                    result = self.kernel_dynamic_ids.release(kind, output)
                    self.transactions.append({'type': 'kernel_dynamic_id_free', 'type_val': kind,
                                              'id': output, 'returned': result})
                    return result
                if not output:
                    return -1024
                result, value = self.kernel_dynamic_ids.allocate(kind, key)
                if result == 0:
                    memory_writer(output, struct.pack('<I', value))
                self.transactions.append({'type': 'kernel_dynamic_id_alloc', 'type_val': kind,
                                          'key': key, 'allocated_id': value, 'returned': result,
                                          'namespace': 'emulated-empty-kernel-allocator'})
                return result
            except UnsupportedDynamicId as error:
                raise UnsupportedUipc(str(error)) from error
        raw_arg = memory_reader(arg_ptr, 12)
        w0, w1, w2 = struct.unpack('<III', raw_arg)
        is_indirect = False
        if 0x1000 <= w1 < 0xc0000000:
            try:
                candidate = memory_reader(w1, 12)
                cand_type, cand_key, cand_out = struct.unpack('<III', candidate)
                if 0x1000 <= cand_out < 0xc0000000:
                    type_val, key, out_ptr = cand_type, cand_key, cand_out
                    is_indirect = True
            except Exception:
                pass

        if not is_indirect:
            type_val, key, out_ptr = w0, w1, w2

        if type_val & 0x40:
            self.transactions.append({
                'type': 'dynamic_id_free',
                'type_val': type_val,
                'key': key,
                'out_ptr': out_ptr,
                'indirect': is_indirect
            })
            return 0
        dyn_id = self.next_dynamic_id
        self.next_dynamic_id += 1
        self.dynamic_ids[key] = dyn_id
        if out_ptr != 0:
            memory_writer(out_ptr, struct.pack('<I', dyn_id))
        self.transactions.append({
            'type': 'dynamic_id_alloc',
            'type_val': type_val,
            'key': key,
            'allocated_id': dyn_id,
            'out_ptr': out_ptr,
            'indirect': is_indirect
        })
        return 0

    def handle_ioctl(self, memory_reader, memory_writer, cmd: int, arg: int, tid=None) -> Optional[int]:
        """Dispatches supported UIPC ioctl commands."""
        if cmd == UIPC_CMD_WAIT_CB and self.kernel_pool_options:
            return self.handle_wait_cb(memory_reader, memory_writer, arg, tid=tid)
        if cmd == UIPC_CMD_CONNECT:
            return self.handle_connect(memory_reader, memory_writer, arg)
        elif cmd == UIPC_CMD_VALLOC_MSG_WAIT:
            return self.handle_valloc_msg_wait(memory_reader, memory_writer, arg)
        elif cmd == UIPC_CMD_SND_SYNC_MSG:
            return self.handle_snd_sync_msg(memory_reader, arg, memory_writer=memory_writer, tid=tid)
        elif cmd == UIPC_CMD_SND_MSG:
            return self.handle_snd_msg(memory_reader, arg, memory_writer=memory_writer)
        elif cmd == UIPC_CMD_RCV_MSG_TMO:
            self.rcv_tid = tid  # read by handle_rcv_msg_tmo; wrappers keep the 3-argument signature
            return self.handle_rcv_msg_tmo(memory_reader, memory_writer, arg)
        elif cmd == UIPC_CMD_STAT_MSGQ:
            return self.handle_stat_msgq(memory_reader, memory_writer, arg)
        elif cmd == UIPC_CMD_FREE_MSG:
            return self.handle_free_msg(memory_reader, arg)
        elif cmd == UIPC_CMD_REG_MSG_QUEUE_CB:
            return self.handle_reg_msg_queue_cb(memory_reader, memory_writer, arg)
        elif cmd == UIPC_CMD_UNREG_MSG_QUEUE_CB:
            return self.handle_unreg_msg_queue_cb(memory_reader, arg)
        elif cmd == UIPC_CMD_SND_SYNC_DIRECT:
            return self.handle_snd_sync_direct(memory_reader, arg, memory_writer)
        elif cmd == UIPC_CMD_WAI_SEM_TMO:
            return self.handle_wai_sem_tmo(memory_reader, memory_writer, arg)
        elif cmd == UIPC_CMD_SIG_SEM:
            return self.handle_sig_sem(memory_reader, memory_writer, arg)
        elif cmd == UIPC_CMD_STAT_SEM:
            return self.handle_stat_sem(memory_reader, memory_writer, arg)
        elif cmd == UIPC_CMD_DYNAMIC_ID:
            return self.handle_dynamic_id(memory_reader, memory_writer, arg)
        return None

    def callback_ready(self):
        policy = getattr(self, 'pool_options_policy', '')
        busy = {entry['queue'] for entry in getattr(self, 'callback_inflight', {}).values()}
        sync_ready = (
            getattr(self, 'sync_callback_delivery_policy', 'unmodelled') == 'kernel-origin'
            and any(cb['flags'] == 1 and cb['queue'] not in busy
                    and self.message_queues.get(cb['queue'])
                    for cb in self.callbacks.values()))
        if policy == KERNEL_E0303:
            # E0303: any registered async consumer of a non-busy queue with a
            # pending message makes the proxy loop ready; multiple consumers
            # and broadcast queues are no longer boundaries.
            busy = {entry['queue'] for entry in getattr(self, 'callback_inflight', {}).values()}
            return sync_ready or any(cb['flags'] == 0 and cb['queue'] not in busy
                                     and self.message_queues.get(cb['queue'])
                                     for cb in self.callbacks.values())
        if policy == 'kernel-e0301':
            busy = {entry['queue'] for entry in getattr(self, 'callback_inflight', {}).values()}
            return sync_ready or any(cb['flags'] == 0 and cb['queue'] not in busy
                                     and self.message_queues.get(cb['queue']) for cb in self.callbacks.values())
        return sync_ready or any(self.message_queues.get(cb['queue']) for cb in self.callbacks.values())

    def handle_wait_cb(self, reader, writer, arg, tid=None):
        """E0300 __k_4u_wait_cb: return a tuple to the original proxy loop.

        Completion/ownership for the default and kernel-e0300/e0301 policies is
        unchanged.  ``kernel-e0303`` adds generic async completion: multiple
        async consumers per queue, broadcast delivery of one message to every
        registered consumer, round-robin dispatch for non-broadcast multi-
        consumer queues, and sync-registered queues are never consumed by the
        async path.  No host invocation of guest callbacks is performed and the
        completion guard never inspects, writes or frees the message buffer.
        """
        policy = getattr(self, 'pool_options_policy', '')
        _, params = struct.unpack('<II', reader(arg, 8))
        previous_cb, previous_user, previous_msg, index = struct.unpack('<4I', reader(params, 16))
        if index >= 4:
            return -22
        if tid is None:
            raise UnsupportedUipc('uipc_proxy_thread_identity_required')
        owners = getattr(self, 'callback_proxy_owners', {})
        if index in owners and owners[index] != tid:
            return -22
        owners[index] = tid
        self.callback_proxy_owners = owners
        inflight = getattr(self, 'callback_inflight', {})
        if index in inflight:
            previous = inflight[index]
            if policy not in ('kernel-e0301', KERNEL_E0303):
                raise UnsupportedUipc('uipc_callback_completion_not_implemented',
                                      proxy=index, previous=previous)
            registered = self.callbacks.get(previous['handle'])
            if (previous.get('mode') == 'kernel_sync'
                    and getattr(self, 'sync_callback_delivery_policy', 'unmodelled') == 'kernel-origin'):
                if (registered is None or registered['flags'] != 1
                        or registered['queue'] != previous['queue']):
                    raise UnsupportedUipc('uipc_sync_callback_completion_mismatch',
                                          proxy=index, previous=previous)
                header = reader(previous['msg_ptr'] - 7, 1)[0]
                writer(previous['msg_ptr'] - 7, bytes([header & 0x7f]))
                self.transactions.append({
                    'type': 'wait_cb_sync_completion', 'proxy': index,
                    'handle': previous['handle'], 'queue': previous['queue'],
                    'msg_ptr': previous['msg_ptr'], 'tid': tid,
                    'header_flags': header})
                del inflight[index]
                self.callback_inflight = inflight
                return 0
            if policy == KERNEL_E0303:
                # Generic completion: original finish_callback decrements the
                # callback activity and redispatches; it neither inspects nor
                # frees the message (the original consumer owns that). The
                # guard rejects identity/queue/registration mismatches so a
                # stale or forged proxy index cannot complete another call.
                if (registered is None or registered['flags'] != 0
                        or registered['queue'] != previous['queue']):
                    raise UnsupportedUipc('uipc_callback_completion_mode_not_implemented',
                                          proxy=index, previous=previous)
                self.transactions.append({'type': 'wait_cb_completion', 'proxy': index,
                                          'message_touched': False,
                                          'broadcast': bool(previous.get('broadcast')),
                                          'handle': previous['handle'],
                                          'queue': previous['queue'],
                                          'msg_ptr': previous['msg_ptr']})
                del inflight[index]
                self.callback_inflight = inflight
            else:
                low_id = previous['queue'] & 0xffff
                if (registered is None or registered['flags'] != 0
                        or registered['queue'] != previous['queue']
                        or 0x4000 <= low_id < 0x6000 or low_id >= 0x7000):
                    raise UnsupportedUipc('uipc_callback_completion_mode_not_implemented',
                                          proxy=index, previous=previous)
                # E0301 finish_callback .text+0x41d4..0x42c4: ordinary queue
                # clears callback activity/queue busy and redispatches. It does
                # not inspect or free the message, which may already be freed.
                self.transactions.append({'type': 'wait_cb_completion', 'proxy': index,
                                          'message_touched': False, **previous})
                del inflight[index]
        if policy == KERNEL_E0303:
            return self._deliver_generic_callback(reader, writer, params, index)
        if getattr(self, 'sync_callback_delivery_policy', 'unmodelled') == 'kernel-origin':
            if reader is None or writer is None:
                raise UnsupportedUipc('uipc_sync_callback_memory_required')
            for handle, cb in self.callbacks.items():
                if cb['flags'] != 1:
                    continue
                messages = self.message_queues.get(cb['queue'], [])
                if not messages:
                    continue
                if any(entry.get('queue') == cb['queue'] for entry in inflight.values()):
                    raise UnsupportedUipc('uipc_sync_callback_already_active', queue=cb['queue'])
                if not cb['callback']:
                    raise UnsupportedUipc('uipc_null_callback', handle=handle)
                msg = messages.pop(0)
                header = reader(msg - 7, 1)[0]
                writer(msg - 7, bytes([header | 0x80]))
                writer(params, struct.pack('<4I', cb['callback'], cb['user_data'], msg, index))
                inflight[index] = {'handle': handle, 'queue': cb['queue'],
                                   'msg_ptr': msg, 'mode': 'kernel_sync'}
                self.callback_inflight = inflight
                self.transactions.append({
                    'type': 'wait_cb_sync_delivery', 'proxy': index,
                    'callback': cb['callback'], 'user_data': cb['user_data'],
                    'handle': handle, 'queue': cb['queue'], 'msg_ptr': msg,
                    'tid': tid, 'mode': 'kernel_sync'})
                return 0
        for handle, cb in self.callbacks.items():
            if getattr(self, 'pool_options_policy', '') == 'kernel-e0301':
                # Async list is queue+8; sync registration lives at queue+24.
                if cb['flags'] != 0:
                    continue
                if any(entry['queue'] == cb['queue'] for entry in inflight.values()):
                    continue
            messages = self.message_queues.get(cb['queue'], [])
            if not messages:
                continue
            count = sum(other['queue'] == cb['queue'] and
                        (getattr(self, 'pool_options_policy', '') != 'kernel-e0301' or other['flags'] == 0)
                        for other in self.callbacks.values())
            if count != 1:
                raise UnsupportedUipc('uipc_multiple_callbacks_not_implemented', queue=cb['queue'])
            low_id = cb['queue'] & 0xffff
            if (getattr(self, 'pool_options_policy', '') == 'kernel-e0301'
                    and (0x4000 <= low_id < 0x6000 or low_id >= 0x7000)):
                raise UnsupportedUipc('uipc_callback_queue_mode_not_implemented', queue=cb['queue'])
            if cb['flags'] != 0:
                raise UnsupportedUipc('uipc_sync_callback_not_implemented', handle=handle,
                                      queue=cb['queue'], flags=cb['flags'])
            if not cb['callback']:
                raise UnsupportedUipc('uipc_null_callback', handle=handle)
            msg = messages[0]
            writer(params, struct.pack('<4I', cb['callback'], cb['user_data'], msg, index))
            messages.pop(0)
            inflight[index] = {'handle': handle, 'queue': cb['queue'], 'msg_ptr': msg}
            self.callback_inflight = inflight
            self.transactions.append({'type': 'wait_cb_delivery', 'proxy': index,
                                      'callback': cb['callback'], 'user_data': cb['user_data'],
                                      **inflight[index]})
            return 0
        return None

    def _deliver_generic_callback(self, reader, writer, params, index):
        """E0303 delivery rules layered on the original E0301 evidence.

        Implemented (bounded on the retained finish_callback/dynamic-ID ARM
        controls): ordinary queues keep one owner per message (round-robin among
        registered async consumers); broadcast queues (dynamic slot
        0x7000..0x7fff) deliver the same message to every registered async
        consumer once; a queue is serialized across proxies while a callback is
        inflight; delivery writes only the original four-word tuple and never
        reads, writes or frees the message buffer; sync-registered callbacks are
        never consumed here. Remaining UNKNOWN: the kernel's exact consumer
        selection order and broadcast refcount/free timing are not observed, so
        the message is only removed from the model queue after every registered
        consumer has been handed it (no double-free is possible because the
        completion path never touches the message).
        """
        inflight = getattr(self, 'callback_inflight', {})
        busy = {entry['queue'] for entry in inflight.values()}
        by_queue: Dict[int, List[Tuple[int, Dict[str, object]]]] = {}
        for handle, cb in self.callbacks.items():
            if cb['flags'] != 0:
                continue
            by_queue.setdefault(cb['queue'], []).append((handle, cb))
        for queue, entries in by_queue.items():
            if queue in busy:
                continue
            messages = self.message_queues.get(queue)
            if not messages:
                continue
            low_id = queue & 0xffff
            broadcast = BROADCAST_QUEUE_RANGE[0] <= low_id < BROADCAST_QUEUE_RANGE[1]
            msg = messages[0]
            if broadcast:
                delivered = self.broadcast_message_deliveries.setdefault((queue, msg), set())
                entry = next(((handle, cb) for handle, cb in entries if handle not in delivered),
                             None)
                if entry is None:
                    # All registered consumers already received this message;
                    # consume it from the model queue without touching it.
                    messages.pop(0)
                    self.broadcast_message_deliveries.pop((queue, msg), None)
                    continue
                handle, cb = entry
            else:
                cursor = self.queue_consumer_cursor.get(queue, 0) % len(entries)
                handle, cb = entries[cursor]
                self.queue_consumer_cursor[queue] = (cursor + 1) % len(entries)
            if not cb['callback']:
                raise UnsupportedUipc('uipc_null_callback', handle=handle, queue=queue)
            writer(params, struct.pack('<4I', cb['callback'], cb['user_data'], msg, index))
            if broadcast:
                delivered.add(handle)
                consumer_handles = {consumer for consumer, _cb in entries}
                if consumer_handles <= delivered:
                    messages.pop(0)
                    self.broadcast_message_deliveries.pop((queue, msg), None)
            else:
                messages.pop(0)
            inflight[index] = {'handle': handle, 'queue': queue, 'msg_ptr': msg,
                               'broadcast': broadcast}
            self.callback_inflight = inflight
            self.transactions.append({'type': 'wait_cb_delivery', 'proxy': index,
                                      'callback': cb['callback'], 'user_data': cb['user_data'],
                                      'broadcast': broadcast, **inflight[index]})
            return 0
        return None
