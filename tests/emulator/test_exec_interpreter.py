import struct
import unittest

from src.a6400.execution.arm_atags import build_atags
from src.a6400.execution.unicorn_machine import UnicornMachine


class TraceRegisterTests(unittest.TestCase):
    def test_register_is_captured_at_pc(self):
        program = bytearray(0x100)
        words = [
            0xE321F0D3,  # msr cpsr_c,#0xd3 (machine head marker)
            0xE3A0002A,  # mov r0,#0x2a
            0xEAFFFFFE,  # b .
        ]
        for index, word in enumerate(words):
            struct.pack_into('<I', program, index * 4, word)
        machine = UnicornMachine(bytes(program), b'\x00' * 64,
                                 build_atags('console=ttyAM0', [(0, 0x40000000)]),
                                 machine_id=0x0DA9, instruction_limit=20,
                                 exclusive_patch=False, data_abort_delivery=False,
                                 trace_regs={0x00108008: ['r0']})
        report = machine.run()
        self.assertEqual(report['trace_reg_values']['0x108008'][0]['r0'], 0x2A)


class InterpreterElfTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from pathlib import Path
        from src.a6400.execution.nflasha_boot_set import NflashaBootSet
        from tests.emulator.test_cramfs_busybox import read_blocks, read_symlink
        root = Path(__file__).resolve().parents[2]
        cls.image = NflashaBootSet.from_evidence(root, 'nflasha1').read('boot/initrd.img')
        cls.lib = {}
        pos, end = 0x1F50, 0x1F50 + 0x2F4
        while pos + 12 <= end:
            a, b, c = struct.unpack_from('<III', cls.image, pos)
            nwords = c & 0x3F
            name = cls.image[pos + 12:pos + 12 + 4 * nwords].split(b'\x00')[0]
            if not name:
                break
            cls.lib[name.decode('latin1')] = {
                'mode': a & 0xFFFF, 'size': b & 0xFFFFFF, 'off': (c >> 6) * 4}
            pos += 12 + 4 * nwords
        cls.read_blocks = staticmethod(read_blocks)
        cls.read_symlink = staticmethod(read_symlink)

    def test_ld_linux_symlink_resolves_to_ld_2_11_2(self):
        entry = self.lib['ld-linux.so.3']
        self.assertEqual(entry['mode'] & 0xF000, 0xA000)
        self.assertEqual(self.read_symlink(self.image, entry['off'], entry['size']),
                         'ld-2.11.2.so')
        self.assertIn('ld-2.11.2.so', self.lib)
        self.assertEqual(self.lib['ld-2.11.2.so']['size'], 101736)

    def test_ld_2_11_2_is_arm_dynamic_loader_elf(self):
        entry = self.lib['ld-2.11.2.so']
        elf = self.read_blocks(self.image, entry['off'], entry['size'])
        self.assertEqual(elf[:4], b'\x7fELF')
        e_type, e_machine = struct.unpack_from('<HH', elf, 16)
        self.assertEqual(e_type, 3)          # ET_DYN
        self.assertEqual(e_machine, 0x28)    # ARM
        e_entry = struct.unpack_from('<I', elf, 24)[0]
        self.assertEqual(e_entry, 0x791)     # Thumb entry
        e_flags = struct.unpack_from('<I', elf, 36)[0]
        self.assertEqual(e_flags, 0x05000002)
        e_phoff = struct.unpack_from('<I', elf, 28)[0]
        e_phnum = struct.unpack_from('<H', elf, 44)[0]
        interp = None
        for index in range(e_phnum):
            ph = struct.unpack_from('<8I', elf, e_phoff + 32 * index)
            if ph[0] == 3:
                interp = elf[ph[1]:ph[1] + ph[4]]
        self.assertIsNone(interp)            # the interpreter itself has no PT_INTERP


if __name__ == '__main__':
    unittest.main()
