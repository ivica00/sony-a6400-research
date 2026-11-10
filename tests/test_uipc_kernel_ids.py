import struct
import unittest

from src.a6400.execution.guest_uipc import GuestUipc
from src.a6400.execution.guest_uipc_ids import KernelDynamicIds, UnsupportedDynamicId


class KernelIdTests(unittest.TestCase):
    def test_namespaces_and_lowest_released_slot(self):
        ids = KernelDynamicIds()
        self.assertEqual(ids.allocate(0x2a, 0x3f), (0, 0x3f6000))
        self.assertEqual(ids.allocate(2, 0x3f), (0, 0x3f6001))
        self.assertEqual(ids.allocate(0x12, 0x88), (0, 0x886000))
        self.assertEqual(ids.allocate(6, 0x55), (0, 0x557000))
        self.assertEqual(ids.release(0x42, 0x3f6000), 0)
        self.assertEqual(ids.allocate(2, 0x77), (0, 0x776000))
        with self.assertRaisesRegex(UnsupportedDynamicId, 'not_owned'):
            ids.release(0x42, 0x3f6000)
        self.assertEqual(ids.allocations['queue'][0x6000], 0x776000)

    def test_invalid_type_and_outside_pool_do_not_mutate(self):
        ids = KernelDynamicIds()
        self.assertEqual(ids.allocate(0, 1), (-1024, None))
        self.assertEqual(ids.release(0x42, 0x12341000), -1024)
        with self.assertRaises(UnsupportedDynamicId):
            ids.release(0x42, 0x12346000)
        self.assertEqual(ids.allocations, {'queue': {}, 'broadcast': {}, 'semaphore': {}})

    def test_connect_control_queue_and_free_abi(self):
        data = bytearray(4096)
        def read(address, size):
            return bytes(data[address:address + size])
        def write(address, value):
            data[address:address + len(value)] = value
        uipc = GuestUipc()
        uipc.pool_options_policy = 'kernel-e0301'
        write(0x100, struct.pack('<II', 0, 0x200))
        self.assertEqual(uipc.handle_connect(read, write, 0x100), 0)
        self.assertEqual(struct.unpack_from('<I', data, 0x20c)[0], 0x3f6000)
        write(0x200, struct.pack('<3I', 2, 0x22, 0x300))
        self.assertEqual(uipc.handle_dynamic_id(read, write, 0x100), 0)
        value = struct.unpack_from('<I', data, 0x300)[0]
        self.assertEqual(value, 0x226001)
        # Free's third field is the value itself, never an output pointer.
        write(0x200, struct.pack('<3I', 0x42, 0, value))
        self.assertEqual(uipc.handle_dynamic_id(read, write, 0x100), 0)
        self.assertNotIn(0x6001, uipc.kernel_dynamic_ids.allocations['queue'])
