"""Unit tests for BK4PresetState and PresetBackedBackupService."""
import struct
import tempfile
import unittest
from pathlib import Path

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
        preset_path = PROJECT_ROOT / DEFAULT_PRESET_REL
        if not preset_path.is_file():
            raise unittest.SkipTest(f"Local firmware preset not present: {DEFAULT_PRESET_REL}")
        cls.preset_raw = preset_path.read_bytes()

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
        self.assertEqual(reply_code, 1)  # success returns the unit size (callers test > 0)
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

    def test_setting_attr_write_element_checks_and_stores_bytes(self):
        state = BK4PresetState(self.preset_raw)
        service = PresetBackedBackupService(state)
        unit = 0x1070394
        before = state.read_unit(unit)
        mem = bytearray(b'\xa5' * 512)
        mem[300] = 0x5A

        def run(index, subsystem):
            struct.pack_into('<10I', mem, 100, 28, 0, 4, BACKUP_SERVICE_QUEUE, 0, 0,
                             index, subsystem, unit, 300)
            service.handle_uipc_sync_message(lambda a, s: bytes(mem[a:a+s]),
                                            lambda a, d: mem.__setitem__(slice(a, a+len(d)), d), 100)
            return struct.unpack_from('<i', mem, 104)[0]

        # a) index 0 in range, subsystem matches unit: byte 0 replaced, tail kept
        self.assertEqual(run(0, 263), 1)
        after = state.read_unit(unit)
        self.assertEqual(after[0], 0x5A)
        self.assertEqual(after[1:4], before[1:4])

        # b) index == count (4) is rejected without a write
        snapshot = bytes(state.raw)
        self.assertEqual(run(4, 263), -7)
        self.assertEqual(bytes(state.raw), snapshot)

        # c) subsystem mismatch is rejected without a write
        self.assertEqual(run(0, 262), -4)
        self.assertEqual(bytes(state.raw), snapshot)

    def test_setting_attr_read_ops_26_34(self):
        state = BK4PresetState(self.preset_raw)
        service = PresetBackedBackupService(state)
        unit = 0x1070394
        state.write_unit(unit, bytes.fromhex('11223344'))
        mem = bytearray(bytes([0xa5]) * 512)
        snapshot = bytes(state.raw)

        def run(op, index, unit=unit, cap=4):
            words = (op, 0, 4 if op == 34 else 3, BACKUP_SERVICE_QUEUE, 0, 0, index, unit, 300) + ((cap,) if op == 34 else ())
            struct.pack_into('<%dI' % len(words), mem, 100, *words)
            service.handle_uipc_sync_message(lambda a, s: bytes(mem[a:a+s]),
                                            lambda a, d: mem.__setitem__(slice(a, a+len(d)), d), 100)
            return struct.unpack_from('<i', mem, 104)[0]

        for op in (26, 34):
            mem[300:304] = b'\xa5' * 4
            self.assertEqual(run(op, 2), 1)
            self.assertEqual(mem[300:303], b'3\xa5\xa5')
            mem[300] = 0xa5
            self.assertEqual(run(op, 4), -7)
            self.assertEqual(mem[300], 0xa5)
            self.assertEqual(run(op, 0, unit=0x1071AC0), -3)  # attribute 0: bit7 clear
        self.assertEqual(run(34, 1, cap=5), 1)  # capacity >= unit size
        with self.assertRaises(UnsupportedUipc):  # capacity < unit size: rejected
            run(34, 1, cap=3)
        self.assertEqual(bytes(state.raw), snapshot)

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

    def test_service_backup_read_multi_and_nread_multi(self):
        state = BK4PresetState(self.preset_raw)
        service = PresetBackedBackupService(state)
        mem = bytearray(1024)
        # units array at 200: [0x003e000b (1B), 0x00fa007c (4B), 0]
        struct.pack_into('<3I', mem, 200, 0x003e000b, 0x00fa007c, 0)
        # dst_ptrs array at 240: [400, 416]
        struct.pack_into('<2I', mem, 240, 400, 416)
        # op 5: Backup_read_multi(units_ptr=200, dst_ptrs_ptr=240)
        struct.pack_into('<8I', mem, 100, 5, 0, 2, BACKUP_SERVICE_QUEUE, 0, 0, 200, 240)

        ret = service.handle_uipc_sync_message(
            lambda a, s: bytes(mem[a:a+s]),
            lambda a, d: mem.__setitem__(slice(a, a+len(d)), d),
            100
        )
        self.assertEqual(ret, 0)
        self.assertEqual(struct.unpack_from('<i', mem, 104)[0], 2)
        self.assertEqual(mem[400:401], b'\x01')
        self.assertEqual(struct.unpack_from('<I', mem, 416)[0], 0x035c6000)

        # op 31: Backup_nread_multi(units_ptr=200, dst_ptrs_ptr=240, capacities_ptr=280)
        mem[400:424] = b'\x00' * 24
        struct.pack_into('<2I', mem, 280, 1, 4)
        struct.pack_into('<9I', mem, 100, 31, 0, 3, BACKUP_SERVICE_QUEUE, 0, 0, 200, 240, 280)
        ret = service.handle_uipc_sync_message(
            lambda a, s: bytes(mem[a:a+s]),
            lambda a, d: mem.__setitem__(slice(a, a+len(d)), d),
            100
        )
        self.assertEqual(ret, 0)
        self.assertEqual(struct.unpack_from('<i', mem, 104)[0], 2)
        self.assertEqual(mem[400:401], b'\x01')
        self.assertEqual(struct.unpack_from('<I', mem, 416)[0], 0x035c6000)

    def test_service_backup_get_datasize_multi_and_write_multi_and_sync(self):
        state = BK4PresetState(self.preset_raw)
        service = PresetBackedBackupService(state)
        mem = bytearray(1024)
        # units array at 200: [0x003e000b (1B), 0x00fa007c (4B), 0]
        struct.pack_into('<3I', mem, 200, 0x003e000b, 0x00fa007c, 0)
        # op 1: Backup_get_datasize_multi(units_ptr=200, sizes_ptr=240)
        struct.pack_into('<8I', mem, 100, 1, 0, 2, BACKUP_SERVICE_QUEUE, 0, 0, 200, 240)
        service.handle_uipc_sync_message(
            lambda a, s: bytes(mem[a:a+s]),
            lambda a, d: mem.__setitem__(slice(a, a+len(d)), d),
            100
        )
        self.assertEqual(struct.unpack_from('<i', mem, 104)[0], 5)
        self.assertEqual(struct.unpack_from('<2I', mem, 240), (1, 4))

        # op 10: Backup_write_multi(subsystem=0x3e, units_ptr=300, src_ptrs_ptr=320)
        struct.pack_into('<2I', mem, 300, 0x003e000b, 0)
        struct.pack_into('<I', mem, 320, 400)
        mem[400] = 0x77
        struct.pack_into('<9I', mem, 100, 10, 0, 3, BACKUP_SERVICE_QUEUE, 0, 0, 0x3e, 300, 320)
        service.handle_uipc_sync_message(
            lambda a, s: bytes(mem[a:a+s]),
            lambda a, d: mem.__setitem__(slice(a, a+len(d)), d),
            100
        )
        self.assertEqual(struct.unpack_from('<i', mem, 104)[0], 1)
        self.assertEqual(state.read_unit(0x003e000b), b'\x77')

        # op 14 / 15: Backup_sync_subsystem / Backup_sync_all
        for op in (14, 15):
            struct.pack_into('<7I', mem, 100, op, 0xffffffff, 1, BACKUP_SERVICE_QUEUE, 0, 0, 0x3e)
            service.handle_uipc_sync_message(
                lambda a, s: bytes(mem[a:a+s]),
                lambda a, d: mem.__setitem__(slice(a, a+len(d)), d),
                100
            )
            self.assertEqual(struct.unpack_from('<i', mem, 104)[0], 0)


    def test_load_default_selects_pdc_preset_and_checks_sha(self):
        rel = 'firmware/extracted_a6400/firmware.tar_unpacked/0110_backup/SYSASTRA-DSLR/PDC/CX77700_UC2.bin'
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(bytes(256))
            with self.assertRaisesRegex(ValueError, 'Preset SHA-256 mismatch'):
                BK4PresetState.load_default(Path(tmp))

    def test_load_default_missing_raises_file_not_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                BK4PresetState.load_default(Path(tmp))

    def _uipc(self, state, mem, op, *args):
        service = PresetBackedBackupService(state)
        words = (op, 0, len(args) + 2, BACKUP_SERVICE_QUEUE, 0, 0) + args
        struct.pack_into('<%dI' % len(words), mem, 100, *words)
        service.handle_uipc_sync_message(lambda a, s: bytes(mem[a:a+s]),
                                        lambda a, d: mem.__setitem__(slice(a, a+len(d)), d), 100)
        return struct.unpack_from('<i', mem, 104)[0]

    def test_reset_op_18_live_unit_and_errors(self):
        state = BK4PresetState(self.preset_raw)
        mem = bytearray(512)
        live = 0x1071B94  # attr 0x7c, size 1, reset copy 00 (a typical call)
        self.assertEqual(state.read_unit(live), b'\x00')
        state.write_unit(live, b'\x01')
        self.assertEqual(self._uipc(state, mem, 18, 0x107, live), 0)
        self.assertEqual(state.read_unit(live), b'\x00')
        snapshot = bytes(state.raw)
        self.assertEqual(self._uipc(state, mem, 18, 0x106, live), -4)       # subsystem != unit >> 16
        self.assertEqual(self._uipc(state, mem, 18, 0x107, 0x107fff0), -1)  # unit not found
        self.assertEqual(self._uipc(state, mem, 18, 0x107, 0x1071AC0), -1)   # attribute 0: no reset bits
        self.assertEqual(bytes(state.raw), snapshot)

    def test_reset_op_18_setting_attr_unit_resets_every_element_from_first_reset_bytes(self):
        state = BK4PresetState(self.preset_raw)
        mem = bytearray(512)
        unit = 0x1070394  # attr 0xc0, size 4, reset copy 00010101, 4 elements (unit 0x3E000C = 3)
        state.write_unit(unit, bytes.fromhex('11223344'))
        self.assertEqual(self._uipc(state, mem, 18, 0x107, unit), 0)
        self.assertEqual(state.read_unit(unit), bytes(4))  # loop re-reads the first reset element each pass

    def test_reset_subsystem_and_reset_all_ops_19_20(self):
        state = BK4PresetState(self.preset_raw)
        mem = bytearray(512)
        live = 0x1071B94
        state.write_unit(live, b'\x01')
        self.assertEqual(self._uipc(state, mem, 19, 0x107, 1), 0)
        self.assertEqual(state.read_unit(live), b'\x00')
        self.assertEqual(self._uipc(state, mem, 19, 5000, 1), -7)  # subsystem >= header count
        self.assertEqual(self._uipc(state, mem, 19, 0x107, 5), -7)  # mode outside 1..4
        state.write_unit(live, b'\x01')
        self.assertEqual(self._uipc(state, mem, 20, 1), 0)
        self.assertEqual(state.read_unit(live), b'\x00')
        self.assertEqual(self._uipc(state, mem, 20, 9), -7)

    def test_write_vsize_op_9(self):
        state = BK4PresetState(self.preset_raw)
        mem = bytearray(512)
        var, fixed = 0x3e0014, 0x3e000b  # var: size 1, vmax 4; fixed: size 1
        mem[300:304] = b'\xaa\xbb\xcc\xdd'
        self.assertEqual(self._uipc(state, mem, 9, 0x3e, var, 300, 3), 3)
        desc = state.search_id(var)
        self.assertEqual(desc.size, 3)
        self.assertEqual(state.read_unit(var), b'\xaa\xbb\xcc')
        self.assertEqual(self._uipc(state, mem, 9, 0x3e, var, 300, 5), -5)   # > vmax
        self.assertEqual(self._uipc(state, mem, 9, 0x3e, var, 300, 0), -1)   # size 0 on a variable unit
        self.assertEqual(self._uipc(state, mem, 9, 0x3e, fixed, 300, 2), -5)  # fixed unit, wrong size
        self.assertEqual(self._uipc(state, mem, 9, 0x3e, fixed, 300, 1), 1)
        self.assertEqual(state.read_unit(fixed), b'\xaa')
        self.assertEqual(self._uipc(state, mem, 9, 0x3d, fixed, 300, 1), -4)
        self.assertEqual(self._uipc(state, mem, 9, 0x3e, 0x3effff, 300, 1), -1)

    def test_write_op_8_returns_unit_size_and_errors(self):
        state = BK4PresetState(self.preset_raw)
        mem = bytearray(512)
        var, fixed = 0x3e0014, 0x3e000b
        mem[300:304] = b'\xaa\xbb\xcc\xdd'
        self.assertEqual(self._uipc(state, mem, 8, 0x3e, fixed, 300), 1)
        self.assertEqual(state.read_unit(fixed), b'\xaa')
        self.assertEqual(self._uipc(state, mem, 8, 0x3e, var, 300), -1)  # variable unit needs op 9
        self.assertEqual(self._uipc(state, mem, 8, 0x3d, fixed, 300), -4)
        self.assertEqual(self._uipc(state, mem, 8, 0x3e, 0x3effff, 300), -1)  # missing unit: -1, not an error

    def test_write_core_sharedcb_unit_writes_and_notes_unmodeled_notification(self):
        state = BK4PresetState(self.preset_raw)
        svc = PresetBackedBackupService(state)
        mem = bytearray(512)
        mem[300] = 0x5a
        cands = [0x3e0000 | i for i in range(0x40)]
        unit = next(u for u in cands if (d := state.search_id(u)) and d.attribute & 8
                    and d.size == 1 and not d.vmax and not d.attribute & 1)
        struct.pack_into('<9I', mem, 100, 8, 0, 5, BACKUP_SERVICE_QUEUE, 0, 0, 0x3e, unit, 300)
        svc.handle_uipc_sync_message(lambda a, s: bytes(mem[a:a+s]),
                                     lambda a, d: mem.__setitem__(slice(a, a+len(d)), d), 100)
        self.assertEqual(struct.unpack_from('<i', mem, 104)[0], 1)
        self.assertEqual(state.read_unit(unit), b'\x5a')
        self.assertIn('Backup_sharedcb_not_modeled', [e['type'] for e in svc.events])

    def test_read_rst_attr_op_37_and_pdt_stat_op_36(self):
        state = BK4PresetState(self.preset_raw)
        mem = bytearray(512)
        self.assertEqual(self._uipc(state, mem, 37, 0x1070394, 300), 4)
        self.assertEqual(bytes(mem[300:304]), bytes.fromhex('00010101'))
        self.assertEqual(self._uipc(state, mem, 37, 0x107ffff0, 300), -1)
        self.assertEqual(self._uipc(state, mem, 36, 300), 0)
        self.assertEqual(struct.unpack_from('<I', mem, 300)[0], 0x40)  # '4' << 4 + '0'
        self.assertEqual(struct.unpack_from('<I', mem, 304)[0], struct.unpack_from('<I', state.raw, 0x30)[0])
        self.assertEqual(bytes(mem[308:340]), bytes(state.raw[0xc0:0xe0]))

    def test_file_backed_ops_22_to_25_raise(self):
        state = BK4PresetState(self.preset_raw)
        for op in (22, 23, 24, 25):
            with self.assertRaises(UnsupportedUipc):
                self._uipc(state, bytearray(512), op, 1, 2, 3, 4)
