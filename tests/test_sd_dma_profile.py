"""Tests for SD DMA scatter-gather buffer transfer contract and ADMA2 descriptors."""
import io
import json
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from elftools.elf.elffile import ELFFile
from project_paths import PROJECT_ROOT
from tools.research.rea_wsl_batch import checked_input
from tools.research.sd_dma_profile import MCMN_DRIVER, MMC_DRIVER, main

MMC_SHA256 = 'b150c666ee29567e920e156b8a5def8307d04c51b799956cdd74fcf5c55211cf'
MCMN_SHA256 = 'c18e8457cbb8dd993d649d393490de32225cd419d546270b8a0d00af6f027d7b'


class TestSdDmaProfile(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (PROJECT_ROOT / MMC_DRIVER).is_file() or not (PROJECT_ROOT / MCMN_DRIVER).is_file():
            raise unittest.SkipTest('Local firmware SD drivers not present')
        mmc_raw = checked_input(PROJECT_ROOT, MMC_DRIVER, MMC_SHA256)
        mcmn_raw = checked_input(PROJECT_ROOT, MCMN_DRIVER, MCMN_SHA256)
        cls.mmc_elf = ELFFile(io.BytesIO(mmc_raw))
        cls.mcmn_elf = ELFFile(io.BytesIO(mcmn_raw))
        cls.mmc_sym_list = [(s.name, s['st_value']) for s in cls.mmc_elf.get_section_by_name('.symtab').iter_symbols()]
        cls.mcmn_sym_list = [(s.name, s['st_value']) for s in cls.mcmn_elf.get_section_by_name('.symtab').iter_symbols()]
        cls.mmc_text = cls.mmc_elf.get_section_by_name('.text').data()
        cls.mcmn_text = cls.mcmn_elf.get_section_by_name('.text').data()

    def test_dma_adapter_symbols_exist(self):
        expected = [
            ('list_count', 0x1e8c),
            ('get_next', 0x1ea0),
            ('reset_list_ptr', 0x1ed8),
            ('mmc_single_scatter_list', 0x2090),
            ('list_count', 0x25cc),
            ('get_next', 0x25e0),
            ('reset_list_ptr', 0x2688),
            ('mmc_hw_exec_command', 0xd754),
        ]
        for item in expected:
            self.assertIn(item, self.mmc_sym_list)

    def test_mcmn_scatterlist_symbols_exist(self):
        expected = [
            ('mcmnd_api_makescatterlist', 0x2d0),
            ('mcmnd_api_releasescatterlist', 0x2bc),
            ('mcmnd_scatter_makescatterlist', 0xd5cc),
            ('mcmnd_scatter_releasescatterlist', 0xd7ac),
        ]
        for item in expected:
            self.assertIn(item, self.mcmn_sym_list)

    def test_single_scatter_list_stores_state(self):
        # 0x209c: stm r1, {r2, r3} (0xe881000c)
        ins = struct.unpack_from('<I', self.mmc_text, 0x209c)[0]
        self.assertEqual(ins, 0xe881000c)

    def test_adma2_end_bit_set(self):
        # 0xd910: orr r2, r2, #2 (0xe3822002)
        ins = struct.unpack_from('<I', self.mmc_text, 0xd910)[0]
        self.assertEqual(ins, 0xe3822002)

    def test_sdhci_adma_address_reg(self):
        # 0xd924: mov r1, #0x58 (0xe3a01058)
        ins = struct.unpack_from('<I', self.mmc_text, 0xd924)[0]
        self.assertEqual(ins, 0xe3a01058)

    def test_report_generation(self):
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / 'artifacts') as td:
            sub = Path(td) / 'sub'
            rel = sub.relative_to(PROJECT_ROOT)
            with mock.patch('sys.argv', ['sd_dma_profile', '--report-dir', str(rel)]):
                main()
            report_file = sub / 'report.json'
            self.assertTrue(report_file.exists())
            data = json.loads(report_file.read_text(encoding='utf-8'))
            self.assertEqual(data['status'], 'verified')
            self.assertIn('step_3_adma2_programming', data['scatterlist_memory_pipeline'])


if __name__ == '__main__':
    unittest.main()
