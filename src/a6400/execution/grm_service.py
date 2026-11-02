"""Authentic Graphics Resource Manager (GRM-MA) service contract.

Verified against Sony firmware modules /usr/kmod/grm_ma.ko, /usr/kmod/dmm.ko,
userland library /usr/lib/libObj.so, and Evidence records E0044 through E0055.
"""

import struct
from typing import Any, Dict, List, Optional

# Verified queue ID for synchronous GRM-MA requests (ma_init)
GRM_MA_SERVICE_QUEUE = 0x014c0424
DMM_SERVICE_QUEUE = 0x0061003c

# Verified gl_common allocation parameters (E0044, E0045, E0047, E0050)
GRM_POOL_PHYS_BASE = 0x202e0000
GRM_POOL_SIZE = 0x02000000       # 32 MiB
GRM_KERNEL_HANDLE = 0x68a96220    # Captured gl_common kernel object pointer
GRM_DMM_HANDLE = 0x0417          # SearchUnitTypeToHandle(0x280) handle
MA_ERR_NONE = 0                  # MA_ErrNone (0)


class GrmMaService:
    """Services synchronous UIPC requests to GRM-MA (queue 0x014c0424).

    Implements the authentic ma_user_sync_cb dispatch contract:
    - Opcode 1: ma_dmm_open_impl (unit 0x280 / gl_common)
    - Opcode 2: ma_dmm_close_impl
    - Opcode 7: ma_findbyname_impl (lookup gl_common)
    - Opcode 9: ma_malloc_impl (allocate buffer from gl_common pool)
    """

    def __init__(self,
                 phys_base: int = GRM_POOL_PHYS_BASE,
                 pool_size: int = GRM_POOL_SIZE,
                 kernel_handle: int = GRM_KERNEL_HANDLE):
        self.phys_base = phys_base
        self.pool_size = pool_size
        self.kernel_handle = kernel_handle
        self.next_alloc_offset = 0
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

