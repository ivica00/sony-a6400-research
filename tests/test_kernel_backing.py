"""Constructed + real-dump checks for the kernel-backed Unicorn mapping (E0415)."""
import struct
import unittest
from pathlib import Path

import unicorn
from unicorn import UC_ARCH_ARM, UC_MODE_ARM, Uc

from src.a6400.execution.kernel_backing import (
    ARM_IMAGE_FIRST_WORD,
    KERNEL_IMAGE_BYTES,
    KERNEL_IMAGE_SHA256,
    KERNEL_VIRTUAL_BASE,
    KernelBacking,
    KernelBackingError,
    KernelImage,
    KernelSymbolTable,
)

ROOT = Path(__file__).resolve().parents[1]
DUMP = ROOT / 'artifacts/dumps/a6400-nflasha-readonly/nflasha3-50331648.bin'


def synthetic_kernel(size=0x2000, banner_offset=0x100):
    raw = bytearray(size)
    struct.pack_into('<I', raw, 0, ARM_IMAGE_FIRST_WORD)
    raw[banner_offset:banner_offset + 64] = b'Linux version 3.0.27_nl-rt106+ (test)\x00' + bytes(20)
    return bytes(raw)


class KernelImageTests(unittest.TestCase):
    def test_layout_and_bounds(self):
        image = KernelImage(synthetic_kernel(), virtual_base=0x60100000)
        self.assertEqual(image.virtual_base, 0x60100000)
        self.assertEqual(image.banner_offset(), 0x100)
        self.assertEqual(image.bytes_at(0x60100100, 13), b'Linux version')
        with self.assertRaises(KernelBackingError):
            image.bytes_at(0x600FFFFF, 4)
        with self.assertRaises(KernelBackingError):
            image.bytes_at(0x60100000, 0x2001)

    def test_non_kernel_bytes_are_rejected(self):
        with self.assertRaises(KernelBackingError):
            KernelImage(bytes(0x2000))
        with self.assertRaises(KernelBackingError):
            KernelImage(bytes(0x100))

    def test_mapping_into_unicorn_reads_back_the_image(self):
        image = KernelImage(synthetic_kernel(), virtual_base=0x60100000)
        uc = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        ranges = image.map_into(uc)
        self.assertTrue(ranges)
        self.assertEqual(uc.mem_read(0x60100000, 4), struct.pack('<I', ARM_IMAGE_FIRST_WORD))
        self.assertEqual(bytes(uc.mem_read(0x60100100, 13)), b'Linux version')

    def test_symbol_table_semantics(self):
        table = KernelSymbolTable({'alpha': 0x60100100, 'beta': 0x60100200,
                                   'gamma': 0x60100300})
        self.assertEqual(len(table), 3)
        self.assertEqual(table.address('beta'), 0x60100200)
        self.assertEqual(table.names_matching('a', limit=2), ['alpha', 'beta'])
        self.assertEqual(table.span('alpha'), 0x100)
        with self.assertRaises(KernelBackingError):
            table.address('missing')
        with self.assertRaises(KernelBackingError):
            KernelSymbolTable({})

    def test_backing_verification_on_synthetic_symbols(self):
        image = KernelImage(synthetic_kernel(), virtual_base=0x60100000)
        symbols = KernelSymbolTable({'linux_banner': 0x60100100, '_stext': 0x60100000,
                                     '_etext': 0x60101000})
        backing = KernelBacking(image, symbols)
        report = backing.verify()
        self.assertTrue(report['linux_banner_symbol_matches_file'])
        self.assertTrue(report['text_range_valid'])
        self.assertEqual(backing.resolve('_etext'), 0x60101000)


@unittest.skipUnless(DUMP.is_file(), 'nflasha3 read-only dump not present')
class RealKernelBackingTests(unittest.TestCase):
    def setUp(self):
        self.backing = KernelBacking.from_evidence(ROOT)

    def test_identity_and_observed_layout(self):
        report = self.backing.verify()
        self.assertEqual(report['sha256'], KERNEL_IMAGE_SHA256)
        self.assertEqual(report['bytes'], KERNEL_IMAGE_BYTES)
        self.assertTrue(report['linux_banner_symbol_matches_file'])
        self.assertTrue(report['text_range_valid'])
        self.assertGreater(len(self.backing.symbols), 20_000)
        self.assertEqual(report['symbols']['_stext'], 0x60108160)
        self.assertEqual(report['symbols']['_etext'], 0x6048D024)
        self.assertEqual(report['symbols']['linux_banner'], 0x603C8028)
        self.assertIn('Linux version 3.0.27_nl-rt106+', report['linux_banner_string'])

    def test_usb_gadgetcore_symbol_is_resolved_from_the_live_table(self):
        address = self.backing.resolve('usb_gadgetcore_register_driver')
        self.assertEqual(address, 0x602B8610)
        self.assertTrue(self.backing.image.virtual_base <= address
                        < self.backing.image.virtual_end)
        binding = self.backing.module_harness_binding(('usb_gadgetcore_register_driver',))
        self.assertEqual(binding['usb_gadgetcore_register_driver']['address'], address)

    def test_kernel_image_maps_at_its_virtual_base_in_unicorn(self):
        uc = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        receipt = self.backing.map_into(uc)
        self.assertEqual(receipt['virtual_base'], KERNEL_VIRTUAL_BASE)
        self.assertEqual(bytes(uc.mem_read(0x603C8028, 13)), b'Linux version')
        banner = self.backing.read_symbol('linux_banner', 13)
        self.assertEqual(banner, b'Linux version')
        instructions = self.backing.disassemble_symbol('usb_gadgetcore_register_driver', 4)
        self.assertTrue(instructions)
        self.assertTrue(all(line.startswith('0x602b') for line in instructions))


if __name__ == '__main__':
    unittest.main()
