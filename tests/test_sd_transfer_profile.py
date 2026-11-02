"""Test SD serialized transfer pipeline and card-state initialization contracts."""
import io
import json
import unittest

from elftools.elf.elffile import ELFFile
from project_paths import PROJECT_ROOT
from tools.research.rea_wsl_batch import checked_input
from tools.research.sd_transfer_profile import DRIVER

EXPECTED_DIGEST = 'b150c666ee29567e920e156b8a5def8307d04c51b799956cdd74fcf5c55211cf'


class SdTransferProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raw = checked_input(PROJECT_ROOT, DRIVER, EXPECTED_DIGEST)
        cls.elf = ELFFile(io.BytesIO(raw))
        cls.symbols = {s.name: s['st_value'] for s in cls.elf.get_section_by_name('.symtab').iter_symbols()}
        cls.text = cls.elf.get_section_by_name('.text').data()

    def test_pipeline_symbols_exist_at_expected_offsets(self):
        expected = {
            'serialized_transfer': 0x2760,
            'mmcd_blk_ioctl': 0x3fa0,
            'real_card_transfer': 0x53ac,
            'mmc_card_open': 0x9f70,
            'mmc_mmcp_detect_each': 0x14794,
            'mmc_mmcp_read': 0x17070,
            'mmc_hw_wrapper_lock_sem': 0x18dfc,
            'mmc_hw_wrapper_unlock_sem': 0x18e70,
        }
        for name, addr in expected.items():
            self.assertIn(name, self.symbols)
            self.assertEqual(self.symbols[name], addr, f'{name} mismatch')

    def test_lock_and_unlock_sem_read_hw_id_from_byte_zero(self):
        # 0x18dfc + 0xc: 0x18e08 ldrb r1, [r0] (load byte 0 = hw_id)
        # 0x18e70 + 0xc: 0x18e7c ldrb r1, [r0] (load byte 0 = hw_id)
        ldrb_r1_r0 = bytes.fromhex('0010d0e5')  # ldrb r1, [r0]
        self.assertEqual(self.text[0x18e08:0x18e0c], ldrb_r1_r0)
        self.assertEqual(self.text[0x18e7c:0x18e80], ldrb_r1_r0)

    def test_preparation_loads_state_zero_and_calls_lock_sem(self):
        # 0x16338: ldr r0, [r0]
        # 0x1633c: bl lock_sem
        ldr_r0_r0 = bytes.fromhex('000090e5')
        self.assertEqual(self.text[0x16338:0x1633c], ldr_r0_r0)

        # Relocation at 0x1633c must target mmc_hw_wrapper_lock_sem
        text_index = next(i for i, s in enumerate(self.elf.iter_sections()) if s.name == '.text')
        symtab = self.elf.get_section_by_name('.symtab')
        sym_names = [s.name for s in symtab.iter_symbols()]
        relocs = {}
        for section in self.elf.iter_sections():
            if section['sh_type'] == 'SHT_REL' and section['sh_info'] == text_index:
                for r in section.iter_relocations():
                    relocs[r['r_offset']] = sym_names[r['r_info_sym']]
        self.assertEqual(relocs.get(0x1633c), 'mmc_hw_wrapper_lock_sem')
        self.assertEqual(relocs.get(0x163c8), 'mmc_hw_wrapper_unlock_sem')

    def test_preparation_compares_rca_offsets(self):
        # 0x16348: ldr r3, [r4, #0x290] (selected RCA pointer)
        # 0x1634c: mov r5, #0x278 (card RCA offset)
        # 0x16350: ldrh r2, [r4, r5] (load card RCA)
        # 0x16354: ldrh r3, [r3] (load selected RCA)
        # 0x16358: cmp r2, r3
        # 0x1635c: beq 0x163cc (skip reselection if matching)
        self.assertEqual(self.text[0x16348:0x1634c], bytes.fromhex('903294e5'))  # ldr r3, [r4, #0x290]
        self.assertEqual(self.text[0x1634c:0x16350], bytes.fromhex('9e5fa0e3'))  # mov r5, #0x278
        self.assertEqual(self.text[0x16358:0x1635c], bytes.fromhex('030052e1'))  # cmp r2, r3


if __name__ == '__main__':
    unittest.main()
