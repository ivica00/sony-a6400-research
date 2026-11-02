"""Unit tests for authentic Graphics Resource Manager (GRM-MA) service contract."""

import struct
import unittest

from src.a6400.execution.grm_service import (
    GrmMaService,
    GRM_MA_SERVICE_QUEUE,
    DMM_SERVICE_QUEUE,
    GRM_POOL_PHYS_BASE,
    GRM_POOL_SIZE,
    GRM_KERNEL_HANDLE,
    GRM_DMM_HANDLE,
    MA_ERR_NONE,
)
from src.a6400.execution.guest_uipc import (
    GuestUipc,
    UnsupportedUipc,
    UIPC_CMD_SND_SYNC_MSG,
    UIPC_CMD_SND_MSG,
    UIPC_CMD_RCV_MSG_TMO,
)


class TestGrmMaService(unittest.TestCase):
    def setUp(self):
        self.memory = {}

    def _reader(self, addr: int, size: int) -> bytes:
        data = bytearray()
        for i in range(size):
            data.append(self.memory.get(addr + i, 0))
        return bytes(data)

    def _writer(self, addr: int, data: bytes):
        for i, b in enumerate(data):
            self.memory[addr + i] = b

    def test_grm_service_opcode1_open(self):
        """Opcode 1 (ma_dmm_open_impl) returns MA_ErrNone, pool base, size, and handle."""
        service = GrmMaService()
        msg_ptr = 0x1000

        # Authentic trace bytes: opcode 1, unit 0x0280, flag 0, name 'gl_common' at offset 9
        req = bytes.fromhex('010000008002000000676c5f636f6d6d6f6e00')
        req = req.ljust(64, b'\x00')
        self._writer(msg_ptr, req)

        ret = service.handle_uipc_sync_message(self._reader, self._writer, msg_ptr, 64)
        self.assertEqual(ret, 0)

        # Check reply at msg_ptr + 28
        reply = self._reader(msg_ptr + 28, 16)
        status, phys_base, size, handle = struct.unpack('<IIII', reply)
        self.assertEqual(status, MA_ERR_NONE)
        self.assertEqual(phys_base, GRM_POOL_PHYS_BASE)
        self.assertEqual(size, GRM_POOL_SIZE)
        self.assertEqual(handle, GRM_KERNEL_HANDLE)

        # Check event logging
        self.assertEqual(len(service.events), 1)
        self.assertEqual(service.events[0]['action'], 'ma_dmm_open_impl')
        self.assertEqual(service.events[0]['name'], 'gl_common')
        self.assertEqual(service.events[0]['status'], MA_ERR_NONE)

    def test_grm_service_opcode7_lookup(self):
        """Opcode 7 (ma_findbyname_impl) returns MA_ErrNone and gl_common descriptors."""
        service = GrmMaService()
        msg_ptr = 0x2000

        # Construct request: opcode 7, name 'gl_common'
        name_bytes = b'gl_common\x00' + b'\x00' * 6
        req = struct.pack('<HI', 7, 0) + name_bytes
        req = req.ljust(64, b'\x00')
        self._writer(msg_ptr, req)

        ret = service.handle_uipc_sync_message(self._reader, self._writer, msg_ptr, 64)
        self.assertEqual(ret, 0)

        # Check reply at msg_ptr + 20
        reply = self._reader(msg_ptr + 20, 16)
        status, phys_base, size, handle = struct.unpack('<IIII', reply)
        self.assertEqual(status, MA_ERR_NONE)
        self.assertEqual(phys_base, GRM_POOL_PHYS_BASE)
        self.assertEqual(size, GRM_POOL_SIZE)
        self.assertEqual(handle, GRM_KERNEL_HANDLE)

    def test_grm_service_opcode9_alloc(self):
        """Opcode 9 (ma_malloc_impl) returns MA_ErrNone and allocated address inside pool."""
        service = GrmMaService()
        msg_ptr = 0x3000

        # Construct request: opcode 9, handle, size (64 KiB)
        req = struct.pack('<HI', 9, 0) + struct.pack('<II', GRM_KERNEL_HANDLE, 0x10000)
        req = req.ljust(64, b'\x00')
        self._writer(msg_ptr, req)

        ret = service.handle_uipc_sync_message(self._reader, self._writer, msg_ptr, 64)
        self.assertEqual(ret, 0)

        # Check reply at msg_ptr + 16
        reply = self._reader(msg_ptr + 16, 8)
        status, alloc_addr = struct.unpack('<II', reply)
        self.assertEqual(status, MA_ERR_NONE)
        self.assertEqual(alloc_addr, GRM_POOL_PHYS_BASE)

    def test_grm_service_opcode2_close(self):
        """Opcode 2 (ma_dmm_close_impl) returns MA_ErrNone."""
        service = GrmMaService()
        msg_ptr = 0x4000
        req = struct.pack('<HI', 2, 0).ljust(64, b'\x00')
        self._writer(msg_ptr, req)

        ret = service.handle_uipc_sync_message(self._reader, self._writer, msg_ptr, 64)
        self.assertEqual(ret, 0)

        # Check reply status at msg_ptr + 8
        reply = self._reader(msg_ptr + 8, 4)
        status = struct.unpack('<I', reply)[0]
        self.assertEqual(status, MA_ERR_NONE)

    def test_guest_uipc_graphics_policy_stop_fails_closed(self):
        """Default graphics_service_policy='stop' raises UnsupportedUipc on queue 0x014c0424."""
        uipc = GuestUipc(graphics_service_policy='stop')
        arg_ptr = 0x1000
        params_ptr = 0x2000
        msg_ptr = 0x3000

        self._writer(arg_ptr, struct.pack('<II', GRM_MA_SERVICE_QUEUE, params_ptr))
        self._writer(params_ptr, struct.pack('<III', msg_ptr, 0, 0))
        self._writer(msg_ptr, struct.pack('<HI', 1, 0).ljust(32, b'\x00'))

        with self.assertRaises(UnsupportedUipc) as ctx:
            uipc.handle_ioctl(self._reader, self._writer, UIPC_CMD_SND_SYNC_MSG, arg_ptr)
        self.assertEqual(ctx.exception.details['reason'], 'graphics_service_reply_not_supplied')

    def test_guest_uipc_graphics_policy_authentic_grm(self):
        """Policy 'authentic-grm' services GRM-MA requests and records transaction classification."""
        uipc = GuestUipc(graphics_service_policy='authentic-grm')
        arg_ptr = 0x1000
        params_ptr = 0x2000
        msg_ptr = 0x3000

        req = bytes.fromhex('010000008002000000676c5f636f6d6d6f6e00')
        self._writer(arg_ptr, struct.pack('<II', GRM_MA_SERVICE_QUEUE, params_ptr))
        self._writer(params_ptr, struct.pack('<III', msg_ptr, 0, 0))
        self._writer(msg_ptr, req.ljust(64, b'\x00'))

        ret = uipc.handle_ioctl(self._reader, self._writer, UIPC_CMD_SND_SYNC_MSG, arg_ptr)
        self.assertEqual(ret, 0)

        # Check reply
        status, phys_base, size, handle = struct.unpack('<IIII', self._reader(msg_ptr + 28, 16))
        self.assertEqual(status, MA_ERR_NONE)
        self.assertEqual(phys_base, GRM_POOL_PHYS_BASE)

        # Check transaction classification
        self.assertEqual(len(uipc.transactions), 1)
        self.assertIn('authentic-grm verified gl_common pool', uipc.transactions[0]['classification'])

    def test_guest_uipc_dmm_message_completion(self):
        """Asynchronous DMM requests (queue 0x0061003c) receive completion reply with correct source and ret_code."""
        uipc = GuestUipc(graphics_service_policy='authentic-grm')
        uipc.pool_base = 0x50000000

        # Construct request to DMM queue
        req_msg_ptr = uipc.allocate_message(size=32)
        reply_queue = 0x53076980
        req_id = 42
        opcode = 1
        unit = 0x000e1700

        # Authentic layout: opcode (uint16), pad (uint16), unit (uint32), ..., reply_queue at +16, req_id at +20
        req_bytes = struct.pack('<HHI', opcode, 0, unit) + b'\x00' * 8 + struct.pack('<IH', reply_queue, req_id)
        self._writer(req_msg_ptr, req_bytes.ljust(32, b'\x00'))

        arg_ptr = 0x1000
        self._writer(arg_ptr, struct.pack('<II', DMM_SERVICE_QUEUE, req_msg_ptr))

        # Send message via UIPC_CMD_SND_MSG
        ret = uipc.handle_ioctl(self._reader, self._writer, UIPC_CMD_SND_MSG, arg_ptr)
        self.assertEqual(ret, 0)

        # Verify reply was enqueued in reply_queue
        self.assertIn(reply_queue, uipc.message_queues)
        self.assertEqual(len(uipc.message_queues[reply_queue]), 1)
        reply_ptr = uipc.message_queues[reply_queue][0]

        # Verify sender queue ID at reply_ptr - 4 (osal_get_msg_src)
        src_queue = struct.unpack('<I', self._reader(reply_ptr - 4, 4))[0]
        self.assertEqual(src_queue, DMM_SERVICE_QUEUE)

        # Verify reply packet contents:
        # offset 0: opcode, offset 2: ret_code (0), offset 4: handle (0x0417), offset 6: req_id (42)
        # offset 16: phys_base (0x202e0000), offset 20: pool_size (32 MiB)
        reply_raw = self._reader(reply_ptr, 28)
        rep_opcode, ret_code, handle, rep_req_id = struct.unpack_from('<hhHH', reply_raw, 0)
        self.assertEqual(rep_opcode, opcode)
        self.assertEqual(ret_code, 0)
        self.assertEqual(handle, GRM_DMM_HANDLE)
        self.assertEqual(rep_req_id, req_id)
        phys_base_map = struct.unpack_from('<I', reply_raw, 16)[0]
        size_map = struct.unpack_from('<I', reply_raw, 20)[0]
        self.assertEqual(phys_base_map, GRM_POOL_PHYS_BASE)
        self.assertEqual(size_map, GRM_POOL_SIZE)

        # Verify rcv_msg_tmo dequeues the reply and returns 0
        rcv_arg_ptr = 0x1100
        out_msg_dest = 0x1200
        self._writer(rcv_arg_ptr, struct.pack('<IIII', reply_queue, out_msg_dest, 0, 0xFFFFFFFF))
        ret_rcv = uipc.handle_ioctl(self._reader, self._writer, UIPC_CMD_RCV_MSG_TMO, rcv_arg_ptr)
        self.assertEqual(ret_rcv, 0)
        delivered_msg = struct.unpack('<I', self._reader(out_msg_dest, 4))[0]
        self.assertEqual(delivered_msg, reply_ptr)


if __name__ == '__main__':
    unittest.main()
