"""Tests for static producer and physical storage trace logic."""
import io
import struct
import unittest

from elftools.elf.elffile import ELFFile
from tools.research.producer_physical_trace import find_calls_to_target, data_table_relocations


def elf_data_table_fixture():
    names = b'\0.data\0.rel.data\0.symtab\0.strtab\0.shstrtab\0'
    table_data = struct.pack('<2I', 0, 0)
    symbols = bytes(16)
    symbols += struct.pack('<IIIBBH', 1, 0x1000, 0, 0x12, 0, 1)
    symbols += struct.pack('<IIIBBH', 7, 0x2000, 0, 0x12, 0, 1)
    rel = struct.pack('<2I', 0, (1 << 8) | 2)
    rel += struct.pack('<2I', 4, (2 << 8) | 2)
    contents = [table_data, rel, symbols, b'\0funcA\0funcB\0', names]
    attributes = [(1, 3, 0, 0, 4, 0),
                  (9, 0, 3, 1, 4, 8),
                  (2, 0, 4, 1, 4, 16),
                  (3, 0, 0, 0, 1, 0),
                  (3, 0, 0, 0, 1, 0)]
    section_names = ['.data', '.rel.data', '.symtab', '.strtab', '.shstrtab']
    data = bytearray(52)
    headers = [bytes(40)]
    for name, content, (kind, flags, link, info, alignment, entry_size) in zip(section_names, contents, attributes):
        data.extend(bytes((-len(data)) % 4))
        offset = len(data)
        data.extend(content)
        headers.append(struct.pack('<10I', names.index(name.encode()), kind, flags, 0,
                                   offset, len(content), link, info, alignment, entry_size))
    data.extend(bytes((-len(data)) % 4))
    table = len(data)
    data.extend(b''.join(headers))
    data[:16] = b'\x7fELF' + bytes([1, 1, 1]) + bytes(9)
    struct.pack_into('<HHIIIIIHHHHHH', data, 16, 1, 40, 1, 0, 0, table,
                     0x5000000, 52, 0, 0, 40, 6, 5)
    return bytes(data)


class ProducerPhysicalTraceTests(unittest.TestCase):
    def test_find_calls_to_target(self):
        rows = [
            {'offset': 0x10, 'kind': 'instruction_candidate', 'mnemonic': 'mov', 'operands': 'r0, r1'},
            {'offset': 0x14, 'kind': 'instruction_candidate', 'mnemonic': 'bl', 'operands': '#0xa89c'},
            {'offset': 0x18, 'kind': 'instruction_candidate', 'mnemonic': 'b', 'operands': '#0xa89c'},
            {'offset': 0x1c, 'kind': 'instruction_candidate', 'mnemonic': 'bl', 'operands': '#0x5000'},
            {'offset': 0x20, 'kind': 'literal_data', 'value': 0xa89c},
        ]
        calls = find_calls_to_target(rows, 0xa89c)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0], {'offset': 0x14, 'mnemonic': 'bl', 'target': 0xa89c})
        self.assertEqual(calls[1], {'offset': 0x18, 'mnemonic': 'b', 'target': 0xa89c})

    def test_find_calls_ignores_malformed_operands(self):
        rows = [
            {'offset': 0x10, 'kind': 'instruction_candidate', 'mnemonic': 'bl', 'operands': 'r3'},
            {'offset': 0x14, 'kind': 'instruction_candidate', 'mnemonic': 'bl', 'operands': 'invalid'},
        ]
        self.assertEqual(find_calls_to_target(rows, 0xa89c), [])

    def test_data_table_relocations_decodes_slots(self):
        elf_bytes = elf_data_table_fixture()
        elf = ELFFile(io.BytesIO(elf_bytes))
        slots = data_table_relocations(elf, '.data', 0, 8)
        self.assertEqual(len(slots), 2)
        self.assertEqual(slots[0]['offset'], 0)
        self.assertEqual(slots[0]['relocation']['symbol'], 'funcA')
        self.assertEqual(slots[1]['offset'], 4)
        self.assertEqual(slots[1]['relocation']['symbol'], 'funcB')


if __name__ == '__main__':
    unittest.main()
