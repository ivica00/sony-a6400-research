"""Machine-ID and updater boot-contract checks (E0416)."""
import struct
import unittest
from pathlib import Path

from src.a6400.execution.machine_contract import (
    MACHINE_NAME,
    MachineContractError,
    UpdaterBootContract,
    recover_machine_descriptor,
)
from src.a6400.execution.nflasha_boot_set import NflashaBootSet

ROOT = Path(__file__).resolve().parents[1]
DUMPS = ROOT / 'artifacts/dumps/a6400-nflasha-readonly'
DUMPS_PRESENT = ((DUMPS / 'nflasha1-8323072.bin').is_file()
                 and (DUMPS / 'nflasha3-50331648.bin').is_file())
VIRTUAL_BASE = 0x60108000


def synthetic_kernel(*, machine_id=0x0DA9, name_offset=0x200, struct_offset=0x100,
                     size=0x800):
    image = bytearray(size)
    struct.pack_into('<I', image, 0, 0xE321F0D3)
    image[name_offset:name_offset + len(MACHINE_NAME)] = MACHINE_NAME
    name_vaddr = VIRTUAL_BASE + name_offset
    struct.pack_into('<I', image, struct_offset, machine_id)
    struct.pack_into('<I', image, struct_offset + 4, name_vaddr)
    return bytes(image)


class RecoverMachineDescriptorTests(unittest.TestCase):
    def test_recovers_observed_id_and_name_pointer(self):
        descriptor = recover_machine_descriptor(
            synthetic_kernel(), virtual_base=VIRTUAL_BASE, image_sha256='x' * 64)
        self.assertEqual(descriptor.machine_id, 0x0DA9)
        self.assertEqual(descriptor.name, 'ARM-CXD900X0')
        self.assertEqual(descriptor.struct_file_offset, 0x100)
        self.assertEqual(descriptor.name_file_offset, 0x200)
        self.assertEqual(descriptor.name_offset_in_struct, 4)
        self.assertEqual(descriptor.as_dict()['struct_vaddr'],
                         VIRTUAL_BASE + 0x100)

    def test_missing_name_is_an_error(self):
        with self.assertRaises(MachineContractError):
            recover_machine_descriptor(bytes(0x800), virtual_base=VIRTUAL_BASE,
                                       image_sha256='x' * 64)

    def test_implausible_id_is_an_error(self):
        image = bytearray(synthetic_kernel(machine_id=0))
        with self.assertRaises(MachineContractError):
            recover_machine_descriptor(bytes(image), virtual_base=VIRTUAL_BASE,
                                       image_sha256='x' * 64)

    def test_conflicting_ids_are_rejected_as_ambiguous(self):
        image = bytearray(synthetic_kernel())
        struct.pack_into('<I', image, 0x300, 0x0DAA)
        struct.pack_into('<I', image, 0x304, VIRTUAL_BASE + 0x200)
        with self.assertRaises(MachineContractError):
            recover_machine_descriptor(bytes(image), virtual_base=VIRTUAL_BASE,
                                       image_sha256='x' * 64)


@unittest.skipUnless(DUMPS_PRESENT, 'E0414 nflasha1/nflasha3 dumps not present')
class RealMachineContractTests(unittest.TestCase):
    def test_updater_contract_matches_the_observed_boot_inputs(self):
        boot_set = NflashaBootSet.from_evidence(ROOT, 'nflasha1')
        contract = UpdaterBootContract(boot_set)
        verification = contract.verify()
        self.assertEqual(verification['machine']['machine_id'], 0x0DA9)
        self.assertEqual(verification['machine']['name'], 'ARM-CXD900X0')
        self.assertEqual(verification['load_addresses'],
                         {'kernel_load': 0x00108000, 'initrd_load': 0x00700000,
                          'boot_params': 0x00103000})
        self.assertEqual(verification['kernel_raw_bytes'], 3581952)
        self.assertEqual(len(verification['memory_banks']), 2)
        self.assertEqual(verification['memory_banks'][0], [0, 0x40000000])
        self.assertEqual(verification['memory_banks'][1][0], 0x80000000)
        self.assertEqual(verification['atags']['address'], 0x00103000)
        self.assertEqual(len(verification['atags']['memory_banks']), 2)
        self.assertIn('console=ttyAM0,115200n8', verification['cmdline'])
        self.assertTrue(all(verification['checks'].values()))

    def test_cmdline_extra_prepends_init_and_replaces_default(self):
        boot_set = NflashaBootSet.from_evidence(ROOT, 'nflasha1')
        contract = UpdaterBootContract(boot_set, cmdline_extra='init=/bin/ash')
        self.assertTrue(contract.cmdline.startswith('init=/bin/ash'))
        self.assertEqual(contract.cmdline.count('init='), 1)
        self.assertNotIn('init=/sbin/init', contract.cmdline)
        self.assertIn(b'init=/bin/ash', contract.atags)

    def test_sony_override_payload_keeps_kemco_magic(self):
        boot_set = NflashaBootSet.from_evidence(ROOT, 'nflasha1')
        contract = UpdaterBootContract(boot_set, cmdline_extra='init=/bin/ash')
        self.assertTrue(contract.sony_payload.startswith(b'kemco '))
        self.assertIn(b'init=/bin/ash', contract.sony_payload)
        self.assertNotIn(b'init=/sbin/init', contract.sony_payload)
        self.assertEqual(contract.sony_payload[-1], 0)

    def test_main_kernel_carries_the_same_machine_id(self):
        boot_set = NflashaBootSet.from_evidence(ROOT, 'nflasha3')
        raw = boot_set.raw_kernel_image()
        descriptor = recover_machine_descriptor(
            raw, virtual_base=VIRTUAL_BASE,
            image_sha256=boot_set.kernel_file().sha256)
        self.assertEqual(descriptor.machine_id, 0x0DA9)
        self.assertEqual(descriptor.struct_file_offset, 0x3A85F4)
        self.assertEqual(descriptor.name_file_offset, 0x3424B9)
        # The known board function pointers follow the name word; they must resolve
        # inside the image (text evidence for the descriptor).
        self.assertGreaterEqual(len(descriptor.pointer_words), 3)


if __name__ == '__main__':
    unittest.main()
