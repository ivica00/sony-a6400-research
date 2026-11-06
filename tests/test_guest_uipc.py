"""Unit tests for verified /dev/uipc character device contract."""

import struct
import unittest
from src.a6400.execution.guest_uipc import (
    GuestUipc,
    UIPC_CMD_CONNECT,
    UIPC_CMD_VALLOC_MSG_WAIT,
    UIPC_CMD_SND_SYNC_MSG,
    UIPC_CMD_FREE_MSG,
    DEFAULT_TOTAL_POOL_SIZE,
    DEFAULT_VPOOL_SIZE,
    DEFAULT_FBLOCK_SIZE,
)


class TestGuestUipc(unittest.TestCase):
    def setUp(self):
        self.memory = {}

    def _reader(self, addr, size):
        data = bytearray()
        for i in range(size):
            data.append(self.memory.get(addr + i, 0))
        return bytes(data)

    def _writer(self, addr, data):
        for i, b in enumerate(data):
            self.memory[addr + i] = b

    def test_default_pool_geometry(self):
        uipc = GuestUipc()
        self.assertEqual(uipc.total_pool_size, DEFAULT_TOTAL_POOL_SIZE)
        self.assertEqual(uipc.vpool_size, DEFAULT_VPOOL_SIZE)
        self.assertEqual(uipc.fblock_size, DEFAULT_FBLOCK_SIZE)
        self.assertFalse(uipc.connected)
        self.assertIsNone(uipc.pool_base)

    def test_handle_connect(self):
        uipc = GuestUipc()
        arg_ptr = 0x1000
        buf_ptr = 0x2000
        self._writer(arg_ptr, struct.pack('<II', 0x10, buf_ptr))

        ret = uipc.handle_ioctl(self._reader, self._writer, UIPC_CMD_CONNECT, arg_ptr)
        self.assertEqual(ret, 0)
        self.assertTrue(uipc.connected)

        # Check written pool info: total_pool, vpool, fblock, reserved
        total, vpool, fblock, rsvd = struct.unpack('<4I', self._reader(buf_ptr, 16))
        self.assertEqual(total, DEFAULT_TOTAL_POOL_SIZE)
        self.assertEqual(vpool, DEFAULT_VPOOL_SIZE)
        self.assertEqual(fblock, DEFAULT_FBLOCK_SIZE)
        self.assertEqual(rsvd, 0)

    def test_valloc_before_mmap_fails(self):
        uipc = GuestUipc()
        arg_ptr = 0x1000
        params_ptr = 0x2000
        out_ptr = 0x3000
        self._writer(arg_ptr, struct.pack('<II', 0x8f013a, params_ptr))
        self._writer(params_ptr, struct.pack('<III', out_ptr, 64, 1))

        ret = uipc.handle_ioctl(self._reader, self._writer, UIPC_CMD_VALLOC_MSG_WAIT, arg_ptr)
        self.assertEqual(ret, -14)

    def test_valloc_and_free_lifecycle(self):
        uipc = GuestUipc()
        uipc.pool_base = 0x50330000

        arg_ptr = 0x1000
        params_ptr = 0x2000
        out_ptr = 0x3000
        self._writer(arg_ptr, struct.pack('<II', 0x8f013a, params_ptr))
        self._writer(params_ptr, struct.pack('<III', out_ptr, 52, 1))

        ret = uipc.handle_ioctl(self._reader, self._writer, UIPC_CMD_VALLOC_MSG_WAIT, arg_ptr)
        self.assertEqual(ret, 0)

        # Dest pointer receives user address inside pool (offset by 12-byte authentic OSAL header)
        msg_addr = struct.unpack('<I', self._reader(out_ptr, 4))[0]
        self.assertEqual(msg_addr, 0x5033002c)
        self.assertIn(msg_addr, uipc.allocated_msgs)

        # Verify authentic Sony OSAL header preceding msg_addr
        raw_header = self._reader(msg_addr - 12, 12)
        _, num_blocks, flags, ref_count, magic = struct.unpack('<IBBHI', raw_header)
        self.assertEqual(flags, 1)
        self.assertEqual(ref_count, 1)
        self.assertEqual(magic, 0xa5a5a5a5)
        # For size 52: alloc_size = (52 + 43) & ~31 = 96, num_blocks = 96 >> 5 = 3
        self.assertEqual(num_blocks, 2)

        # Write message body
        msg_body = b'\t\x00  94 B  Ib 094_main()\x00'
        self._writer(msg_addr, msg_body)

        # Send sync message
        snd_arg = 0x1100
        snd_params = 0x2100
        self._writer(snd_arg, struct.pack('<II', 0x8f013a, snd_params))
        self._writer(snd_params, struct.pack('<III', msg_addr, 0, 0))

        ret = uipc.handle_ioctl(self._reader, self._writer, UIPC_CMD_SND_SYNC_MSG, snd_arg)
        self.assertEqual(ret, 0)
        self.assertEqual(len(uipc.transactions), 2)
        self.assertEqual(uipc.transactions[-1]['type'], 'snd_sync_msg')
        self.assertIn('Ib 094_main()', uipc.transactions[-1]['preview_ascii'])

        # Free message
        free_arg = 0x1200
        self._writer(free_arg, struct.pack('<II', 0x8f013a, msg_addr))
        ret = uipc.handle_ioctl(self._reader, self._writer, UIPC_CMD_FREE_MSG, free_arg)
        self.assertEqual(ret, 0)
        self.assertNotIn(msg_addr, uipc.allocated_msgs)

    def test_reg_msg_queue_cb(self):
        uipc = GuestUipc()
        from src.a6400.execution.guest_uipc import UIPC_CMD_REG_MSG_QUEUE_CB
        arg_ptr = 0x1000
        params_ptr = 0x2000
        out_handle_ptr = 0x3000
        queue = 0x94016a
        cb_addr = 0x9635
        user_data = 0x3e8
        flags = 1

        self._writer(arg_ptr, struct.pack('<II', queue, params_ptr))
        self._writer(params_ptr, struct.pack('<IIII', out_handle_ptr, cb_addr, user_data, flags))

        ret = uipc.handle_ioctl(self._reader, self._writer, UIPC_CMD_REG_MSG_QUEUE_CB, arg_ptr)
        self.assertEqual(ret, 0)

        handle = struct.unpack('<I', self._reader(out_handle_ptr, 4))[0]
        self.assertEqual(handle, 0x1000)
        self.assertIn(handle, uipc.callbacks)
        self.assertEqual(uipc.callbacks[handle]['queue'], queue)
        self.assertEqual(uipc.callbacks[handle]['callback'], cb_addr)

    def test_snd_sync_direct(self):
        uipc = GuestUipc()
        from src.a6400.execution.guest_uipc import UIPC_CMD_SND_SYNC_DIRECT
        arg_ptr = 0x1000
        buf_ptr = 0x2000
        queue = 0x920277
        payload = b'\x14\x01\x92\x00j\x01\x94\x00\x00\x00\x00\x00\x00\x00\x00\x00'
        header = struct.pack('<4I', 16 + len(payload), 0, 0, 0)

        self._writer(arg_ptr, struct.pack('<II', queue, buf_ptr))
        self._writer(buf_ptr, header + payload)

        ret = uipc.handle_ioctl(self._reader, self._writer, UIPC_CMD_SND_SYNC_DIRECT, arg_ptr)
        self.assertEqual(ret, 0)
        self.assertEqual(len(uipc.transactions), 1)
        self.assertEqual(uipc.transactions[0]['type'], 'snd_sync_direct')
        self.assertEqual(uipc.transactions[0]['queue'], queue)
        self.assertEqual(uipc.transactions[0]['total_size'], 32)
        self.assertEqual(uipc.transactions[0]['payload_hex'], payload.hex())

    def test_unhandled_ioctl(self):
        uipc = GuestUipc()
        ret = uipc.handle_ioctl(self._reader, self._writer, 0x12345678, 0x1000)
        self.assertIsNone(ret)

    def test_semaphore_wait_and_signal(self):
        from src.a6400.execution.guest_uipc import UIPC_CMD_WAI_SEM_TMO, UIPC_CMD_SIG_SEM
        uipc = GuestUipc()
        sem_id = 0x83037a
        arg_ptr = 0x1000

        # Wait on initially free semaphore
        self._writer(arg_ptr, struct.pack('<II', sem_id, 0xffffffff))
        ret = uipc.handle_ioctl(self._reader, self._writer, UIPC_CMD_WAI_SEM_TMO, arg_ptr)
        self.assertEqual(ret, 0)
        self.assertTrue(uipc.semaphores[sem_id]['locked'])

        # Signal semaphore
        self._writer(arg_ptr, struct.pack('<II', sem_id, 0))
        ret = uipc.handle_ioctl(self._reader, self._writer, UIPC_CMD_SIG_SEM, arg_ptr)
        self.assertEqual(ret, 0)
        self.assertFalse(uipc.semaphores[sem_id]['locked'])

    def test_semaphore_stat(self):
        from src.a6400.execution.guest_uipc import UIPC_CMD_STAT_SEM, UIPC_CMD_WAI_SEM_TMO
        uipc = GuestUipc()
        sem_id = 0x83037a
        arg_ptr = 0x1000
        out_stat = 0x2000

        # Acquire semaphore
        self._writer(arg_ptr, struct.pack('<II', sem_id, 0xffffffff))
        uipc.handle_ioctl(self._reader, self._writer, UIPC_CMD_WAI_SEM_TMO, arg_ptr)

        # Query status
        self._writer(arg_ptr, struct.pack('<II', sem_id, out_stat))
        ret = uipc.handle_ioctl(self._reader, self._writer, UIPC_CMD_STAT_SEM, arg_ptr)
        self.assertEqual(ret, 0)
        state, owner, waiters = struct.unpack('<III', self._reader(out_stat, 12))
        self.assertEqual(state, 1)
        self.assertEqual(owner, 1000)
        self.assertEqual(waiters, 0)

    def test_message_queue_send_and_receive(self):
        from src.a6400.execution.guest_uipc import UIPC_CMD_SND_MSG, UIPC_CMD_RCV_MSG_TMO
        uipc = GuestUipc()
        queue = 0x0094016a
        msg_addr = 0x50330970
        arg_ptr = 0x1000
        out_ptr = 0x2000

        # Send message
        self._writer(arg_ptr, struct.pack('<II', queue, msg_addr))
        ret = uipc.handle_ioctl(self._reader, self._writer, UIPC_CMD_SND_MSG, arg_ptr)
        self.assertEqual(ret, 0)
        self.assertEqual(len(uipc.message_queues[queue]), 1)

        # Receive message
        self._writer(arg_ptr, struct.pack('<IIII', queue, out_ptr, 0, 0xffffffff))
        ret = uipc.handle_ioctl(self._reader, self._writer, UIPC_CMD_RCV_MSG_TMO, arg_ptr)
        self.assertEqual(ret, 0)
        rcv_msg = struct.unpack('<I', self._reader(out_ptr, 4))[0]
        self.assertEqual(rcv_msg, msg_addr)
        self.assertEqual(len(uipc.message_queues[queue]), 0)

    def test_message_queue_empty_receive_returns_eagain(self):
        from src.a6400.execution.guest_uipc import UIPC_CMD_RCV_MSG_TMO
        uipc = GuestUipc()
        queue = 0x0094016a
        arg_ptr = 0x1000

        self._writer(arg_ptr, struct.pack('<IIII', queue, 0x2000, 0, 0))
        ret = uipc.handle_ioctl(self._reader, self._writer, UIPC_CMD_RCV_MSG_TMO, arg_ptr)
        self.assertEqual(ret, -1022) # OSAL_ERR_TIMEOUT (0xfffffc02)

    def test_message_queue_stat(self):
        from src.a6400.execution.guest_uipc import UIPC_CMD_STAT_MSGQ, UIPC_CMD_SND_MSG
        uipc = GuestUipc()
        queue = 0x0094016a
        arg_ptr = 0x1000
        out_stat = 0x2000

        # Send 2 messages
        self._writer(arg_ptr, struct.pack('<II', queue, 0x5001))
        uipc.handle_ioctl(self._reader, self._writer, UIPC_CMD_SND_MSG, arg_ptr)
        self._writer(arg_ptr, struct.pack('<II', queue, 0x5002))
        uipc.handle_ioctl(self._reader, self._writer, UIPC_CMD_SND_MSG, arg_ptr)

        # Stat
        self._writer(arg_ptr, struct.pack('<II', queue, out_stat))
        ret = uipc.handle_ioctl(self._reader, self._writer, UIPC_CMD_STAT_MSGQ, arg_ptr)
        self.assertEqual(ret, 0)
        count, max_msgs, waiters = struct.unpack('<III', self._reader(out_stat, 12))
        self.assertEqual(count, 2)
        self.assertEqual(max_msgs, 128)

    def test_message_queue_receive_with_out_msg_dest(self):
        from src.a6400.execution.guest_uipc import UIPC_CMD_RCV_MSG_TMO
        uipc = GuestUipc()
        queue = 0x0094016a
        msg_addr = 0x50330100
        uipc.message_queues[queue] = [msg_addr]
        
        arg_ptr = 0x1000
        p_out_msg = 0x1008
        out_msg_dest = 0x2000
        
        # In ABI, word 1 points to word 2, and word 2 contains user destination address
        self._writer(arg_ptr, struct.pack('<IIII', queue, p_out_msg, out_msg_dest, 0))
        ret = uipc.handle_ioctl(self._reader, self._writer, UIPC_CMD_RCV_MSG_TMO, arg_ptr)
        self.assertEqual(ret, 0)
        # Verify message was written to destination out_msg_dest
        rcv_msg = struct.unpack('<I', self._reader(out_msg_dest, 4))[0]
        self.assertEqual(rcv_msg, msg_addr)

    def test_message_queue_allocate_and_enqueue_helpers(self):
        uipc = GuestUipc()
        with self.assertRaises(RuntimeError):
            uipc.allocate_message(64)
            
        uipc.pool_base = 0x50330000
        msg_addr = uipc.allocate_message(48)
        self.assertEqual(msg_addr, 0x5033002c)
        self.assertIn(msg_addr, uipc.allocated_msgs)
        
        queue = 0x0094016a
        uipc.enqueue_message(queue, msg_addr)
        self.assertEqual(uipc.message_queues[queue], [msg_addr])

    def test_dynamic_id_allocation_and_free(self):
        from src.a6400.execution.guest_uipc import UIPC_CMD_DYNAMIC_ID
        uipc = GuestUipc()
        
        # Alloc 1
        arg1 = 0x1000
        out1 = 0x2000
        self._writer(arg1, struct.pack('<III', 0x00, 0x1234, out1))
        ret = uipc.handle_ioctl(self._reader, self._writer, UIPC_CMD_DYNAMIC_ID, arg1)
        self.assertEqual(ret, 0)
        id1 = struct.unpack('<I', self._reader(out1, 4))[0]
        self.assertEqual(id1, 0x80001001)
        self.assertEqual(uipc.dynamic_ids[0x1234], 0x80001001)

        # Alloc 2
        arg2 = 0x1010
        out2 = 0x2004
        self._writer(arg2, struct.pack('<III', 0x10, 0x5678, out2))
        ret = uipc.handle_ioctl(self._reader, self._writer, UIPC_CMD_DYNAMIC_ID, arg2)
        self.assertEqual(ret, 0)
        id2 = struct.unpack('<I', self._reader(out2, 4))[0]
        self.assertEqual(id2, 0x80001002)

        # Free with flag 0x40
        arg_free = 0x1020
        self._writer(arg_free, struct.pack('<III', 0x40, 0x1234, id1))
        ret = uipc.handle_ioctl(self._reader, self._writer, UIPC_CMD_DYNAMIC_ID, arg_free)
        self.assertEqual(ret, 0)
        self.assertEqual(uipc.transactions[-1]['type'], 'dynamic_id_free')

    def test_dynamic_id_indirect_abi(self):
        """Authentic u_osal_dynamic_id ABI with [cmd, params_ptr] writes to params[2]."""
        from src.a6400.execution.guest_uipc import UIPC_CMD_DYNAMIC_ID
        uipc = GuestUipc()

        arg_ptr = 0x1000
        params_ptr = 0x1020
        out_ptr = 0x2000

        # params: type=0, key=0x9999, out_id_ptr=out_ptr
        self._writer(params_ptr, struct.pack('<III', 0x00, 0x9999, out_ptr))
        # arg: cmd=0, params_ptr
        self._writer(arg_ptr, struct.pack('<II', 0x00, params_ptr))

        ret = uipc.handle_ioctl(self._reader, self._writer, UIPC_CMD_DYNAMIC_ID, arg_ptr)
        self.assertEqual(ret, 0)
        dyn_id = struct.unpack('<I', self._reader(out_ptr, 4))[0]
        self.assertEqual(dyn_id, 0x80001001)
        self.assertTrue(uipc.transactions[-1]['indirect'])


if __name__ == '__main__':
    unittest.main()

