"""Unit tests for authentic Graphics Resource Manager (GRM-MA) service contract."""

import struct
import unittest

from src.a6400.execution.grm_service import (
    CAPTURED_E0044_POOLS,
    DMM_SERVICE_QUEUE,
    GRM_DMM_HANDLE,
    GRM_KERNEL_HANDLE,
    GRM_MA_SERVICE_QUEUE,
    GRM_POOL_PHYS_BASE,
    GRM_POOL_SIZE,
    GRM_UNIT_GL_COMMON,
    GrmMaService,
    MA_ERR_NONE,
    MA_ERR_NOT_FOUND,
    POOL_POLICY_CAPTURED_E0044,
    POOL_POLICY_GL_COMMON_ONLY,
)
from src.a6400.execution.guest_uipc import (
    GuestUipc,
    UnsupportedUipc,
    UIPC_CMD_SND_SYNC_MSG,
    UIPC_CMD_SND_MSG,
    UIPC_CMD_RCV_MSG_TMO,
)


def _open_request(unit: int, name: str = 'gl_common', flags: int = 0) -> bytes:
    """Opcode 1 request: opcode at +0, unit at +4, flags at +8, name at +9."""
    request = bytearray(64)
    struct.pack_into('<H', request, 0, 1)
    struct.pack_into('<I', request, 4, unit)
    request[8] = flags
    encoded = name.encode('latin1')
    request[9:9 + len(encoded)] = encoded
    return bytes(request)


def _lookup_request(name: str) -> bytes:
    """Opcode 7 request: opcode at +0, name string at +4 (16 bytes)."""
    request = bytearray(64)
    struct.pack_into('<H', request, 0, 7)
    encoded = name.encode('latin1')
    request[4:4 + len(encoded)] = encoded
    return bytes(request)


def _alloc_request(handle: int, size: int) -> bytes:
    """Opcode 9 request: opcode at +0, handle at +4, size at +8."""
    request = bytearray(64)
    struct.pack_into('<H', request, 0, 9)
    struct.pack_into('<II', request, 4, handle, size)
    return bytes(request)


def _close_request() -> bytes:
    request = bytearray(64)
    struct.pack_into('<H', request, 0, 2)
    return bytes(request)


