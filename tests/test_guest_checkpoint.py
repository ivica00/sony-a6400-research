import struct
import tempfile
import unittest
from pathlib import Path

import unicorn
from unicorn import arm_const as arm

from src.a6400.execution.guest_checkpoint import restore_checkpoint, save_checkpoint
from src.a6400.execution.guest_threads import GuestThreads
from src.a6400.execution.guest_uipc import GuestUipc


class MockFilesystem:
    def __init__(self):
        self.fds = {3: {'path': '/dev/uipc', 'device': 'uipc'}}
        self.cache = {'/usr/lib/test.so': b'TEST_BYTES'}


class MockHeap:
    def __init__(self):
        self.current = 0x12000
        self.start = 0x10000
        self.ceiling = 0x20000


class MockMmap:
    def __init__(self):
        self.next_address = 0x51000000
        self.mapped_pages = {0x50000000}
        self.page_backing = {0x50000000: {'kind': 'anonymous'}}
        self.mappings = [{'address': 0x50000000, 'length': 0x1000}]
        self.base_address = 0x50000000
        self.ceiling_address = 0x5f000000
        self.search_low_base = 0x10000000


class MockProbe:
    def __init__(self):
        self.mu = unicorn.Uc(unicorn.UC_ARCH_ARM, unicorn.UC_MODE_ARM)
        self.instructions = 123456
        self.signal_handlers = {4: {'handler': 0x40001000, 'flags': 0, 'restorer': 0, 'mask': b'\x00' * 8}}
        self.report = {
            'serviced_syscalls': [{'syscall': 'test', 'returned': 0}],
            'syscall_responses_supplied': 1,
            'loaded_modules': ['/usr/kmod/test.ko'],
        }
        self.filesystem = MockFilesystem()
        self.threads = GuestThreads(initial_tid=1000)
        self.uipc = GuestUipc()
        self.heap = MockHeap()
        self.mmap = MockMmap()


class TestGuestCheckpoint(unittest.TestCase):
    def test_save_and_restore_checkpoint(self):
        # 1. Setup mock probe with mapped memory and register state
        p1 = MockProbe()
        p1.mu.mem_map(0x10000, 0x2000, unicorn.UC_PROT_ALL)
        p1.mu.mem_write(0x10000, b'HELLO CHECKPOINT 12345')
        p1.mu.reg_write(arm.UC_ARM_REG_R0, 0x42)
        p1.mu.reg_write(arm.UC_ARM_REG_R7, 197)
        p1.mu.reg_write(arm.UC_ARM_REG_PC, 0x10004)

        # 2. Save checkpoint
        with tempfile.TemporaryDirectory() as tmpdir:
            ckpt_path = Path(tmpdir) / 'test.ckpt'
            saved_size = save_checkpoint(p1, ckpt_path)
            self.assertGreater(saved_size, 0)
            self.assertTrue(ckpt_path.exists())

            # 3. Restore into clean probe
            p2 = MockProbe()
            restore_checkpoint(p2, ckpt_path)

            # 4. Verify registers and memory
            self.assertEqual(p2.mu.reg_read(arm.UC_ARM_REG_R0), 0x42)
            self.assertEqual(p2.mu.reg_read(arm.UC_ARM_REG_R7), 197)
            self.assertEqual(p2.mu.reg_read(arm.UC_ARM_REG_PC), 0x10004)
            self.assertEqual(bytes(p2.mu.mem_read(0x10000, 22)), b'HELLO CHECKPOINT 12345')

            # 5. Verify subsystem states
            self.assertEqual(p2.instructions, 123456)
            self.assertEqual(p2.filesystem.fds[3]['path'], '/dev/uipc')
            self.assertEqual(p2.filesystem.cache['/usr/lib/test.so'], b'TEST_BYTES')
            self.assertEqual(p2.threads.current_tid, 1000)
            self.assertEqual(p2.heap.current, 0x12000)
            self.assertEqual(p2.mmap.next_address, 0x51000000)
            self.assertEqual(p2.mmap.mapped_pages, {0x50000000})
            self.assertEqual(p2.report['syscall_responses_supplied'], 1)
            self.assertEqual(p2.report['loaded_modules'], ['/usr/kmod/test.ko'])


if __name__ == '__main__':
    unittest.main()
