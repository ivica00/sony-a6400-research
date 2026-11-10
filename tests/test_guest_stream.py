"""Constructed stream mappings exercise ABI, ownership and unknown-byte guards."""
import struct
import unittest

import unicorn
from unicorn import arm_const as arm

from src.a6400.execution.guest_stream import GuestStream, UnsupportedStream, STREAM_GET_OFFSET
from src.a6400.execution.guest_mmap import GuestMmap, UnsupportedMmap
from src.a6400.execution.guarded_bytes import UnverifiedGuestData
from src.a6400.execution.interpreter_probe import InterpreterProbe
from src.a6400.execution.guest_stdio import GuestStdio
from project_paths import PROJECT_ROOT
from test_interpreter_probe import make_elf


PROFILE = {'major': 249, 'minor': 7, 'initial_offset': 0,
           'module_sha256': 'fixture', 'devno_sha256': 'fixture'}


class StreamTests(unittest.TestCase):
    def setUp(self):
        self.mu = unicorn.Uc(unicorn.UC_ARCH_ARM, unicorn.UC_MODE_ARM)
        self.mapper = GuestMmap(self.mu, type('FS', (), {'fds': {}})())
        self.stops = []
        self.stream = GuestStream(self.mu, self.mapper, PROFILE, self.stop, lambda a, n: None)
        self.mu.mem_map(0x1000, 4096)
        self.mu.mem_map(0x3000, 4096, unicorn.UC_PROT_READ)

    def stop(self, details):
        self.stops.append(details)
        self.mu.emu_stop()

    def map(self, addr=0, pgoff=0x2000):
        return self.stream.mmap2(addr, 4096, 3, 1, 4, pgoff)['returned']

    def test_ioctl_initializes_only_four_output_bytes_and_rejects_other_commands(self):
        self.mu.mem_write(0x1000, b'GUARD' * 4)
        self.assertEqual(self.stream.ioctl(STREAM_GET_OFFSET, 0x1004), 0)
        self.assertEqual(bytes(self.mu.mem_read(0x1000, 12)), b'GUAR' + bytes(4) + b'RDGU')
        self.assertEqual(self.stream.ioctl(0x1234, 0), 0xffffffea)

    def test_copy_to_unwritable_or_crossing_buffer_stops_without_mutation(self):
        self.mu.mem_write(0x3000, b'KEEP')
        for pointer in (0x3000, 0x1ffe):
            with self.assertRaises(UnsupportedStream):
                self.stream.ioctl(STREAM_GET_OFFSET, pointer)
        self.assertEqual(bytes(self.mu.mem_read(0x3000, 4)), b'KEEP')
        self.assertEqual(self.stream.transactions, [])

    def test_physical_offset_is_used_and_ioctl_returns_both_unsigned_delta_directions(self):
        virtual = self.map()
        self.assertEqual(self.stream.mapping['physical_start'], 0x2000000)
        self.stream.ioctl(STREAM_GET_OFFSET, 0x1000)
        self.assertEqual(struct.unpack('<I', self.mu.mem_read(0x1000, 4))[0], virtual - 0x2000000)
        self.assertEqual(self.mapper.page_backing[virtual]['kind'], 'device')
        self.assertEqual(self.mapper.mappings[-1]['physical_start'], 0x2000000)
        self.assertEqual(self.mapper.mappings[-1]['flags'], 1)
        self.assertNotIn('anonymous', self.mapper.mappings[-1])

    def test_larger_physical_address_produces_absolute_delta(self):
        virtual = self.map(pgoff=0x90000)
        self.assertEqual(self.stream.offset, 0x90000000 - virtual)

    def test_mapped_physical_bytes_cannot_be_read_by_host_consumers(self):
        virtual = self.map()
        with self.assertRaises(UnverifiedGuestData):
            self.stream.assert_known_host_read(virtual, 4)
        self.stream.forget_range(virtual, 2)
        self.stream.assert_known_host_read(virtual, 2)
        with self.assertRaises(UnverifiedGuestData):
            self.stream.assert_known_host_read(virtual, 4)

    def test_original_arm_store_then_load_is_known_but_adjacent_data_is_guarded(self):
        virtual = self.map()
        self.mu.mem_write(0x1000, struct.pack('<3I', 0xe5801000, 0xe5902000, 0xe5903004))
        self.mu.reg_write(arm.UC_ARM_REG_R0, virtual)
        self.mu.reg_write(arm.UC_ARM_REG_R1, 0x12345678)
        self.mu.emu_start(0x1000, 0x100c, count=3)
        self.assertEqual(self.mu.reg_read(arm.UC_ARM_REG_R2), 0x12345678)
        self.assertEqual(len(self.stops), 1)
        self.assertEqual(self.stops[0]['physical_address'], 0x2000004)
        self.stream.assert_known_host_read(virtual, 4)
        self.assertEqual(self.stream.report()['unknown_bytes'], 4092)

    def test_unknown_mapping_cannot_be_discarded_as_private_anonymous_memory(self):
        virtual = self.map()
        with self.assertRaises(UnsupportedMmap):
            self.mapper.request_madvise(virtual, 4096, 4)

    def test_checkpoint_state_round_trip_keeps_mapping_and_guards(self):
        virtual = self.map()
        self.stream.forget_range(virtual, 4)
        state = self.stream.to_state()
        fresh_mu = unicorn.Uc(unicorn.UC_ARCH_ARM, unicorn.UC_MODE_ARM)
        fresh_mapper = GuestMmap(fresh_mu, type('FS', (), {'fds': {}})())
        fresh = GuestStream(fresh_mu, fresh_mapper, PROFILE, self.stop, lambda a, n: None)
        fresh.from_state(state)
        self.assertEqual(fresh.mapping, self.stream.mapping)
        self.assertEqual(fresh.mappings, self.stream.mappings)
        self.assertEqual(fresh.unknown, self.stream.unknown)
        self.assertEqual(fresh.offset, self.stream.offset)

    def test_unsupported_alias_permissions_and_overflow_do_not_allocate_pages(self):
        before = set(self.mapper.mapped_pages)
        for args in ((0, 4096, 7, 1, 4, 0), (0, 4096, 3, 2, 4, 0),
                     (0, 8192, 3, 1, 4, 0xfffff)):
            with self.subTest(args=args):
                with self.assertRaises(UnsupportedStream):
                    self.stream.mmap2(*args)
                self.assertEqual(self.mapper.mapped_pages, before)
        self.map()
        with self.assertRaises(UnsupportedStream):
            self.map()

    def test_existing_guest_pages_are_not_replaced(self):
        self.mapper.register_range(0x1000, 4096)
        with self.assertRaises(UnsupportedStream):
            self.map(addr=0x1000)

    def test_failed_store_does_not_make_readonly_physical_bytes_known(self):
        virtual = self.stream.mmap2(0, 4096, 1, 1, 4, 0x2000)['returned']
        self.mu.mem_write(0x1000, struct.pack('<I', 0xe5801000))
        self.mu.reg_write(arm.UC_ARM_REG_R0, virtual)
        self.mu.reg_write(arm.UC_ARM_REG_R1, 0x12345678)
        with self.assertRaises(unicorn.UcError):
            self.mu.emu_start(0x1000, 0x1004, count=1)
        with self.assertRaises(UnverifiedGuestData):
            self.stream.assert_known_host_read(virtual, 4)

    def test_zero_length_does_not_update_mapping_delta(self):
        result = self.stream.mmap2(0, 0, 3, 1, 4, 0x2000)
        self.assertEqual(result['returned'], 0xffffffea)
        self.assertEqual(self.stream.offset, 0)
        self.assertIsNone(self.stream.mapping)

    def test_open_flags_and_identity_fail_closed(self):
        self.stream.open(4098)
        self.stream.open(0x21002)
        with self.assertRaises(UnsupportedStream):
            self.stream.open(0x102)
        with self.assertRaises(ValueError):
            GuestStream(self.mu, self.mapper, {**PROFILE, 'minor': 8}, self.stop, lambda a, n: None)

    def test_disjoint_physical_mappings_succeed_while_overlapping_alias_fails_closed(self):
        v1 = self.map(pgoff=0x202e0)
        v2 = self.map(pgoff=0x20030)
        self.assertNotEqual(v1, v2)
        self.assertEqual(len(self.stream.mappings), 2)
        with self.assertRaises(UnsupportedStream):
            self.map(pgoff=0x20030)



