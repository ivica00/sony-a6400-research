"""Unit tests for GuestGles: process binding, owner lifecycle, and ioctl dispatch."""
import struct
import unittest

from src.a6400.execution.guest_gles import (
    GuestGles, GlesBinding, UnsupportedGles, GLES_GET_VERSION,
    GLES_GET_MMIO_SIZE, GLES_GET_SUBDEVICE_ID, GLES_GET_POWER_STATE,
    GLES_QUERY_RESOURCE, GLES_GET_ALIGNMENT, GLES_GET_CONTEXT, GLES_RESET,
    GLES_LOCK_SEMAPHORE, GLES_UNLOCK_SEMAPHORE, GLES_RELEASE_RESOURCE, GLES_SIGNAL_COMPLETION,
    GLES_WAIT_COMPLETION, GLES_GET_POWER_STATE_ALT, GLES_GET_RESOURCE_SUB
)
from src.a6400.execution.kernel_task_identity import KernelTaskObservation, UnsupportedKernelBinding


class GuestGlesTests(unittest.TestCase):
    def setUp(self):
        # Valid task observation: thread_info 0x2000, task 0x8000, PID 1003, TGID 1000, limit 0x5f000000
        header = struct.pack('<6I', 0, 1, 0x5f000000, 0x8000, 0, 0)
        task_bytes = bytearray(0x10c)
        struct.pack_into('<I', task_bytes, 8, 0x2000)
        struct.pack_into('<2I', task_bytes, 0x104, 1003, 1000)
        reader = lambda addr, sz: header if addr == 0x2000 else task_bytes
        self.task_obs = KernelTaskObservation.read(reader, 0x2000)
        self.binding = GlesBinding(self.task_obs)

    def test_open_without_binding_raises_unsupported(self):
        gles = GuestGles(binding=None)
        with self.assertRaises(UnsupportedGles) as error:
            gles.open(flags=2, caller_pid=1003, caller_tgid=1000)
        self.assertEqual(error.exception.details['reason'], 'gles_kernel_process_binding_not_supplied')

    def test_binding_rejects_task_limit_exceeding_task_size(self):
        bad_task = KernelTaskObservation(0x2000, 0x8000, 1003, 1000, 0x70000000, 0)
        with self.assertRaises(UnsupportedKernelBinding):
            GlesBinding(bad_task)

    def test_open_validates_caller_pid_and_tgid(self):
        gles = GuestGles(self.binding)
        # Wrong PID
        with self.assertRaises(UnsupportedKernelBinding):
            gles.open(flags=2, caller_pid=999, caller_tgid=1000)
        # Wrong TGID
        with self.assertRaises(UnsupportedKernelBinding):
            gles.open(flags=2, caller_pid=1003, caller_tgid=999)

    def test_open_rejects_user_range_crossing_task_size(self):
        gles = GuestGles(self.binding)
        # Range crossing 0x5f000000
        with self.assertRaises(UnsupportedKernelBinding):
            gles.open(flags=2, caller_pid=1003, caller_tgid=1000,
                      user_ranges=[(0x5ef00000, 0x200000)])

    def test_open_succeeds_with_valid_binding_and_ranges(self):
        gles = GuestGles(self.binding)
        owner = gles.open(flags=2, caller_pid=1003, caller_tgid=1000,
                          user_ranges=[(0x10000, 0x4000), (0x5eb6e000, 0x22000)])
        self.assertEqual(owner['owner_id'], 1)
        self.assertEqual(owner['flags'], 2)
        self.assertEqual(owner['ref_count'], 1)
        self.assertEqual(owner['hardware_version'], 2)

    def test_ioctl_get_version_writes_2(self):
        gles = GuestGles(self.binding)
        owner = gles.open(flags=2, caller_pid=1003, caller_tgid=1000)

        mem = bytearray(16)
        mem_write = lambda addr, data: mem.__setitem__(slice(addr, addr + len(data)), data)
        mem_read = lambda addr, sz: bytes(mem[addr:addr + sz])

        ret = gles.ioctl(owner['owner_id'], GLES_GET_VERSION, 4, mem_read, mem_write)
        self.assertEqual(ret, 0)
        version = struct.unpack_from('<I', mem, 4)[0]
        self.assertEqual(version, 2)

    def test_ioctl_get_version_rejects_kernel_address(self):
        gles = GuestGles(self.binding)
        owner = gles.open(flags=2, caller_pid=1003, caller_tgid=1000)
        with self.assertRaises(UnsupportedGles):
            gles.ioctl(owner['owner_id'], GLES_GET_VERSION, 0x60000000, lambda *_: b'', lambda *_: None)

    def test_ioctl_get_mmio_size_writes_0x4000(self):
        gles = GuestGles(self.binding)
        owner = gles.open(flags=2, caller_pid=1003, caller_tgid=1000)
        mem = bytearray(16)
        ret = gles.ioctl(owner['owner_id'], GLES_GET_MMIO_SIZE, 4,
                         lambda a, s: bytes(mem[a:a+s]),
                         lambda a, d: mem.__setitem__(slice(a, a+len(d)), d))
        self.assertEqual(ret, 0)
        size = struct.unpack_from('<I', mem, 4)[0]
        self.assertEqual(size, 0x4000)

    def test_ioctl_get_subdevice_id_writes_1(self):
        gles = GuestGles(self.binding)
        owner = gles.open(flags=2, caller_pid=1003, caller_tgid=1000)
        mem = bytearray(16)
        ret = gles.ioctl(owner['owner_id'], GLES_GET_SUBDEVICE_ID, 4,
                         lambda a, s: bytes(mem[a:a+s]),
                         lambda a, d: mem.__setitem__(slice(a, a+len(d)), d))
        self.assertEqual(ret, 0)
        sub_id = struct.unpack_from('<I', mem, 4)[0]
        self.assertEqual(sub_id, 1)

    def test_ioctl_get_power_state_writes_1(self):
        gles = GuestGles(self.binding)
        owner = gles.open(flags=2, caller_pid=1003, caller_tgid=1000)
        mem = bytearray(16)
        ret = gles.ioctl(owner['owner_id'], GLES_GET_POWER_STATE, 4,
                         lambda a, s: bytes(mem[a:a+s]),
                         lambda a, d: mem.__setitem__(slice(a, a+len(d)), d))
        self.assertEqual(ret, 0)
        pwr = struct.unpack_from('<I', mem, 4)[0]
        self.assertEqual(pwr, 1)

    def test_decoded_mode_uses_grm_gles_ko_semantics(self):
        device = GuestGles(self.binding)
        owner = device.open(flags=2, caller_pid=1003, caller_tgid=1000)
        device.decoded_semantics = True
        memory = {0x1000: struct.pack('<I', 7)}

        def reader(address, size):
            return memory[address][:size]

        def writer(address, data):
            memory[address] = bytes(data)

        # 0x8004820A decodes to the suspend/status word (dev+0x48, zero at probe),
        # not the historical power_state=1.
        memory[0x2000] = struct.pack('<I', 0xFFFFFFFF)
        self.assertEqual(device.ioctl(owner['owner_id'], GLES_GET_POWER_STATE_ALT, 0x2000, reader, writer, tid=1003), 0)
        self.assertEqual(struct.unpack('<I', memory[0x2000])[0], 0)

        # 0xC004820D is a blocking wait: pending returns None (interpreter parks the
        # guest thread); a key-0 0xC004820E completes only the calling task's ctx.
        self.assertIsNone(device.ioctl(owner['owner_id'], GLES_GET_RESOURCE_SUB, 0x2000, reader, writer, tid=1003))
        memory[0x1000] = struct.pack('<I', 0)
        self.assertEqual(device.ioctl(owner['owner_id'], GLES_SIGNAL_COMPLETION, 0x1000, reader, writer, tid=1003), 0)
        memory[0x2000] = struct.pack('<I', 0xFFFFFFFF)
        self.assertEqual(device.ioctl(owner['owner_id'], GLES_GET_RESOURCE_SUB, 0x2000, reader, writer, tid=1003), 0)
        self.assertEqual(struct.unpack('<I', memory[0x2000])[0], 1)
        # Completion is consumed; the next wait is pending again.
        memory[0x2000] = struct.pack('<I', 0xFFFFFFFF)
        self.assertIsNone(device.ioctl(owner['owner_id'], GLES_GET_RESOURCE_SUB, 0x2000, reader, writer, tid=1003))

        # A different task's ctx is not completed by the key-0 signal above.
        self.assertIsNone(device.ioctl(owner['owner_id'], GLES_GET_RESOURCE_SUB, 0x2000, reader, writer, tid=1004))

        # Unknown nonzero key: kernel failure sentinel 0x1FFFFFFF, no completion.
        memory[0x1000] = struct.pack('<I', 0xDEADBEEF)
        self.assertEqual(device.ioctl(owner['owner_id'], GLES_SIGNAL_COMPLETION, 0x1000, reader, writer, tid=1003), 0)
        self.assertEqual(struct.unpack('<I', memory[0x1000])[0], 0x1FFFFFFF)
        self.assertIsNone(device.ioctl(owner['owner_id'], GLES_GET_RESOURCE_SUB, 0x2000, reader, writer, tid=1003))

        # 0xC0048209 decodes to the suspend/status consume query.
        memory[0x2000] = struct.pack('<I', 0xFFFFFFFF)
        self.assertEqual(device.ioctl(owner['owner_id'], GLES_WAIT_COMPLETION, 0x2000, reader, writer, tid=1003), 0)
        self.assertEqual(struct.unpack('<I', memory[0x2000])[0], 0)

        # Default mode keeps the historical table untouched.
        device.decoded_semantics = False
        memory[0x2000] = struct.pack('<I', 0xFFFFFFFF)
        self.assertEqual(device.ioctl(owner['owner_id'], GLES_GET_POWER_STATE_ALT, 0x2000, reader, writer, tid=1003), 0)
        self.assertEqual(struct.unpack('<I', memory[0x2000])[0], 1)

    def test_ioctl_query_resource_index_1_returns_mmio_base(self):
        gles = GuestGles(self.binding)
        owner = gles.open(flags=2, caller_pid=1003, caller_tgid=1000)
        mem = bytearray(16)
        struct.pack_into('<I', mem, 4, 1)  # query index 1 (MMIO base)
        ret = gles.ioctl(owner['owner_id'], GLES_QUERY_RESOURCE, 4,
                         lambda a, s: bytes(mem[a:a+s]),
                         lambda a, d: mem.__setitem__(slice(a, a+len(d)), d))
        self.assertEqual(ret, 0)
        base = struct.unpack_from('<I', mem, 4)[0]
        self.assertEqual(base, 0xf1000000)

    def test_ioctl_query_resource_index_0_returns_0x80000000(self):
        gles = GuestGles(self.binding)
        owner = gles.open(flags=2, caller_pid=1003, caller_tgid=1000)
        mem = bytearray(16)
        struct.pack_into('<I', mem, 4, 0)  # query index 0
        ret = gles.ioctl(owner['owner_id'], GLES_QUERY_RESOURCE, 4,
                         lambda a, s: bytes(mem[a:a+s]),
                         lambda a, d: mem.__setitem__(slice(a, a+len(d)), d))
        self.assertEqual(ret, 0)
        val = struct.unpack_from('<I', mem, 4)[0]
        self.assertEqual(val, 0x80000000)

    def test_ioctl_get_alignment_writes_0x200(self):
        gles = GuestGles(self.binding)
        owner = gles.open(flags=2, caller_pid=1003, caller_tgid=1000)
        mem = bytearray(16)
        ret = gles.ioctl(owner['owner_id'], GLES_GET_ALIGNMENT, 4,
                         lambda a, s: bytes(mem[a:a+s]),
                         lambda a, d: mem.__setitem__(slice(a, a+len(d)), d))
        self.assertEqual(ret, 0)
        align = struct.unpack_from('<I', mem, 4)[0]
        self.assertEqual(align, 0x200)

    def test_ioctl_lock_and_unlock_semaphore(self):
        gles = GuestGles(self.binding)
        owner = gles.open(flags=2, caller_pid=1003, caller_tgid=1000)
        mem = bytearray(16)
        struct.pack_into('<I', mem, 4, 1)  # sem_id = 1
        ret = gles.ioctl(owner['owner_id'], GLES_LOCK_SEMAPHORE, 4,
                         lambda a, s: bytes(mem[a:a+s]),
                         lambda a, d: mem.__setitem__(slice(a, a+len(d)), d))
        self.assertEqual(ret, 0)
        res = struct.unpack_from('<I', mem, 4)[0]
        self.assertEqual(res, 0)

        # Unlock semaphore
        struct.pack_into('<I', mem, 4, 1)
        ret = gles.ioctl(owner['owner_id'], GLES_UNLOCK_SEMAPHORE, 4,
                         lambda a, s: bytes(mem[a:a+s]),
                         lambda a, d: mem.__setitem__(slice(a, a+len(d)), d))
        self.assertEqual(ret, 0)
        res = struct.unpack_from('<I', mem, 4)[0]
        self.assertEqual(res, 0)

    def test_ioctl_signal_and_wait_completion(self):
        gles = GuestGles(self.binding)
        owner = gles.open(flags=2, caller_pid=1003, caller_tgid=1000)
        mem = bytearray(16)
        struct.pack_into('<I', mem, 4, 1)  # event_id = 1
        ret = gles.ioctl(owner['owner_id'], GLES_SIGNAL_COMPLETION, 4,
                         lambda a, s: bytes(mem[a:a+s]),
                         lambda a, d: mem.__setitem__(slice(a, a+len(d)), d))
        self.assertEqual(ret, 0)

        ret = gles.ioctl(owner['owner_id'], GLES_WAIT_COMPLETION, 4,
                         lambda a, s: bytes(mem[a:a+s]),
                         lambda a, d: mem.__setitem__(slice(a, a+len(d)), d))
        self.assertEqual(ret, 0)
        completed = struct.unpack_from('<I', mem, 4)[0]
        self.assertEqual(completed, 1)

    def test_mmap2_maps_mmio_range(self):
        import unicorn
        from src.a6400.execution.guest_mmap import GuestMmap
        mu = unicorn.Uc(unicorn.UC_ARCH_ARM, unicorn.UC_MODE_ARM)
        fs = type('DummyFS', (), {'fds': {}})()
        mapper = GuestMmap(mu, fs)
        gles = GuestGles(self.binding)
        owner = gles.open(flags=2, caller_pid=1003, caller_tgid=1000)
        event = gles.mmap2(mapper, 0, 0x4000, 3, 1, 0, owner['owner_id'])
        self.assertEqual(event['reason'], 'guarded_mmap2_allocated')
        self.assertEqual(mapper.page_backing[event['returned']]['device'], 'dmpgles2')
        self.assertEqual(gles.transactions[-1]['physical'], 0xf1000000)
        self.assertEqual(gles.bar_virtual, event['returned'])
        self.assertEqual(gles.bar_length, 0x4000)

    def test_mmap2_real_128k_bar_window_is_recognized(self):
        # The real camera maps dmpgles2 as 128 KiB at pgoff 0 (E0313); the
        # observed BAR identity word lives at the start of that window.
        import unicorn
        from src.a6400.execution.guest_mmap import GuestMmap
        mu = unicorn.Uc(unicorn.UC_ARCH_ARM, unicorn.UC_MODE_ARM)
        fs = type('DummyFS', (), {'fds': {}})()
        mapper = GuestMmap(mu, fs)
        gles = GuestGles(self.binding)
        owner = gles.open(flags=2, caller_pid=1003, caller_tgid=1000)
        event = gles.mmap2(mapper, 0, 0x20000, 3, 1, 0, owner['owner_id'])
        self.assertEqual(event['reason'], 'guarded_mmap2_allocated')
        self.assertEqual(gles.transactions[-1]['physical'], 0xf1000000)
        self.assertEqual(gles.bar_virtual, event['returned'])
        self.assertEqual(gles.bar_length, 0x4000)
        self.assertEqual(struct.unpack_from('<I', gles.bar, 0)[0], 0x000b0000)

    def test_ioctl_release_resource(self):
        gles = GuestGles(self.binding)
        owner = gles.open(flags=2, caller_pid=1003, caller_tgid=1000)
        mem = bytearray(16)
        struct.pack_into('<I', mem, 4, 0x04000000)
        ret = gles.ioctl(owner['owner_id'], GLES_RELEASE_RESOURCE, 4,
                         lambda a, s: bytes(mem[a:a+s]),
                         lambda a, d: mem.__setitem__(slice(a, a+len(d)), d))
        self.assertEqual(ret, 0)
        self.assertEqual(gles.transactions[-1]['mask'], 0x04000000)

    def test_decoded_event_wait_reports_engine_completion(self):
        # grm_gles.ko 0xC0048203 -> handler 0xAD0: waits for dev+0xA8 status
        # (IRQ handler from BAR+0x34). The opt-in engine model completes one
        # submitted command with the physically observed class 0x40000000.
        gles = GuestGles(self.binding)
        owner = gles.open(flags=2, caller_pid=1003, caller_tgid=1000)
        gles.decoded_semantics = True
        gles.engine_model = True
        gles.bar_virtual = 0x10000
        gles.bar_length = 0x4000
        memory = {0x10000 + 0xE8: b'\x01\x00\x05\x00',
                  0x2000: struct.pack('<I', 0x04000000)}

        def reader(address, size):
            return memory.get(address, b'\x00' * size)[:size]

        def writer(address, data):
            memory[address] = bytes(data)[:len(data)]

        ret = gles.ioctl(owner['owner_id'], GLES_RELEASE_RESOURCE, 0x2000,
                         reader, writer, tid=1003)
        self.assertEqual(ret, 0)
        self.assertEqual(struct.unpack('<I', memory[0x2000])[0], 0x45000000)
        # The reported status is consumed; with the bounded engine-state
        # budget exhausted the next wait is pending again.
        gles.engine_state_events = 16
        self.assertIsNone(gles.ioctl(owner['owner_id'], GLES_RELEASE_RESOURCE, 0x2000, reader,
                                 lambda address, data: memory.__setitem__(address, bytes(data)), tid=1003))
        self.assertEqual(gles.engine_completions, 1)
        done = [t for t in gles.transactions if t.get('operation') == 'engine-command']
        self.assertEqual(len(done), 1)
        self.assertEqual(done[0]['status'], 0x40000000)
        # The IRQ ack path cleared the class registers and consumed the ring
        # header (physical idle state is 0 at those offsets).
        self.assertEqual(memory[0x10000 + 0x1000], b'\x00\x00\x00\x00')
        self.assertEqual(memory[0x10000 + 0xC18], b'\x00\x00\x00\x00')
        self.assertEqual(memory[0x10000 + 0xE8], b'\x00\x00\x00\x00')

    def test_decoded_event_wait_without_command_returns_zero(self):
        gles = GuestGles(self.binding)
        owner = gles.open(flags=2, caller_pid=1003, caller_tgid=1000)
        gles.decoded_semantics = True
        gles.engine_model = True
        gles.bar_virtual = 0x10000
        memory = {0x2000: struct.pack('<I', 0x04000000)}

        def reader(address, size):
            return memory.get(address, b'\x00' * size)[:size]

        ret = gles.ioctl(owner['owner_id'], GLES_RELEASE_RESOURCE, 0x2000,
                         reader, lambda address, data: memory.__setitem__(address, bytes(data)),
                         tid=1003)
        self.assertIsNone(ret)
        self.assertEqual(gles.engine_completions, 0)
        # Modelled engine completion mirrors the IRQ status into dev+0xA8 and
        # the retried event wait reports the physically observed class word.
        gles.complete_engine_command('test')
        ret = gles.ioctl(owner['owner_id'], GLES_RELEASE_RESOURCE, 0x2000,
                         reader, lambda address, data: memory.__setitem__(address, bytes(data)),
                         tid=1003)
        self.assertEqual(ret, 0)
        self.assertEqual(struct.unpack('<I', memory[0x2000])[0], 0x45000000)
        # The reported status is consumed; with the bounded engine-state
        # budget exhausted the next wait is pending again.
        gles.engine_state_events = 16
        self.assertIsNone(gles.ioctl(owner['owner_id'], GLES_RELEASE_RESOURCE, 0x2000, reader,
                                 lambda address, data: memory.__setitem__(address, bytes(data)), tid=1003))
        self.assertEqual(gles.engine_completions, 1)

    def test_unsupported_ioctl_raises(self):
        gles = GuestGles(self.binding)
        owner = gles.open(flags=2, caller_pid=1003, caller_tgid=1000)
        with self.assertRaises(UnsupportedGles) as error:
            gles.ioctl(owner['owner_id'], 0xdeadbeef, 0, lambda *_: b'', lambda *_: None)
        self.assertEqual(error.exception.details['reason'], 'unsupported_gles_ioctl')


if __name__ == '__main__':
    unittest.main()
