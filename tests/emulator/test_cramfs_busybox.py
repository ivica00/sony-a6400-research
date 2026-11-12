"""E0426: cramfs symlink/busybox ELF decode and user-mode transition tests."""
import struct
import unittest
import zlib
from pathlib import Path

from src.a6400.execution.arm_atags import build_atags
from src.a6400.execution.nflasha_boot_set import NflashaBootSet
from src.a6400.execution.unicorn_machine import UnicornMachine

ROOT = Path(__file__).resolve().parents[2]
BLOCK = 4096


def inode_before(image, name, mode_mask, mode_expected):
    needle = name.encode('latin1') + b'\x00'
    pos = 0
    while True:
        at = image.find(needle, pos)
        if at < 0:
            return None
        pos = at + 1
        if at < 12:
            continue
        a, b, c = struct.unpack_from('<III', image, at - 12)
        if (a & 0xFFFF) != mode_expected:
            continue
        if (a & 0xF000) != mode_mask:
            continue
        return {'size': b & 0xFFFFFF, 'off': (c >> 6) * 4}


def read_blocks(image, off, size, block=BLOCK):
    nblocks = (size + block - 1) // block
    entries = [struct.unpack_from('<I', image, off + 4 * i)[0] for i in range(nblocks)]
    out = bytearray()
    pos = off + 4 * nblocks           # block 0 implicitly follows the pointer table
    for i in range(nblocks):
        end = entries[i]
        out += zlib.decompress(image[pos:end])
        pos = end
    return bytes(out[:size])


def read_symlink(image, off, size):
    # Symlink data is one compressed block whose pointer table has one entry; the
    # target follows the table (verified: /bin/ash -> "busybox", E0426).
    start = off + 4
    for end in range(start + 2, min(len(image), start + 64)):
        try:
            text = zlib.decompress(image[start:end])
            if len(text) == size:
                return text.decode('latin1')
        except Exception:
            continue
    return None


class CramfsBusyboxTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        boot_set = NflashaBootSet.from_evidence(ROOT, 'nflasha1')
        cls.image = boot_set.read('boot/initrd.img')

    def test_ash_symlink_target_is_busybox(self):
        ino = inode_before(self.image, 'ash', 0xA000, 0xA1FF)
        self.assertIsNotNone(ino)
        self.assertEqual(ino['size'], 7)
        self.assertEqual(read_symlink(self.image, ino['off'], ino['size']), 'busybox')

    def test_busybox_is_dynamic_arm_elf(self):
        ino = inode_before(self.image, 'busybox', 0x8000, 0x81FF)
        self.assertIsNotNone(ino)
        self.assertEqual(ino['size'], 233448)
        elf = read_blocks(self.image, ino['off'], ino['size'])
        self.assertEqual(elf[:4], b'\x7fELF')
        e_type, e_machine = struct.unpack_from('<HH', elf, 16)
        self.assertEqual(e_type, 2)          # ET_EXEC
        self.assertEqual(e_machine, 0x28)    # ARM
        e_entry = struct.unpack_from('<I', elf, 24)[0]
        self.assertEqual(e_entry & 1, 1)     # Thumb-2 entry
        e_phoff = struct.unpack_from('<I', elf, 28)[0]
        e_phnum = struct.unpack_from('<H', elf, 44)[0]
        interp = None
        for index in range(e_phnum):
            ph = struct.unpack_from('<8I', elf, e_phoff + 32 * index)
            if ph[0] == 3:
                interp = elf[ph[1]:ph[1] + ph[4]]
        self.assertEqual(interp, b'//lib/ld-linux.so.3\x00')


class UserModeTransitionTests(unittest.TestCase):
    def test_user_mode_entry_is_recorded(self):
        program = bytearray(0x100)
        words = [
            0xE321F0D3,  # msr cpsr_c,#0xd3 (machine head marker)
            0xE10F0000,  # mrs r0, cpsr
            0xE3C0001F,  # bic r0, r0, #0x1f
            0xE3800010,  # orr r0, r0, #0x10
            0xE129F000,  # msr cpsr_c, r0
            0xEAFFFFFE,  # b .
        ]
        for index, word in enumerate(words):
            struct.pack_into('<I', program, index * 4, word)
        machine = UnicornMachine(bytes(program), b'\x00' * 64,
                                 build_atags('console=ttyAM0', [(0, 0x40000000)]),
                                 machine_id=0x0DA9, instruction_limit=50,
                                 kernel_load=0x8000,
                                 exclusive_patch=False, data_abort_delivery=False,
                                 trace_user_mode=True)
        report = machine.run()
        entries = report['user_mode_entries']
        self.assertTrue(entries)
        self.assertEqual(entries[0]['cpsr'] & 0x1F, 0x10)


if __name__ == '__main__':
    unittest.main()
