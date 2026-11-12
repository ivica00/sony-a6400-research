import struct
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from elftools.elf.elffile import ELFFile

from tools.research import build_debug_patch_module as builder


class ExportParsingTests(unittest.TestCase):
    def test_ksymtab_entries_contribute_the_exported_name(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'kallsyms'
            path.write_text(
                '60180020 T __probe_kernel_write\n'
                '60180020 W probe_kernel_write\n'
                '60479ac0 r __ksymtab_probe_kernel_write\n'
                '6047e852 r __kstrtab_probe_kernel_write\n', encoding='utf-8')
            exports = builder.exported_symbols(path)
        self.assertIn('probe_kernel_write', exports)
        self.assertIn('__probe_kernel_write', exports)


class CarrierPreparationTests(unittest.TestCase):
    @unittest.skipUnless(builder.CARRIER.is_file(), 'preserved carrier not present')
    def test_carrier_is_redirected_to_helper_init_and_exit(self):
        with TemporaryDirectory() as directory:
            output = Path(directory) / 'carrier_redirected.ko'
            receipt = builder.prepare_carrier(builder.CARRIER, output)
            self.assertEqual(receipt['retargeted_relocations'], 2)
            self.assertIn(('udif_devnodes', '__udif_devnodes'), receipt['renamed_imports'])
            with output.open('rb') as handle:
                elf = ELFFile(handle)
                module = elf.get_section_by_name('.gnu.linkonce.this_module')
                name = module.data()[12:40].split(b'\0')[0]
                self.assertEqual(name, b'a6400_dbg_patch')
                symbols = {symbol.name: symbol for symbol in
                           elf.get_section_by_name('.symtab').iter_symbols()}
                for entry in ('init_module', 'cleanup_module'):
                    self.assertEqual(symbols[entry]['st_shndx'], 'SHN_UNDEF')
                for carrier_entry in ('carrier_init_module', 'carrier_cleanup_module'):
                    self.assertNotEqual(symbols[carrier_entry]['st_shndx'], 'SHN_UNDEF')
                relocations = elf.get_section_by_name('.rel.gnu.linkonce.this_module')
                linked_symbols = elf.get_section(relocations['sh_link'])
                targets = {linked_symbols.get_symbol(reloc['r_info_sym']).name
                           for reloc in relocations.iter_relocations()}
                self.assertEqual(targets, {'init_module', 'cleanup_module'})


class ModuleSourceInvariantTests(unittest.TestCase):
    def test_patch_source_keeps_the_two_exact_descriptor_arrays(self):
        source = (builder.ROOT / 'tools/native_camera/a6400_dbg_patch.c').read_text(encoding='utf-8')
        self.assertIn('0x4d, 0x00, 0x53, 0x00, 0x46, 0x00, 0x54, 0x00', source)
        self.assertIn('0x31, 0x00, 0x30, 0x00, 0x30, 0x00', source)   # MSFT100
        self.assertIn('0x32, 0x00, 0x30, 0x00, 0x00, 0x00', source)   # MSFT20 + NUL
        self.assertIn('0x02, 0x00', source)                            # vendor code 0x02
        self.assertIn('probe_kernel_write', source)
        self.assertIn('license=GPL', source)

    @unittest.skipUnless(
        (builder.ROOT / 'artifacts/native/a6400-dbg-patch-e0403/final/a6400_dbg_patch.ko').is_file(),
        'built helper module not present')
    def test_built_module_is_audited_and_named(self):
        module = builder.ROOT / 'artifacts/native/a6400-dbg-patch-e0403/final/a6400_dbg_patch.ko'
        receipt = builder.audit(module, builder.CARRIER, {})
        self.assertEqual(receipt['audit'], 'ok')
        self.assertIn('probe_kernel_write', receipt['undefined_symbols'])
        with module.open('rb') as handle:
            modinfo = ELFFile(handle).get_section_by_name('.modinfo').data()
        self.assertIn(b'license=GPL', modinfo)


if __name__ == '__main__':
    unittest.main()
