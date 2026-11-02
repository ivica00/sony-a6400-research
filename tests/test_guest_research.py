"""Static research helpers must preserve guest path and address semantics."""
import struct
import unittest

from tools.research.guest_layout import canonical, resolve_guest, process_plan
from tools.research.startup_trace import decode_block, file_to_va, plt_symbols


class GuestPathTests(unittest.TestCase):
    def setUp(self):
        self.nodes = {'/': {'kind': 'directory'}, '/lib': {'kind': 'directory'},
                      '/lib/ld.so': {'kind': 'symlink', 'target': 'ld-version.so'},
                      '/lib/ld-version.so': {'kind': 'file'},
                      '/alias': {'kind': 'symlink', 'target': '/lib'}}

    def test_relative_and_component_links(self):
        result = resolve_guest(self.nodes, '//alias/ld.so')
        self.assertEqual(result['status'], 'resolved')
        self.assertEqual(result['path'], '/lib/ld-version.so')
        self.assertEqual(len(result['chain']), 2)

    def test_cycle_and_limit(self):
        self.nodes['/a'] = {'kind': 'symlink', 'target': '/b'}
        self.nodes['/b'] = {'kind': 'symlink', 'target': '/a'}
        with self.assertRaises(ValueError):
            resolve_guest(self.nodes, '/a')
        with self.assertRaises(ValueError):
            resolve_guest(self.nodes, '/alias/ld.so', max_links=0)

    def test_missing_and_not_directory(self):
        self.assertEqual(resolve_guest(self.nodes, '/absent')['status'], 'missing')
        self.assertEqual(resolve_guest(self.nodes, '/lib/ld-version.so/child')['status'], 'not_directory')

    def test_root_normalization(self):
        self.assertEqual(canonical('//lib/../lib/ld.so'), '/lib/ld.so')

    def test_parent_component_is_processed_after_link(self):
        self.nodes['/lib/nested'] = {'kind': 'directory'}
        self.nodes['/deep'] = {'kind': 'symlink', 'target': '/lib/nested'}
        result = resolve_guest(self.nodes, '/deep/../ld.so')
        self.assertEqual(result['path'], '/lib/ld-version.so')
        self.assertEqual(result['status'], 'resolved')

    def test_plan_reports_missing_dependency(self):
        self.nodes['/app'] = {'kind': 'file', 'extracted_path': 'local-app'}
        record = {'path': 'local-app', 'sha256': 'fixture', 'interpreter': '//lib/ld.so',
                  'needed': ['missing.so'], 'tls': False, 'relocations': {}, 'initializers': []}
        plan = process_plan({'nodes': self.nodes}, [record], '/app')
        self.assertEqual(plan['status'], 'static_candidate_plan_only')
        self.assertTrue(any(x.get('needed') == 'missing.so' for x in plan['missing']))


class FakeELF:
    def iter_segments(self):
        return iter([{'p_type': 'PT_LOAD', 'p_vaddr': 0x1000, 'p_offset': 0, 'p_filesz': 64}])


class StaticDecodeTests(unittest.TestCase):
    def test_offset_translation(self):
        self.assertEqual(file_to_va(FakeELF(), 8), 0x1008)
        self.assertIsNone(file_to_va(FakeELF(), 80))

    def test_thumb_literal_pc_alignment(self):
        data = struct.pack('<HHI', 0x4800, 0x4770, 0x1008) + b'hello\0'
        data = data.ljust(64, b'\0')
        row = decode_block(FakeELF(), data, 0x1001, 4)[0]
        self.assertEqual(row['literal_address'], 0x1004)
        self.assertEqual(row['literal_string'], 'hello')

    def test_plt_symbol_requires_matching_relocation_slot(self):
        class Symbol:
            name = 'dlopen'
        class Symbols:
            def get_symbol(self, index):
                return Symbol()
        class Relocations(dict):
            def iter_relocations(self):
                return iter([{'r_offset': 0x1018, 'r_info_sym': 1, 'r_info_type': 22}])
        class PLT(dict):
            def data(self):
                return struct.pack('<III', 0xe28fc000, 0xe28cc000, 0xe59cf010)
        class ELF:
            def get_section_by_name(self, name):
                return PLT(sh_addr=0x1000) if name == '.plt' else Relocations(sh_link=1)
            def get_section(self, index):
                return Symbols()
        self.assertEqual(plt_symbols(ELF()), {0x1000: 'dlopen'})


if __name__ == '__main__':
    unittest.main()
