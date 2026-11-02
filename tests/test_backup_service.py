"""Unit tests for BK4PresetState and PresetBackedBackupService."""
import struct
import unittest

from project_paths import PROJECT_ROOT
from src.a6400.execution.backup_service import (
    DEFAULT_PRESET_REL,
    DEFAULT_PRESET_SHA256,
    BK4PresetState,
    PresetBackedBackupService,
    checked_bk4,
)
from src.a6400.execution.guest_uipc import (
    BACKUP_SERVICE_QUEUE,
    GuestUipc,
    UnsupportedUipc,
)


class BackupServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.preset_raw = (PROJECT_ROOT / DEFAULT_PRESET_REL).read_bytes()

    def test_checked_bk4_valid_and_invalid(self):
        info = checked_bk4(self.preset_raw)
        self.assertEqual(info['subsystems'], 691)
        self.assertEqual(info['properties'], 28900)
        self.assertEqual(info['data_offset'], 0x2b6a0)

        # Truncated header
        with self.assertRaises(ValueError):
            checked_bk4(b'short')

        # Invalid identifier
        corrupt_magic = bytearray(self.preset_raw[:0x200])
        corrupt_magic[12:16] = b'XXXX'
        with self.assertRaises(ValueError):
            checked_bk4(corrupt_magic)

        # Corrupt checksum
        corrupt_chk = bytearray(self.preset_raw[:0x30000])
        corrupt_chk[0x10] ^= 0xff
        with self.assertRaises(ValueError):
            checked_bk4(corrupt_chk)

    def test_preset_state_initialization_and_hash_guard(self):
        state = BK4PresetState(self.preset_raw, expected_sha256=DEFAULT_PRESET_SHA256)
        self.assertEqual(state.subsystems, 691)
        self.assertEqual(state.properties, 28900)

        # Mismatched hash rejected
        with self.assertRaises(ValueError):
            BK4PresetState(self.preset_raw, expected_sha256='0' * 64)

    def test_search_id_known_units(self):
        state = BK4PresetState(self.preset_raw)

        # Unit 0x003e000b (Startup flag)
        desc_3e = state.search_id(0x003e000b)
        self.assertIsNotNone(desc_3e)
        self.assertEqual(desc_3e.unit, 0x003e000b)
        self.assertEqual(desc_3e.subsystem, 0x3e)
        self.assertEqual(desc_3e.prop_index, 0xb)
        self.assertEqual(desc_3e.size, 1)
        self.assertEqual(desc_3e.attribute, 0)
        self.assertEqual(desc_3e.data_offset, 0x66b2c)
        self.assertEqual(state.read_unit(0x003e000b), b'\x01')

        # Unit 0x00940003 (Task 94 state)
        desc_94 = state.search_id(0x00940003)
        self.assertIsNotNone(desc_94)
        self.assertEqual(desc_94.unit, 0x00940003)
        self.assertEqual(desc_94.subsystem, 0x94)
        self.assertEqual(desc_94.prop_index, 0x3)
        self.assertEqual(desc_94.size, 1)
        self.assertEqual(desc_94.attribute, 0xa)
        self.assertEqual(desc_94.data_offset, 0x860b0)
        self.assertEqual(state.read_unit(0x00940003), b'\x00')

        # Unit 0x00fa007c (LIRO direct address)
        desc_fa = state.search_id(0x00fa007c)
        self.assertIsNotNone(desc_fa)
        self.assertEqual(desc_fa.unit, 0x00fa007c)
        self.assertEqual(desc_fa.size, 4)
        self.assertEqual(desc_fa.data_offset, 0xb4de0)
        self.assertEqual(state.read_unit(0x00fa007c), b'\x00\x60\x5c\x03')

    def test_search_id_out_of_range_or_missing(self):
        state = BK4PresetState(self.preset_raw)
        self.assertIsNone(state.search_id(0x03000000))  # Subsystem 0x300 >= 691
        self.assertIsNone(state.search_id(0x003e00ff))  # Prop 0xff >= 34 for subsystem 0x3e

        with self.assertRaises(KeyError):
            state.read_unit(0x03000000)

    def test_descriptor_encodings_match_original_arm_getters(self):
        from tools.research.backup_read_contract_trace import run
        report = run()
        self.assertEqual(report['status'], 'original_getters_match')
        self.assertEqual({case['encoding'] for case in report['cases']},
                         {'inline-size', 'extended', 'variable'})

    def test_write_unit_mutates_ram(self):
        state = BK4PresetState(self.preset_raw)
        self.assertEqual(state.read_unit(0x00940003), b'\x00')
        state.write_unit(0x00940003, b'\x42')
        self.assertEqual(state.read_unit(0x00940003), b'\x42')

        # Invalid size rejected
        with self.assertRaises(ValueError):
            state.write_unit(0x00940003, b'\x01\x02')

    def test_service_backup_write(self):
        state = BK4PresetState(self.preset_raw)
        service = PresetBackedBackupService(state)

        # Guest memory buffer: msg_ptr at 100, src_ptr at 200
        mem = bytearray(512)
        # Word 0: 8 (write), Word 2: 3 (args), Word 3: queue, Word 6: 0x3e, Word 7: 0x003e000b, Word 8: 200
        struct.pack_into('<9I', mem, 100, 8, 0, 3, BACKUP_SERVICE_QUEUE, 0, 0, 0x3e, 0x003e000b, 200)
        mem[200] = 0x55  # write value 0x55

        def reader(addr, sz):
            return bytes(mem[addr : addr + sz])

        def writer(addr, data):
            mem[addr : addr + len(data)] = data

        ret = service.handle_uipc_sync_message(reader, writer, 100)
        self.assertEqual(ret, 0)
        # Reply code written to msg_ptr + 4
        reply_code = struct.unpack_from('<i', mem, 104)[0]
        self.assertEqual(reply_code, 0)
        self.assertEqual(state.read_unit(0x003e000b), b'\x55')
        self.assertEqual(len(service.events), 1)
        self.assertEqual(service.events[0]['type'], 'Backup_write')

    def test_service_backup_write_subsystem_mismatch(self):
        state = BK4PresetState(self.preset_raw)
        service = PresetBackedBackupService(state)

        mem = bytearray(512)
        # Subsystem 0x99 mismatch with unit 0x003e000b
        struct.pack_into('<9I', mem, 100, 8, 0, 3, BACKUP_SERVICE_QUEUE, 0, 0, 0x99, 0x003e000b, 200)

        def reader(addr, sz):
            return bytes(mem[addr : addr + sz])

        def writer(addr, data):
            mem[addr : addr + len(data)] = data

        ret = service.handle_uipc_sync_message(reader, writer, 100)
        self.assertEqual(ret, 0)
        reply_code = struct.unpack_from('<i', mem, 104)[0]
        self.assertEqual(reply_code, -4)
        self.assertEqual(state.read_unit(0x003e000b), b'\x01')  # unmutated

    def test_service_backup_read(self):
        state = BK4PresetState(self.preset_raw)
        service = PresetBackedBackupService(state)

        mem = bytearray(512)
        # Word 0: 3 (read), Word 2: 2 (args), Word 3: queue, Word 6: 0x00fa007c, Word 7: dst_ptr 300
        struct.pack_into('<8I', mem, 100, 3, 0, 2, BACKUP_SERVICE_QUEUE, 0, 0, 0x00fa007c, 300)

        def reader(addr, sz):
            return bytes(mem[addr : addr + sz])

        def writer(addr, data):
            mem[addr : addr + len(data)] = data

        ret = service.handle_uipc_sync_message(reader, writer, 100)
        self.assertEqual(ret, 0)
        reply_size = struct.unpack_from('<i', mem, 104)[0]
        self.assertEqual(reply_size, 4)
        read_val = struct.unpack_from('<I', mem, 300)[0]
        self.assertEqual(read_val, 0x035c6000)

    def test_service_unsupported_operation(self):
        state = BK4PresetState(self.preset_raw)
        service = PresetBackedBackupService(state)
        mem = bytearray(512)
        struct.pack_into('<8I', mem, 100, 99, 0, 2, BACKUP_SERVICE_QUEUE, 0, 0, 0, 0)

        with self.assertRaises(UnsupportedUipc):
            service.handle_uipc_sync_message(lambda a, s: bytes(mem[a : a + s]), None, 100)

    def test_nread_copies_whole_unit_and_preserves_tail_and_preset(self):
        state = BK4PresetState(self.preset_raw)
        service = PresetBackedBackupService(state)
        before = bytes(state.raw)
        for capacity in (4, 12):
            with self.subTest(capacity=capacity):
                mem = bytearray(b'\xa5' * 512)
                struct.pack_into('<9I', mem, 100, 30, 0, 3, BACKUP_SERVICE_QUEUE,
                                 0, 0, 0x00fa007c, 300, capacity)
                service.handle_uipc_sync_message(lambda a, s: bytes(mem[a:a+s]),
                                                lambda a, d: mem.__setitem__(slice(a, a+len(d)), d), 100)
                self.assertEqual(mem[300:304], state.read_unit(0x00fa007c))
                self.assertEqual(mem[304:312], b'\xa5' * 8)
                self.assertEqual(struct.unpack_from('<i', mem, 104)[0], 4)
                self.assertEqual(bytes(state.raw), before)

    def test_nread_small_or_negative_capacity_stops_before_any_write(self):
        service = PresetBackedBackupService(BK4PresetState(self.preset_raw))
        for capacity in (0, 3, 0xffffffff, 0x80000000):
            with self.subTest(capacity=capacity):
                mem = bytearray(512)
                struct.pack_into('<9I', mem, 100, 30, 0, 3, BACKUP_SERVICE_QUEUE,
                                 0, 0, 0x00fa007c, 300, capacity)
                before = bytes(mem)
                with self.assertRaises(UnsupportedUipc) as caught:
                    service.handle_uipc_sync_message(lambda a, s: bytes(mem[a:a+s]),
                                                    lambda a, d: self.fail('unexpected write'), 100)
                self.assertEqual(caught.exception.details['reason'], 'backup_nread_capacity_assertion')
                self.assertEqual(bytes(mem), before)

    def test_nread_missing_unit_returns_minus_one_without_touching_destination(self):
        service = PresetBackedBackupService(BK4PresetState(self.preset_raw))
        mem = bytearray(b'\xa5' * 512)
        struct.pack_into('<9I', mem, 100, 30, 0, 3, BACKUP_SERVICE_QUEUE, 0, 0, 0x03000000, 300, 4)
        service.handle_uipc_sync_message(lambda a, s: bytes(mem[a:a+s]),
                                        lambda a, d: mem.__setitem__(slice(a, a+len(d)), d), 100)
        self.assertEqual(struct.unpack_from('<i', mem, 104)[0], -1)
        self.assertEqual(mem[300:304], b'\xa5' * 4)

    def test_metadata_queries_return_preset_size_attribute_or_missing(self):
        state = BK4PresetState(self.preset_raw)
        service = PresetBackedBackupService(state)
        for op, unit, expected in ((0, 0x00940003, 1), (2, 0x00940003, 10),
                                   (0, 0x03000000, -1), (2, 0x03000000, -1)):
            with self.subTest(op=op, unit=unit):
                mem = bytearray(512)
                struct.pack_into('<9I', mem, 100, op, 0, 1, BACKUP_SERVICE_QUEUE, 0, 0, unit, 0, 0)
                service.handle_uipc_sync_message(lambda a, s: bytes(mem[a:a+s]),
                                                lambda a, d: mem.__setitem__(slice(a, a+len(d)), d), 100)
                self.assertEqual(struct.unpack_from('<i', mem, 104)[0], expected)

    def test_read_missing_and_read4_wrong_size_match_original_return_values(self):
        state = BK4PresetState(self.preset_raw)
        service = PresetBackedBackupService(state)
        large_unit = next((subsystem << 16) | prop
                          for subsystem in range(state.subsystems)
                          for prop in range(struct.unpack_from('<H', state.raw, 0x100 + subsystem * 6)[0])
                          if (d := state.search_id((subsystem << 16) | prop)) and d.size > 4)
        for op, unit, expected in ((3, 0x03000000, -1), (4, 0x03000000, 0),
                                   (4, 0x003e000b, 0), (4, large_unit, 0),
                                   (4, 0x00fa007c, 0x035c6000)):
            with self.subTest(op=op, unit=unit):
                mem = bytearray(b'\xa5' * 512)
                struct.pack_into('<9I', mem, 100, op, 0, 2, BACKUP_SERVICE_QUEUE, 0, 0, unit, 300, 0)
                service.handle_uipc_sync_message(lambda a, s: bytes(mem[a:a+s]),
                                                lambda a, d: mem.__setitem__(slice(a, a+len(d)), d), 100)
                self.assertEqual(struct.unpack_from('<i', mem, 104)[0], expected)
                self.assertEqual(mem[300:308], b'\xa5' * 8)

    def test_guest_uipc_preset_backed_integration(self):
        uipc = GuestUipc(backup_service_policy='preset-backed')
        self.assertIsNotNone(uipc.backup_service)

        data = bytearray(256)
        struct.pack_into('<2I', data, 0, BACKUP_SERVICE_QUEUE, 16)
        struct.pack_into('<3I', data, 16, 64, 0, 0)
        # Operation 3: Backup_read(0x00fa007c, dst=128)
        struct.pack_into('<8I', data, 64, 3, 0, 2, BACKUP_SERVICE_QUEUE, 0, 0, 0x00fa007c, 128)

        def reader(a, s):
            return bytes(data[a : a + s])

        def writer(a, d):
            data[a : a + len(d)] = d

        ret = uipc.handle_snd_sync_msg(reader, 0, memory_writer=writer)
        self.assertEqual(ret, 0)
        self.assertIn('preset-backed', uipc.transactions[-1]['classification'])
        reply_size = struct.unpack_from('<i', data, 68)[0]
        self.assertEqual(reply_size, 4)
        read_val = struct.unpack_from('<I', data, 128)[0]
        self.assertEqual(read_val, 0x035c6000)

    def test_compact_allocations_support_one_and_two_argument_requests(self):
        service = PresetBackedBackupService(BK4PresetState(self.preset_raw))
        for op, size, expected in ((0, 28, 4), (2, 28, 0), (3, 32, 4), (4, 28, 0x035c6000)):
            with self.subTest(op=op):
                mem = bytearray(512)
                struct.pack_into('<8I', mem, 100, op, 0, 2 if op == 3 else 1,
                                 BACKUP_SERVICE_QUEUE, 0, 0, 0x00fa007c, 300)
                def read(address, length):
                    self.assertLessEqual(address + length, 100 + size)
                    return bytes(mem[address:address + length])
                service.handle_uipc_sync_message(read,
                    lambda a, d: mem.__setitem__(slice(a, a+len(d)), d), 100, size)
                self.assertEqual(struct.unpack_from('<I', mem, 104)[0], expected)
                if op == 3:
                    self.assertEqual(mem[300:304], bytes.fromhex('00605c03'))

    def test_truncated_message_stops_without_writes(self):
        service = PresetBackedBackupService(BK4PresetState(self.preset_raw))
        for size in (20, 32):
            with self.subTest(size=size):
                mem = bytearray(512)
                struct.pack_into('<9I', mem, 100, 30, 0, 3, BACKUP_SERVICE_QUEUE, 0, 0,
                                 0x00fa007c, 300, 4)
                with self.assertRaises(UnsupportedUipc) as caught:
                    service.handle_uipc_sync_message(lambda a, s: bytes(mem[a:a+s]),
                        lambda a, d: self.fail('unexpected mutation'), 100, size)
                self.assertIn('truncated', caught.exception.details['reason'])