class _WriteRecorder:
    """Memory writer that records every write so framing can be asserted."""

    def __init__(self, memory):
        self.memory = memory
        self.writes = []

    def __call__(self, addr: int, data: bytes):
        data = bytes(data)
        self.writes.append((addr, data))
        for index, value in enumerate(data):
            self.memory[addr + index] = value



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

    def test_default_policy_is_gl_common_only_and_validated(self):
        """Construction without arguments keeps the verified default policy."""
        service = GrmMaService()
        self.assertEqual(service.pool_policy, POOL_POLICY_GL_COMMON_ONLY)
        self.assertEqual(service.phys_base, GRM_POOL_PHYS_BASE)
        self.assertEqual(service.pool_size, GRM_POOL_SIZE)
        self.assertEqual(service.kernel_handle, GRM_KERNEL_HANDLE)
        with self.assertRaises(ValueError):
            GrmMaService(pool_policy='captured-unknown')

    def test_default_policy_unknown_name_still_returns_gl_common(self):
        """The default policy keeps its previous name-agnostic gl_common reply."""
        service = GrmMaService()
        msg_ptr = 0x2100
        self._writer(msg_ptr, _lookup_request('mpTextHeap'))
        service.handle_uipc_sync_message(self._reader, self._writer, msg_ptr, 64)
        reply = struct.unpack('<iIII', self._reader(msg_ptr + 20, 16))
        self.assertEqual(reply, (MA_ERR_NONE, GRM_POOL_PHYS_BASE, GRM_POOL_SIZE, GRM_KERNEL_HANDLE))

    def test_default_policy_allocations_stay_byte_identical(self):
        """Default allocation offset accounting is unchanged (one global offset)."""
        service = GrmMaService()
        first = 0x3100
        second = 0x3200
        self._writer(first, _alloc_request(GRM_KERNEL_HANDLE, 0x1000))
        service.handle_uipc_sync_message(self._reader, self._writer, first, 64)
        self.assertEqual(struct.unpack('<iI', self._reader(first + 16, 8)),
                         (MA_ERR_NONE, GRM_POOL_PHYS_BASE))
        self._writer(second, _alloc_request(GRM_KERNEL_HANDLE, 0x2000))
        service.handle_uipc_sync_message(self._reader, self._writer, second, 64)
        self.assertEqual(struct.unpack('<iI', self._reader(second + 16, 8)),
                         (MA_ERR_NONE, GRM_POOL_PHYS_BASE + 0x1000))
        self.assertEqual(service.next_alloc_offset, 0x3000)

    def test_default_policy_reply_bytes_unchanged(self):
        """Open/lookup replies keep their verified byte layout and values."""
        service = GrmMaService()
        open_ptr = 0x4100
        self._writer(open_ptr, bytes.fromhex('010000008002000000676c5f636f6d6d6f6e00').ljust(64, b'\x00'))
        service.handle_uipc_sync_message(self._reader, self._writer, open_ptr, 64)
        self.assertEqual(self._reader(open_ptr + 28, 16),
                         struct.pack('<IIII', MA_ERR_NONE, GRM_POOL_PHYS_BASE, GRM_POOL_SIZE, GRM_KERNEL_HANDLE))

        lookup_ptr = 0x4200
        self._writer(lookup_ptr, _lookup_request('gl_common'))
        service.handle_uipc_sync_message(self._reader, self._writer, lookup_ptr, 64)
        self.assertEqual(self._reader(lookup_ptr + 20, 16),
                         struct.pack('<IIII', MA_ERR_NONE, GRM_POOL_PHYS_BASE, GRM_POOL_SIZE, GRM_KERNEL_HANDLE))

    def test_constructor_custom_gl_common_parameters_still_supported(self):
        """Backward-compatible constructor parameters still drive the default policy."""
        service = GrmMaService(phys_base=0x40000000, pool_size=0x1000, kernel_handle=0x12345678)
        msg_ptr = 0x5100
        self._writer(msg_ptr, _open_request(GRM_UNIT_GL_COMMON))
        service.handle_uipc_sync_message(self._reader, self._writer, msg_ptr, 64)
        self.assertEqual(struct.unpack('<iIII', self._reader(msg_ptr + 28, 16)),
                         (MA_ERR_NONE, 0x40000000, 0x1000, 0x12345678))

    def test_captured_policy_rejects_custom_gl_common_parameters(self):
        """captured-e0044 must not silently mix table rows with custom values."""
        with self.assertRaises(ValueError):
            GrmMaService(phys_base=0x40000000, pool_policy=POOL_POLICY_CAPTURED_E0044)

    def test_no_writes_outside_sync_message_buffer(self):
        """Every reply write stays inside the 64-byte synchronous message."""
        service = GrmMaService()
        msg_ptr = 0x6000
        for address in range(msg_ptr - 16, msg_ptr):
            self.memory[address] = 0xAA
        for address in range(msg_ptr + 64, msg_ptr + 80):
            self.memory[address] = 0xAA

        requests = [
            _open_request(GRM_UNIT_GL_COMMON),
            _lookup_request('gl_common'),
            _alloc_request(GRM_KERNEL_HANDLE, 0x1000),
            _close_request(),
        ]
        for request in requests:
            self._writer(msg_ptr, request)
            recorder = _WriteRecorder(self.memory)
            self.assertEqual(service.handle_uipc_sync_message(self._reader, recorder, msg_ptr, 64), 0)
            for address, data in recorder.writes:
                self.assertGreaterEqual(address, msg_ptr)
                self.assertLessEqual(address + len(data), msg_ptr + 64)
        for address in range(msg_ptr - 16, msg_ptr):
            self.assertEqual(self.memory[address], 0xAA)
        for address in range(msg_ptr + 64, msg_ptr + 80):
            self.assertEqual(self.memory[address], 0xAA)

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


