"""Loader checks with constructed ELF data, independent of proprietary firmware."""
import contextlib
import io
import struct
import unittest
from unittest.mock import patch

from legacy.elf_layout import load_span, symbol_relocation
from legacy.cxd90045_hle_emulator import CXD90045_HLE_Emulator, RAM_BASE
from legacy.execution_audit import UnsupportedBehavior
from tools.research.elf_inventory import inspect_elf, summarize
from project_paths import PROJECT_ROOT


def fixture_elf(path):
    # ELF32 little-endian ARM ET_DYN, one loadable segment at nonzero vaddr.
    ident = b'\x7fELF' + bytes([1, 1, 1]) + bytes(9)
    header = struct.pack('<HHIIIIIHHHHHH', 3, 40, 1, 0x10000, 52, 0,
                         0x5000000, 52, 32, 1, 40, 0, 0)
    program = struct.pack('<IIIIIIII', 1, 0x1000, 0x10000, 0, 4, 0x2000, 5, 0x1000)
    path.write_bytes((ident + header + program).ljust(0x1000, b'\0') + b'ABCD')


class LayoutTests(unittest.TestCase):
    def test_nonzero_segment_base(self):
        self.assertEqual(load_span([{'p_vaddr': 0x10123, 'p_filesz': 4,
                                    'p_memsz': 0x2000}], 0x30000000),
                         (0x30010000, 0x3000))

    def test_invalid_segments(self):
        for segments in ([], [{'p_vaddr': 0, 'p_filesz': 8, 'p_memsz': 4}]):
            with self.assertRaises(ValueError):
                load_span(segments, 0x30000000)

    def test_addends_and_thumb_state(self):
        self.assertEqual(symbol_relocation(0x1000, 0x24), 0x1024)
        self.assertEqual(symbol_relocation(0x1001, 3, True), 0x1003)
        self.assertEqual(symbol_relocation(0x1001, 3, False), 0x1004)
        self.assertEqual(symbol_relocation(0xfffffff0, 0x30), 0x20)


class LoaderTests(unittest.TestCase):
    def setUp(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.emu = CXD90045_HLE_Emulator(mode='strict')
        self.path = PROJECT_ROOT / 'artifacts/tests/nonzero-vaddr.elf'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fixture_elf(self.path)

    def test_nonzero_vaddr_and_zero_fill(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.emu.load_elf_module(str(self.path), 0x30000000)
        self.assertEqual(bytes(self.emu.mu.mem_read(0x30010000, 4)), b'ABCD')
        self.assertEqual(bytes(self.emu.mu.mem_read(0x30011000, 4)), bytes(4))
        self.assertEqual(self.emu.loaded_modules[self.path.name]['mapped_address'], 0x30010000)

    def test_failure_unmaps_partial_module(self):
        original = self.emu.symbols.copy()
        with patch.object(self.emu, 'apply_relocations', side_effect=UnsupportedBehavior('fixture')):
            with self.assertRaises(UnsupportedBehavior):
                self.emu.load_elf_module(str(self.path), 0x30000000)
        self.assertEqual(self.emu.symbols, original)
        self.assertNotIn(self.path.name, self.emu.loaded_modules)
        with self.assertRaises(Exception):
            self.emu.mu.mem_read(0x30010000, 4)
        with contextlib.redirect_stdout(io.StringIO()):
            self.emu.load_elf_module(str(self.path), 0x30000000)

    def test_rel_addend_reaches_memory(self):
        class Symbol(dict):
            name = 'fixture_data'
        symbol = Symbol(st_info={'type': 'STT_OBJECT'})
        class Symbols:
            def get_symbol(self, index):
                return symbol
        class Relocations:
            name = '.rel.dyn'
            def iter_relocations(self):
                return iter([{'r_info_type': 2, 'r_offset': 0, 'r_info_sym': 1}])
        class ELF:
            def iter_sections(self):
                return iter([Relocations()])
            def get_section_by_name(self, name):
                return Relocations() if name == '.rel.dyn' else None
        self.emu.symbols['fixture_data'] = 0x12340000
        self.emu.mu.mem_write(RAM_BASE, struct.pack('<I', 0x24))
        with patch('elftools.elf.relocation.RelocationSection', Relocations):
            self.emu.apply_relocations(ELF(), RAM_BASE, Symbols())
        self.assertEqual(struct.unpack('<I', self.emu.mu.mem_read(RAM_BASE, 4))[0], 0x12340024)

    def test_inventory_recognizes_fixture(self):
        entry = inspect_elf(self.path)
        self.assertEqual(entry['machine'], 'EM_ARM')
        self.assertEqual(entry['segments'][0]['p_vaddr'], 0x10000)
        self.assertEqual(summarize([entry])['elf_count'], 1)
