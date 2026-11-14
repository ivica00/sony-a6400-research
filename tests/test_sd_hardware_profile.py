"""Tests for original SD host hardware context and register contracts."""
import io
import json
import struct
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from elftools.elf.elffile import ELFFile
from project_paths import PROJECT_ROOT
from tools.research.rea_wsl_batch import checked_input
from tools.research.sd_hardware_profile import DRIVER, main

DRIVER_SHA256 = 'b150c666ee29567e920e156b8a5def8307d04c51b799956cdd74fcf5c55211cf'


class TestSdHardwareProfile(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (PROJECT_ROOT / DRIVER).is_file():
            raise unittest.SkipTest('Local firmware SD driver not present')
        raw = checked_input(PROJECT_ROOT, DRIVER, DRIVER_SHA256)
        cls.elf = ELFFile(io.BytesIO(raw))
        cls.symbols = {s.name: s for s in cls.elf.get_section_by_name('.symtab').iter_symbols()}
        cls.text = cls.elf.get_section_by_name('.text').data()

    def test_hardware_and_synchronization_symbols(self):
        expected = {
            'mmc_os_init_sem_long': 0x11bc,
            'mmc_os_lock_sem_long': 0x121c,
            'mmc_os_unlock_sem_long': 0x1278,
            'mmc_hwconf_led_on': 0x8ab8,
            'mmc_hwconf_led_off': 0x8adc,
            'mmc_hw_exec_command': 0xd754,
            'mmc_hw_lock_sem': 0xc404,
            'mmc_hw_unlock_sem': 0xc3ec,
            'mmc_hw_init': 0xc8f0,
            'mmc_hw_open': 0xdff4,
            'mmc_hw_get_ops_info': 0xe2f4,
            'set_r1_cmd': 0x12b0c,
            'mmc_hw_wrapper_get_ops': 0x18840,
            'mmc_hw_wrapper_lock_sem': 0x18dfc,
            'mmc_hw_wrapper_unlock_sem': 0x18e70,
            'mmc_hw_uhs2_get_ops_info': 0x1dfdc,
        }
        for name, addr in expected.items():
            self.assertIn(name, self.symbols)
            self.assertEqual(self.symbols[name]['st_value'], addr)

    def test_ip_func_ops_in_bss(self):
        ip_sym = self.symbols['ip_func_ops']
        self.assertEqual(ip_sym['st_value'], 0xfa8)
        self.assertEqual(ip_sym['st_size'], 48)

    def test_mmc_hw_lock_adds_0x4c(self):
        # 0xc410: add r0, r0, #0x4c (0xe280004c)
        ins = struct.unpack_from('<I', self.text, 0xc410)[0]
        self.assertEqual(ins, 0xe280004c)

    def test_mmc_hw_unlock_adds_0x4c(self):
        # 0xc3f8: add r0, r0, #0x4c (0xe280004c)
        ins = struct.unpack_from('<I', self.text, 0xc3f8)[0]
        self.assertEqual(ins, 0xe280004c)

    def test_physical_mmio_base(self):
        phys_base = struct.unpack_from('<I', self.text, 0xcb34)[0]
        self.assertEqual(phys_base, 0xf2a00000)

    def test_sdhci_present_state_register_offset(self):
        # 0xd7e0: mov r1, #0x2c (0xe3a0102c)
        ins = struct.unpack_from('<I', self.text, 0xd7e0)[0]
        self.assertEqual(ins, 0xe3a0102c)

    def test_report_generation(self):
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / 'artifacts') as td:
            sub = Path(td) / 'sub'
            rel = sub.relative_to(PROJECT_ROOT)
            with mock.patch('sys.argv', ['sd_hardware_profile', '--report-dir', str(rel)]):
                main()
            report_file = sub / 'report.json'
            self.assertTrue(report_file.exists())
            data = json.loads(report_file.read_text(encoding='utf-8'))
            self.assertEqual(data['status'], 'verified')
            self.assertEqual(data['hardware_registers']['sdhci_physical_base'], '0xf2a00000')
            self.assertEqual(data['host_hw_layout']['total_size'], '0xd0')


if __name__ == '__main__':
    unittest.main()
