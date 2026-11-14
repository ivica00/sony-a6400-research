"""Unit tests for BIONZ X sensor configuration table mapping and emulation."""
from __future__ import annotations

import struct
import unittest
from pathlib import Path

from project_paths import PROJECT_ROOT
from src.a6400.sensor import (
    DfeAppModel,
    DfeError,
    ImagerMmioBank,
    ImagerTableError,
    MmioWrite,
    analyze_avcam_imager,
    parse_dcv_psf,
    parse_dfe_app,
    parse_idt_ssboot,
    parse_sa_module,
    scan_sabin_tree,
)
from src.a6400.sensor.dfe_app import DFE_LINK_BASE, DFE_SRAM_BASE, DfeXdmacDescriptor
from src.a6400.sensor.imager_tables import ORIL_BASE
from src.a6400.sensor.sabin import SA_MAGIC, SabinParseError


class TestSabinParsers(unittest.TestCase):
    def test_parse_sa_module_valid_and_invalid(self) -> None:
        buf = bytearray(0x40)
        struct.pack_into("<5I", buf, 0, SA_MAGIC, 0x02000005, 1, 2, 0)
        buf[0x14:0x20] = b"SA_DCV__0x13"
        hdr = parse_sa_module(bytes(buf), "sa_dcv.bin")
        self.assertEqual(hdr.name_tag, "SA_DCV__0x13")
        self.assertEqual(hdr.magic, SA_MAGIC)

        bad = bytearray(buf)
        bad[0] = 0
        with self.assertRaises(SabinParseError):
            parse_sa_module(bytes(bad), "bad.bin")

    def test_parse_dcv_psf_valid(self) -> None:
        payload = b"\x01\x02\x03\x04" * 8
        buf = bytearray(0x40 + len(payload))
        buf[0:4] = b"IMX2"
        buf[4:8] = b"10\x00\x00"
        buf[16:31] = b"SAL50 CeGenCh_3"
        buf[32:47] = b"20130607_130709"
        struct.pack_into("<4I", buf, 0x30, len(buf), 0, 0x00010003, 0x00040004)
        buf[0x40:] = payload
        hdr = parse_dcv_psf(bytes(buf), "dcv_psf_table_movie.bin")
        self.assertEqual(hdr.payload_size, len(payload))
        self.assertEqual(hdr.generator_tag, "SAL50 CeGenCh_3")

    def test_parse_idt_ssboot_valid(self) -> None:
        buf = bytearray(0x40)
        struct.pack_into("<8I", buf, 0, 0xB03F003D, 0x004F3442, 0x10080001, 0x40, 0x20, 0x40, 0x40, 0)
        hdr = parse_idt_ssboot(bytes(buf), "ssboot.bin")
        self.assertEqual(hdr.declared_size, 0x40)
        self.assertEqual(hdr.code_offset, 0x40)


class TestDfeAppModel(unittest.TestCase):
    def _make_synthetic_dfe(self) -> bytes:
        buf = bytearray(0x100)
        struct.pack_into("<4I", buf, 0, 0xEA000000, 0xE12FFF1E, 0xE28FC03B, 0xE12FFF1C)
        struct.pack_into("<2I", buf, 0x40, DFE_SRAM_BASE, DFE_LINK_BASE + 0xA1)
        buf[0x80:0x95] = b"DFE:XDMAC STATUS ERR "
        return bytes(buf)

    def test_parse_and_emulate_dfe_app(self) -> None:
        raw = self._make_synthetic_dfe()
        info = parse_dfe_app(raw)
        self.assertIn(DFE_SRAM_BASE, info.sram_regions)
        self.assertIn(DFE_LINK_BASE + 0xA1, info.entrypoints)

        model = DfeAppModel.from_bytes(raw)
        self.assertEqual(
            model.create_list([DfeXdmacDescriptor(0x1000, 0x2000, 512)]),
            1,
        )
        self.assertEqual(model.run_xdmac(), 512)
        header_count, header_flag = struct.unpack_from("<II", model.read_sram(DFE_SRAM_BASE, 8), 0)
        self.assertEqual((header_count, header_flag), (1, 1))

    def test_dfe_padding_and_bounds_errors(self) -> None:
        model = DfeAppModel.from_bytes(self._make_synthetic_dfe())
        with self.assertRaises(DfeError):
            model.run_xdmac()
        with self.assertRaises(DfeError):
            model.create_list([DfeXdmacDescriptor(0x1000, 0x2000, 7, padding_mode="cpu")])
        with self.assertRaises(DfeError):
            model.read_sram(DFE_SRAM_BASE - 4, 4)


class TestImagerMmioAndRealFirmware(unittest.TestCase):
    def test_mmio_bank_bounds_and_writes(self) -> None:
        bank = ImagerMmioBank()
        n = bank.apply_table([MmioWrite(ORIL_BASE, 0xFC0A1208, 0x12345678)])
        self.assertEqual(n, 1)
        self.assertEqual(bank.read32(0xFC0A1208), 0x12345678)
        with self.assertRaises(ImagerTableError):
            bank.write32(0xFC000000, 1)

    def test_real_a6400_sensor_tables_if_present(self) -> None:
        dev_dir = (
            PROJECT_ROOT
            / "firmware"
            / "extracted_a6400"
            / "firmware.tar_unpacked"
            / "0700_part_image"
            / "dev"
        )
        if not dev_dir.exists():
            self.skipTest("unpacked a6400 firmware not present")

        inv = scan_sabin_tree([dev_dir / "nflasha3_unpacked/sabin", dev_dir / "nflasha15_unpacked/sabin"])
        self.assertGreater(len(inv.sa_modules), 40)
        self.assertGreaterEqual(len(inv.dcv_tables), 3)
        self.assertEqual(len(inv.idt_ssboot), 3)

        dfe = parse_dfe_app((dev_dir / "nflasha3_unpacked/dfe_app.bin").read_bytes())
        self.assertEqual(dfe.size, 1956)
        self.assertEqual(len(dfe.error_strings), 5)

        avcam = analyze_avcam_imager((dev_dir / "nflasha3_unpacked/av-cam.bin").read_bytes())
        self.assertIn("IMX284E", avcam.imx_identifiers)
        self.assertGreater(len(avcam.geometries), 4)
        self.assertGreater(len(avcam.timing_entries), 10)
        self.assertIn("ZIMA_AVC/ZMA", avcam.active_encoder_engines)
        self.assertGreater(len(avcam.mmio_tables), 10)


if __name__ == "__main__":
    unittest.main()