class StreamProbeTests(unittest.TestCase):
    def probe(self):
        folder = PROJECT_ROOT / 'artifacts/tests/stream-probe'
        folder.mkdir(parents=True, exist_ok=True)
        app = make_elf(folder / 'app.elf', bytes.fromhex('fee7'), dynamic=False)
        interp = make_elf(folder / 'interpreter.elf', struct.pack('<2I', 0xef000000, 0xeafffffe), thumb=False)
        probe = InterpreterProbe(syscall_policy='mmap', uname_profile={'raw_hex': bytes(390).hex()},
                                 filesystem={'nodes': {}, 'content_loader': lambda *a: b''})
        probe.prepare(app, interp, ['/stream-test'])
        probe.syscall_policy = 'uipc'
        probe.stream = GuestStream(probe.mu, probe.mmap, PROFILE, probe._identity_boundary, probe._after_host_write)
        probe.stdio = GuestStdio()
        probe.filesystem.fds[4] = {'path': '/dev/stream', 'device': 'stream'}
        return probe

    def test_arm_ioctl_uses_stream_dispatch_and_preserves_unknown_command_errno(self):
        probe = self.probe()
        for reg, val in ((arm.UC_ARM_REG_R0, 4), (arm.UC_ARM_REG_R1, 0x1234),
                         (arm.UC_ARM_REG_R2, 0), (arm.UC_ARM_REG_R7, 54)):
            probe.mu.reg_write(reg, val)
        report = probe.run(instruction_budget=2)
        self.assertEqual(report['syscall_responses_supplied'], 1)
        self.assertEqual(report['serviced_syscalls'][0]['returned'], 0xffffffea)
        self.assertEqual(report['serviced_syscalls'][0]['device'], 'stream')

    def test_arm_stdout_cannot_consume_unwritten_physical_mapping(self):
        probe = self.probe()
        virtual = probe.stream.mmap2(0, 4096, 3, 1, 4, 0x2000)['returned']
        for reg, val in ((arm.UC_ARM_REG_R0, 1), (arm.UC_ARM_REG_R1, virtual),
                         (arm.UC_ARM_REG_R2, 4), (arm.UC_ARM_REG_R7, 4)):
            probe.mu.reg_write(reg, val)
        report = probe.run(instruction_budget=2)
        self.assertEqual(report['status'], 'unverified_device_read')
        self.assertEqual(report['syscall_responses_supplied'], 0)
        self.assertEqual(report['stdio']['stdout_chunks'], 0)
