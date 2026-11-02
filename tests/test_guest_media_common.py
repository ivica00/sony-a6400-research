"""Unit tests for authentic Sony MediaCommonDriver (mcmn_drv.ko) UIPC contract and /setting overlay."""

import struct
import unittest
from src.a6400.execution.guest_media_common import (
    GuestMediaCommon,
    MEDIA_COMMON_DRIVER_QUEUE,
    MEDIA_TYPE_SD,
    MEDIA_TYPE_MS,
)
from src.a6400.execution.guest_uipc import GuestUipc, UnsupportedUipc


class MockUipcPool:
    """Mock shared memory pool for testing UIPC message allocation and queueing."""
    def __init__(self, memory, pool_base=0x20000000):
        self.memory = memory
        self.pool_base = pool_base
        self.next_offset = 0x20
        self.allocated = {}
        self.enqueued = {}

    def allocate_message(self, size: int) -> int:
        alloc_size = (size + 15) & ~15
        addr = self.pool_base + self.next_offset
        self.next_offset += alloc_size
        self.allocated[addr] = alloc_size
        return addr

    def enqueue_message(self, queue: int, msg_addr: int):
        if queue not in self.enqueued:
            self.enqueued[queue] = []
        self.enqueued[queue].append(msg_addr)


class TestGuestMediaCommon(unittest.TestCase):
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

    def test_media_common_sd_presence_reply(self):
        """Verifies authentic category 2 subcmd 1 CheckInsertedMedia response."""
        handler = GuestMediaCommon(media_type=MEDIA_TYPE_SD)
        mock_uipc = MockUipcPool(self.memory)

        # Build request message: category 2, subcmd 1, payload_len 8, reply_queue 0x8000100f, slot 0
        req_ptr = 0x1000
        reply_queue = 0x8000100f
        subcmd_payload = (1) | (8 << 16)
        req_data = struct.pack('<IIIIIIII', 2, subcmd_payload, reply_queue, 0, 0, 0, 0, 0)
        self._writer(req_ptr, req_data)

        record = handler.handle_message(self._reader, self._writer, req_ptr, mock_uipc)
        self.assertIsNotNone(record)
        self.assertEqual(record['status'], 'serviced')
        self.assertEqual(record['media_type'], MEDIA_TYPE_SD)
        self.assertEqual(handler.queries_serviced, 1)

        # Verify reply was enqueued to reply_queue
        self.assertIn(reply_queue, mock_uipc.enqueued)
        reply_ptr = mock_uipc.enqueued[reply_queue][0]

        # Verify reply packet contents
        raw_reply = self._reader(reply_ptr, 32)
        cat, subcmd_len, rq, status, r1, r2, slot, mtype = struct.unpack('<IIIIIIII', raw_reply)
        self.assertEqual(cat, 2)
        self.assertEqual(subcmd_len, subcmd_payload)
        self.assertEqual(rq, reply_queue)
        self.assertEqual(status, 0)  # success
        self.assertEqual(slot, 0)    # slot 0
        self.assertEqual(mtype, 3)   # SD card!

    def test_uipc_media_service_stop_policy(self):
        """Verifies fail-closed behavior when media_service_policy is stop."""
        uipc = GuestUipc(media_service_policy='stop')
        msg_ptr = 0x1000
        self._writer(msg_ptr, struct.pack('<IIIIIIII', 2, 1 | (8 << 16), 0x8000100f, 0, 0, 0, 0, 0))

        arg_ptr = 0x2000
        self._writer(arg_ptr, struct.pack('<II', MEDIA_COMMON_DRIVER_QUEUE, msg_ptr))

        with self.assertRaises(UnsupportedUipc) as ctx:
            uipc.handle_snd_msg(self._reader, arg_ptr, self._writer)
        self.assertEqual(ctx.exception.details['reason'], 'media_service_reply_not_supplied')

    def test_uipc_media_service_authentic_sd_policy(self):
        """Verifies integration of authentic-sd policy with GuestUipc."""
        uipc = GuestUipc(media_service_policy='authentic-sd')
        uipc.pool_base = 0x20000000

        msg_ptr = 0x1000
        reply_queue = 0x8000100f
        self._writer(msg_ptr, struct.pack('<IIIIIIII', 2, 1 | (8 << 16), reply_queue, 0, 0, 0, 0, 0))

        arg_ptr = 0x2000
        self._writer(arg_ptr, struct.pack('<II', MEDIA_COMMON_DRIVER_QUEUE, msg_ptr))

        ret = uipc.handle_snd_msg(self._reader, arg_ptr, self._writer)
        self.assertEqual(ret, 0)
        self.assertEqual(uipc.media_service.queries_serviced, 1)

        # Check that reply was enqueued
        self.assertIn(reply_queue, uipc.message_queues)
        self.assertEqual(len(uipc.message_queues[reply_queue]), 1)
        reply_ptr = uipc.message_queues[reply_queue][0]

        # Check media type is SD
        reply_data = self._reader(reply_ptr, 32)
        _, _, _, status, _, _, slot, mtype = struct.unpack('<IIIIIIII', reply_data)
        self.assertEqual(status, 0)
        self.assertEqual(slot, 0)
        self.assertEqual(mtype, MEDIA_TYPE_SD)


if __name__ == '__main__':
    unittest.main()
