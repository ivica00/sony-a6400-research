"""Partial /dev/uipc transport model; recipient services are separate contracts."""

import struct
from typing import Dict, List, Optional, Tuple

# Linux ARM ioctl commands recognized by osal_uipc.ko
UIPC_CMD_STAT_SEM = 0x80000000
UIPC_CMD_WAI_SEM_TMO = 0x80000001
UIPC_CMD_SIG_SEM = 0x80000002
UIPC_CMD_STAT_MSGQ = 0x80000003
UIPC_CMD_SND_MSG = 0x80000004
UIPC_CMD_SND_SYNC_MSG = 0x80000005
UIPC_CMD_SND_SYNC_DIRECT = 0x80000006
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

    def __init__(self,
                 total_pool_size: int = DEFAULT_TOTAL_POOL_SIZE,
                 vpool_size: int = DEFAULT_VPOOL_SIZE,
                 fblock_size: int = DEFAULT_FBLOCK_SIZE,
                 backup_service_policy: str = 'stop',
                 backup_service: Optional[object] = None,
                 graphics_service_policy: str = 'stop',
                 grm_service: Optional[object] = None,
                 media_service_policy: str = 'stop',
                 media_service: Optional[object] = None):
        if backup_service_policy not in ('stop', 'unverified-ack', 'preset-backed'):
            raise ValueError('Unknown backup service policy')
        if graphics_service_policy not in ('stop', 'authentic-grm'):
            raise ValueError('Unknown graphics service policy')
        if media_service_policy not in ('stop', 'authentic-sd'):
            raise ValueError('Unknown media service policy')
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
        self.transactions: List[Dict[str, object]] = []

    def handle_connect(self, memory_reader, memory_writer, arg_ptr: int) -> int:
        """Handles ioctl 0x80000010 (__k_4u_connect).
        
        arg_ptr points to struct { uint32_t cmd; void *buf; }.
        Kernel writes pool dimensions [total_pool_size, vpool_size, fblock_size, reserved].
        """
        raw_arg = memory_reader(arg_ptr, 8)
        _, buf_ptr = struct.unpack('<II', raw_arg)
        pool_info = struct.pack('<4I', self.total_pool_size, self.vpool_size, self.fblock_size, 0)
        memory_writer(buf_ptr, pool_info)
        self.connected = True
        self.transactions.append({'type': 'connect', 'total_pool': self.total_pool_size, 'buf_ptr': buf_ptr})
        return 0

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

        if self.next_offset + alloc_size > self.total_pool_size:
            return -12 # ENOMEM

        raw_addr = self.pool_base + self.next_offset
        self.next_offset += alloc_size

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

    def handle_snd_sync_msg(self, memory_reader, arg_ptr: int, memory_writer=None) -> int:
        """Handles ioctl 0x80000005 (__k_4u_snd_sync_msg).
        
        arg_ptr points to struct { uint32_t target_queue; void *params; }.
        params points to struct { void *msg_ptr; uint32_t tmo; uint32_t flag; }.
        """
        raw_arg = memory_reader(arg_ptr, 8)
        target_queue, params_ptr = struct.unpack('<II', raw_arg)
        raw_params = memory_reader(params_ptr, 12)
        msg_ptr, tmo, flag = struct.unpack('<III', raw_params)

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
            del self.allocated_msgs[msg_ptr]
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

        handle_id = 0x1000 + len(self.callbacks)
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
        return 0

    def handle_snd_sync_direct(self, memory_reader, arg_ptr: int) -> int:
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
        return 0

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
        if self.next_offset + alloc_size > self.total_pool_size:
            raise MemoryError("UIPC shared pool exhausted")
        raw_addr = self.pool_base + self.next_offset
        self.next_offset += alloc_size
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
        if msgs:
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

    def handle_ioctl(self, memory_reader, memory_writer, cmd: int, arg: int) -> Optional[int]:
        """Dispatches supported UIPC ioctl commands."""
        if cmd == UIPC_CMD_CONNECT:
            return self.handle_connect(memory_reader, memory_writer, arg)
        elif cmd == UIPC_CMD_VALLOC_MSG_WAIT:
            return self.handle_valloc_msg_wait(memory_reader, memory_writer, arg)
        elif cmd == UIPC_CMD_SND_SYNC_MSG:
            return self.handle_snd_sync_msg(memory_reader, arg, memory_writer=memory_writer)
        elif cmd == UIPC_CMD_SND_MSG:
            return self.handle_snd_msg(memory_reader, arg, memory_writer=memory_writer)
        elif cmd == UIPC_CMD_RCV_MSG_TMO:
            return self.handle_rcv_msg_tmo(memory_reader, memory_writer, arg)
        elif cmd == UIPC_CMD_STAT_MSGQ:
            return self.handle_stat_msgq(memory_reader, memory_writer, arg)
        elif cmd == UIPC_CMD_FREE_MSG:
            return self.handle_free_msg(memory_reader, arg)
        elif cmd == UIPC_CMD_REG_MSG_QUEUE_CB:
            return self.handle_reg_msg_queue_cb(memory_reader, memory_writer, arg)
        elif cmd == UIPC_CMD_SND_SYNC_DIRECT:
            return self.handle_snd_sync_direct(memory_reader, arg)
        elif cmd == UIPC_CMD_WAI_SEM_TMO:
            return self.handle_wai_sem_tmo(memory_reader, memory_writer, arg)
        elif cmd == UIPC_CMD_SIG_SEM:
            return self.handle_sig_sem(memory_reader, memory_writer, arg)
        elif cmd == UIPC_CMD_STAT_SEM:
            return self.handle_stat_sem(memory_reader, memory_writer, arg)
        elif cmd == UIPC_CMD_DYNAMIC_ID:
            return self.handle_dynamic_id(memory_reader, memory_writer, arg)
        return None
