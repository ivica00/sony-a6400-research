"""Unit tests for the SDHCI ADMA2 host controller disk sector bridge."""
import hashlib
import json
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from project_paths import PROJECT_ROOT
from tools.research.sdhci_bridge import (
    ADMA2_ATTR_ACT_TRANSFER,
    ADMA2_ATTR_END,
    ADMA2_ATTR_VALID,
    INT_STATUS_CMD_COMPLETE,
    INT_STATUS_TRANSFER_COMPLETE,
    MemorySectorSource,
    PhysicalVolumeSource,
    SectorSource,
    SDHCI_ADMA_ADDRESS,
    SDHCI_ARGUMENT,
    SDHCI_BLOCK_COUNT,
    SDHCI_BLOCK_SIZE,
    SDHCI_COMMAND,
    SDHCI_INT_STATUS,
    SDHCI_PRESENT_STATE,
    SDHCI_TRANSFER_MODE,
    SdhciController,
    main,
)


class TestSdhciBridge(unittest.TestCase):
    def setUp(self):
        # 16 sectors of recognizable synthetic test data (exactly 512 bytes each)
        self.sectors = {
            i: (f'SECTOR_{i:04d}_'.encode('ascii') * 32) + (b'PAD_' * 32)
            for i in range(16)
        }
        self.source = MemorySectorSource(self.sectors, total_sectors=1024)
        self.ram = bytearray(64 * 1024)  # 64 KiB test RAM
        self.controller = SdhciController(self.ram, self.source)

    def test_register_read_write_widths(self):
        # 16-bit block size
        self.controller.write_reg(SDHCI_BLOCK_SIZE, 512, 2)
        self.assertEqual(self.controller.read_reg(SDHCI_BLOCK_SIZE, 2), 512)

        # 32-bit argument
        self.controller.write_reg(SDHCI_ARGUMENT, 0x12345678, 4)
        self.assertEqual(self.controller.read_reg(SDHCI_ARGUMENT, 4), 0x12345678)

        # 8-bit host control
        self.controller.write_reg(0x28, 0xab, 1)
        self.assertEqual(self.controller.read_reg(0x28, 1), 0xab)

    def test_adma2_single_block_read_cmd17(self):
        adma_phys = 0x1000
        dest_phys = 0x2000

        # Descriptor: 512 bytes, Valid | Transfer | End (0x23)
        attr_len = (512 << 16) | ADMA2_ATTR_VALID | ADMA2_ATTR_ACT_TRANSFER | ADMA2_ATTR_END
        struct.pack_into('<II', self.ram, adma_phys, attr_len, dest_phys)

        self.controller.write_reg(SDHCI_ADMA_ADDRESS, adma_phys, 4)
        self.controller.write_reg(SDHCI_BLOCK_SIZE, 512, 2)
        self.controller.write_reg(SDHCI_BLOCK_COUNT, 1, 2)
        self.controller.write_reg(SDHCI_ARGUMENT, 3, 4)  # LBA 3
        self.controller.write_reg(SDHCI_TRANSFER_MODE, 0x10, 2)
        self.controller.write_reg(SDHCI_COMMAND, 0x1120, 2)  # CMD17 trigger

        # Verify interrupt status
        int_status = self.controller.read_reg(SDHCI_INT_STATUS, 4)
        self.assertEqual(int_status, INT_STATUS_CMD_COMPLETE | INT_STATUS_TRANSFER_COMPLETE)

        # Verify data copied to dest_phys matches sector 3
        transferred = bytes(self.ram[dest_phys:dest_phys + 512])
        self.assertEqual(transferred, self.sectors[3])

    def test_adma2_multi_block_read_cmd18(self):
        adma_phys = 0x1000
        dest_seg1 = 0x2000
        dest_seg2 = 0x2400

        # Descriptor 0: 512 bytes, Valid | Transfer (0x21) -> LBA 5
        attr_len_0 = (512 << 16) | ADMA2_ATTR_VALID | ADMA2_ATTR_ACT_TRANSFER
        struct.pack_into('<II', self.ram, adma_phys + 0, attr_len_0, dest_seg1)

        # Descriptor 1: 1024 bytes (2 sectors), Valid | Transfer | End (0x23) -> LBA 6, 7
        attr_len_1 = (1024 << 16) | ADMA2_ATTR_VALID | ADMA2_ATTR_ACT_TRANSFER | ADMA2_ATTR_END
        struct.pack_into('<II', self.ram, adma_phys + 8, attr_len_1, dest_seg2)

        self.controller.write_reg(SDHCI_ADMA_ADDRESS, adma_phys, 4)
        self.controller.write_reg(SDHCI_BLOCK_SIZE, 512, 2)
        self.controller.write_reg(SDHCI_BLOCK_COUNT, 3, 2)
        self.controller.write_reg(SDHCI_ARGUMENT, 5, 4)  # Start LBA 5
        self.controller.write_reg(SDHCI_TRANSFER_MODE, 0x30, 2)
        self.controller.write_reg(SDHCI_COMMAND, 0x1220, 2)  # CMD18 trigger

        # Verify seg 1 received sector 5
        self.assertEqual(bytes(self.ram[dest_seg1:dest_seg1 + 512]), self.sectors[5])
        # Verify seg 2 received sector 6 and 7
        self.assertEqual(bytes(self.ram[dest_seg2:dest_seg2 + 512]), self.sectors[6])
        self.assertEqual(bytes(self.ram[dest_seg2 + 512:dest_seg2 + 1024]), self.sectors[7])

    def test_adma2_rejects_unaligned_transfer_length(self):
        adma_phys = 0x1000
        dest_phys = 0x2000

        # Unaligned length: 500 bytes (not multiple of 512)
        attr_len = (500 << 16) | ADMA2_ATTR_VALID | ADMA2_ATTR_ACT_TRANSFER | ADMA2_ATTR_END
        struct.pack_into('<II', self.ram, adma_phys, attr_len, dest_phys)

        self.controller.write_reg(SDHCI_ADMA_ADDRESS, adma_phys, 4)
        self.controller.write_reg(SDHCI_ARGUMENT, 0, 4)
        with self.assertRaises(ValueError):
            self.controller.write_reg(SDHCI_COMMAND, 0x1120, 2)

    def test_physical_volume_source_is_read_only(self):
        # Ensure SectorSource and PhysicalVolumeSource expose no write methods
        self.assertFalse(hasattr(SectorSource, 'write_sectors'))
        self.assertFalse(hasattr(PhysicalVolumeSource, 'write_sectors'))
        self.assertFalse(hasattr(MemorySectorSource, 'write_sectors'))

    def test_report_generation(self):
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / 'artifacts') as td:
            sub = Path(td) / 'sub'
            rel = sub.relative_to(PROJECT_ROOT)
            with mock.patch('sys.argv', ['sdhci_bridge', '--report-dir', str(rel)]):
                main()
            report_file = sub / 'report.json'
            self.assertTrue(report_file.exists())
            data = json.loads(report_file.read_text(encoding='utf-8'))
            self.assertEqual(data['status'], 'verified')
            self.assertEqual(data['controller_base_phys'], '0xf2a00000')
            self.assertEqual(data['cmd17_single_block']['bytes_transferred'], 512)


if __name__ == '__main__':
    unittest.main()