class TestGrmMaCapturedE0044Policy(unittest.TestCase):
    """Opt-in captured E0044 pool policy (six captured allocator objects)."""

    def setUp(self):
        self.memory = {}
        self.msg_ptr = 0x5000
        self.service = GrmMaService(pool_policy=POOL_POLICY_CAPTURED_E0044)

    def _reader(self, addr: int, size: int) -> bytes:
        return bytes(self.memory.get(addr + i, 0) for i in range(size))

    def _writer(self, addr: int, data: bytes):
        for i, b in enumerate(data):
            self.memory[addr + i] = b

    def _send(self, request: bytes):
        self._writer(self.msg_ptr, request)
        return self.service.handle_uipc_sync_message(self._reader, self._writer, self.msg_ptr, 64)

    def _open_reply(self):
        return struct.unpack('<iIII', self._reader(self.msg_ptr + 28, 16))

    def _lookup_reply(self):
        return struct.unpack('<iIII', self._reader(self.msg_ptr + 20, 16))

    def _alloc_reply(self):
        return struct.unpack('<iI', self._reader(self.msg_ptr + 16, 8))

    def _lookup(self, name: str):
        self._send(_lookup_request(name))
        return self._lookup_reply()

    def test_pool_table_matches_captured_e0044_report(self):
        """The table and handles are exactly the E0044 captured values."""
        expected = [
            ('empty', 0x00B7F2A0, 0x23B16000, 0x96000),
            ('mpMemoryHeap2', 0x08ABD560, 0x226E0000, 0x1A0000),
            ('mpTextHeap', 0x08ABD5A0, 0x22880000, 0x200000),
            ('mpMemoryHeap', 0x00B7F2E0, 0x222E0000, 0x400000),
            ('empty', 0x00B7F360, 0x23A80000, 0x96000),
            ('gl_common', 0x08A96220, 0x202E0000, 0x02000000),
        ]
        self.assertEqual([tuple(pool) for pool in CAPTURED_E0044_POOLS], expected)
        for pool in CAPTURED_E0044_POOLS:
            # E0044 link conversion: cached kernel pointer = physical + 0x60000000.
            self.assertEqual(pool.kernel_handle, pool.object_physical + 0x60000000)
        gl_common = next(pool for pool in CAPTURED_E0044_POOLS if pool.name == 'gl_common')
        self.assertEqual(gl_common.kernel_handle, GRM_KERNEL_HANDLE)

    def test_open_unit_0280_returns_gl_common_row(self):
        self.assertEqual(self._send(_open_request(GRM_UNIT_GL_COMMON)), 0)
        self.assertEqual(self._open_reply(),
                         (MA_ERR_NONE, 0x202E0000, 0x02000000, 0x68A96220))
        event = self.service.events[-1]
        self.assertEqual(event['action'], 'ma_dmm_open_impl')
        self.assertEqual(event['status'], MA_ERR_NONE)
        self.assertEqual(event['unit'], '0x0280')
        self.assertEqual(event['pool_name'], 'gl_common')

    def test_open_uses_unit_not_name_per_e0046(self):
        """E0046: the original open contains no name lookup; unit 0x280 wins."""
        self.assertEqual(self._send(_open_request(GRM_UNIT_GL_COMMON, 'mpTextHeap')), 0)
        self.assertEqual(self._open_reply(),
                         (MA_ERR_NONE, 0x202E0000, 0x02000000, 0x68A96220))
        self.assertEqual(self.service.events[-1]['name'], 'mpTextHeap')

    def test_open_unknown_unit_fails_explicitly(self):
        self.assertEqual(self._send(_open_request(0x0281)), 0)
        self.assertEqual(self._open_reply(), (MA_ERR_NOT_FOUND, 0, 0, 0))
        event = self.service.events[-1]
        self.assertEqual(event['action'], 'ma_dmm_open_impl_unsupported_unit')
        self.assertEqual(event['status'], MA_ERR_NOT_FOUND)
        self.assertNotIn('phys_base', event)

    def test_lookup_matches_each_captured_pool_name(self):
        first_by_name = {}
        for pool in CAPTURED_E0044_POOLS:
            first_by_name.setdefault(pool.name, pool)
        self.assertEqual(len(first_by_name), 5)  # 'empty' appears twice
        for name, pool in first_by_name.items():
            with self.subTest(name=name):
                self.assertEqual(self._send(_lookup_request(name)), 0)
                self.assertEqual(self._lookup_reply(),
                                 (MA_ERR_NONE, pool.phys_base, pool.pool_size, pool.kernel_handle))
                event = self.service.events[-1]
                self.assertEqual(event['action'], 'ma_findbyname_impl')
                self.assertEqual(event['pool_name'], name)

    def test_lookup_duplicate_empty_uses_first_captured_node(self):
        """ma_list_findbyname traversal returns the first matching list node."""
        self.assertEqual(self._lookup('empty'),
                         (MA_ERR_NONE, 0x23B16000, 0x96000, 0x60B7F2A0))

    def test_lookup_unknown_name_fails_explicitly(self):
        self.assertEqual(self._send(_lookup_request('absent_control')), 0)
        self.assertEqual(self._lookup_reply(), (MA_ERR_NOT_FOUND, 0, 0, 0))
        event = self.service.events[-1]
        self.assertEqual(event['action'], 'ma_findbyname_impl_unknown_name')
        self.assertEqual(event['status'], MA_ERR_NOT_FOUND)
        self.assertNotIn('phys_base', event)

    def test_unknown_handle_fails_explicitly_without_consuming_pool(self):
        self.assertEqual(self._send(_alloc_request(0xDEADBEEF, 0x1000)), 0)
        self.assertEqual(self._alloc_reply(), (MA_ERR_NOT_FOUND, 0))
        event = self.service.events[-1]
        self.assertEqual(event['action'], 'ma_malloc_impl_unknown_handle')
        self.assertEqual(event['status'], MA_ERR_NOT_FOUND)

        # The failed request must not consume gl_common's allocation offset.
        self.assertEqual(self._send(_alloc_request(GRM_KERNEL_HANDLE, 0x1000)), 0)
        self.assertEqual(self._alloc_reply(), (MA_ERR_NONE, 0x202E0000))

    def test_allocations_from_different_pools_stay_in_their_ranges(self):
        text = self._lookup('mpTextHeap')
        heap2 = self._lookup('mpMemoryHeap2')
        self.assertEqual(text, (MA_ERR_NONE, 0x22880000, 0x200000, 0x68ABD5A0))
        self.assertEqual(heap2, (MA_ERR_NONE, 0x226E0000, 0x1A0000, 0x68ABD560))

        pools = {
            text[3]: (text[1], text[2]),
            heap2[3]: (heap2[1], heap2[2]),
            GRM_KERNEL_HANDLE: (0x202E0000, 0x02000000),
        }
        allocations = [
            (text[3], 0x1000, 0x22880000),
            (heap2[3], 0x2000, 0x226E0000),
            (GRM_KERNEL_HANDLE, 0x2000, 0x202E0000),
            (text[3], 0x1000, 0x22881000),
            (heap2[3], 0x1000, 0x226E2000),
            (GRM_KERNEL_HANDLE, 0x1000, 0x202E2000),
        ]
        for handle, size, expected_addr in allocations:
            with self.subTest(handle=f'0x{handle:08x}', size=size):
                self.assertEqual(self._send(_alloc_request(handle, size)), 0)
                status, alloc_addr = self._alloc_reply()
                self.assertEqual(status, MA_ERR_NONE)
                self.assertEqual(alloc_addr, expected_addr)
                base, pool_size = pools[handle]
                self.assertGreaterEqual(alloc_addr, base)
                self.assertLess(alloc_addr + size, base + pool_size)
                self.assertEqual(self.service.events[-1]['pool_name'],
                                 next(pool.name for pool in CAPTURED_E0044_POOLS
                                      if pool.kernel_handle == handle))

    def test_allocation_offsets_are_aligned_per_pool(self):
        self.assertEqual(self._lookup('mpTextHeap')[0], MA_ERR_NONE)
        for size, expected_addr in ((0x0001, 0x22880000),
                                    (0x1001, 0x22881000),
                                    (0x1000, 0x22883000)):
            with self.subTest(size=size):
                self.assertEqual(self._send(_alloc_request(0x68ABD5A0, size)), 0)
                self.assertEqual(self._alloc_reply(), (MA_ERR_NONE, expected_addr))

    def test_captured_policy_through_guest_uipc(self):
        """The Lead can pass a captured-e0044 service instance to GuestUipc."""
        service = GrmMaService(pool_policy=POOL_POLICY_CAPTURED_E0044)
        uipc = GuestUipc(graphics_service_policy='authentic-grm', grm_service=service)
        arg_ptr, params_ptr, msg_ptr = 0x1000, 0x2000, 0x3000

        def send(request: bytes):
            self._writer(arg_ptr, struct.pack('<II', GRM_MA_SERVICE_QUEUE, params_ptr))
            self._writer(params_ptr, struct.pack('<III', msg_ptr, 0, 0))
            self._writer(msg_ptr, request)
            self.assertEqual(uipc.handle_ioctl(self._reader, self._writer, UIPC_CMD_SND_SYNC_MSG, arg_ptr), 0)

        send(_open_request(GRM_UNIT_GL_COMMON))
        self.assertEqual(struct.unpack('<iIII', self._reader(msg_ptr + 28, 16)),
                         (MA_ERR_NONE, 0x202E0000, 0x02000000, 0x68A96220))

        send(_lookup_request('mpTextHeap'))
        self.assertEqual(struct.unpack('<iIII', self._reader(msg_ptr + 20, 16)),
                         (MA_ERR_NONE, 0x22880000, 0x200000, 0x68ABD5A0))

        send(_alloc_request(0x68ABD5A0, 0x1000))
        self.assertEqual(struct.unpack('<iI', self._reader(msg_ptr + 16, 8)),
                         (MA_ERR_NONE, 0x22880000))


