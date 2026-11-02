"""Decode ARM immediates from instructions, independently of display spelling."""
import struct
import unittest

from tools.research.startup_trace import arm_rotated_immediate, plt_symbols


def fixture(words, slot=0x15100, relocation_type=22):
    class PLT(dict):
        def data(self):
            return struct.pack('<' + 'I' * len(words), *words)
    class Relocations(dict):
        def iter_relocations(self):
            return iter([{'r_offset': slot, 'r_info_sym': 1, 'r_info_type': relocation_type}])
    class Symbols:
        def get_symbol(self, index):
            return type('Symbol', (), {'name': 'write'})()
    class ELF:
        def get_section_by_name(self, name):
            return PLT(sh_addr=0x1000) if name == '.plt' else Relocations(sh_link=1)
        def get_section(self, index):
            return Symbols()
    return ELF()


class ArmPLTTests(unittest.TestCase):
    def test_rotated_immediate_values(self):
        self.assertEqual(arm_rotated_immediate(0xe28cca14), 0x14000)
        self.assertEqual(arm_rotated_immediate(0xe28fc600), 0)
        self.assertEqual(arm_rotated_immediate(0xe28fc102), 0x80000000)

    def test_rotated_plt_matches_actual_got_slot(self):
        for load in (0xe5bcf0f8, 0xe59cf0f8):
            words = (0xe28fc600, 0xe28cca14, load)
            self.assertEqual(plt_symbols(fixture(words)), {0x1000: 'write'})

    def test_wrong_register_condition_or_relocation_cannot_resolve(self):
        words = (0xe28fc600, 0xe28cca14, 0xe5bcf0f8)
        for altered in ((0xe28fb600, *words[1:]), (words[0], 0xe28cba14, words[2]),
                         (0x128fc600, *words[1:])):
            self.assertEqual(plt_symbols(fixture(altered)), {})
        self.assertEqual(plt_symbols(fixture(words, slot=0x15104)), {})
        self.assertEqual(plt_symbols(fixture(words, relocation_type=21)), {})

    def test_truncated_stub_is_not_a_call(self):
        self.assertEqual(plt_symbols(fixture((0xe28fc600, 0xe28cca14))), {})