class TestGrmMaMessageFraming(unittest.TestCase):
    """Wire framing and bounded writes for both pool policies."""

    def setUp(self):
        self.memory = {}
        self.msg_ptr = 0x8000

    def _reader(self, addr: int, size: int) -> bytes:
        return bytes(self.memory.get(addr + i, 0) for i in range(size))

    def _writer(self, addr: int, data: bytes):
        for i, b in enumerate(data):
            self.memory[addr + i] = b

    def _run(self, service, request: bytes):
        for address in range(self.msg_ptr - 16, self.msg_ptr):
            self.memory[address] = 0xAA
        for address in range(self.msg_ptr + 64, self.msg_ptr + 80):
            self.memory[address] = 0xAA
        self._writer(self.msg_ptr, request)
        recorder = _WriteRecorder(self.memory)
        self.assertEqual(service.handle_uipc_sync_message(self._reader, recorder, self.msg_ptr, 64), 0)
        for address, data in recorder.writes:
            self.assertGreaterEqual(address, self.msg_ptr)
            self.assertLessEqual(address + len(data), self.msg_ptr + 64)
        for address in range(self.msg_ptr - 16, self.msg_ptr):
            self.assertEqual(self.memory[address], 0xAA)
        for address in range(self.msg_ptr + 64, self.msg_ptr + 80):
            self.assertEqual(self.memory[address], 0xAA)
        return [(address - self.msg_ptr, data) for address, data in recorder.writes]

    def test_reply_offsets_unchanged_for_both_policies(self):
        expected = {
            'open': (28, 16),
            'lookup': (20, 16),
            'alloc': (16, 8),
            'close': (8, 4),
        }
        requests = {
            'open': _open_request(GRM_UNIT_GL_COMMON),
            'lookup': _lookup_request('gl_common'),
            'alloc': _alloc_request(GRM_KERNEL_HANDLE, 0x1000),
            'close': _close_request(),
        }
        for policy in (POOL_POLICY_GL_COMMON_ONLY, POOL_POLICY_CAPTURED_E0044):
            for case, request in requests.items():
                with self.subTest(policy=policy, case=case):
                    writes = self._run(GrmMaService(pool_policy=policy), request)
                    self.assertEqual([(offset, len(data)) for offset, data in writes],
                                     [expected[case]])

    def test_captured_failures_use_same_offsets(self):
        service = GrmMaService(pool_policy=POOL_POLICY_CAPTURED_E0044)
        cases = [
            (_open_request(0x0281), (28, 16)),
            (_lookup_request('absent_control'), (20, 16)),
            (_alloc_request(0xDEADBEEF, 0x1000), (16, 8)),
        ]
        for request, (offset, length) in cases:
            with self.subTest(offset=offset):
                writes = self._run(service, request)
                self.assertEqual([(position, len(data)) for position, data in writes],
                                 [(offset, length)])

    def test_supported_replies_identical_between_policies(self):
        """captured-e0044 returns the same bytes as default for the gl_common row."""
        requests = [
            _open_request(GRM_UNIT_GL_COMMON),
            _lookup_request('gl_common'),
            _alloc_request(GRM_KERNEL_HANDLE, 0x1000),
        ]
        for request in requests:
            replies = {}
            for policy in (POOL_POLICY_GL_COMMON_ONLY, POOL_POLICY_CAPTURED_E0044):
                replies[policy] = self._run(GrmMaService(pool_policy=policy), request)
            self.assertEqual(replies[POOL_POLICY_GL_COMMON_ONLY],
                             replies[POOL_POLICY_CAPTURED_E0044])


if __name__ == '__main__':
    unittest.main()
