"""Constructed relocatable ELF evidence, with code and data at shared offsets."""
import struct
import unittest

from tools.research.storage_trace import decode_arm_range, inspect_module, execute_parameter_copy


def module_fixture(relocation_offset=8, duplicate=False):
    names = b'\0.text\0.rodata\0.rel.text\0.symtab\0.strtab\0.shstrtab\0'
    code = struct.pack('<4I', 0xe59f0000, 0xebfffffe, 0, 0xe12fff1e)
    symbols = bytes(16)
    symbols += struct.pack('<IIIBBH', 0, 0, 0, 3, 0, 2)  # local rodata section
    symbols += struct.pack('<IIIBBH', 1, 0, 16, 0x12, 0, 1)  # global function
    symbols += struct.pack('<IIIBBH', 7, 0, 0, 0x10, 0, 0)  # undefined external
    rel = struct.pack('<4I', 4, (3 << 8) | 28, relocation_offset, (1 << 8) | 2)
    if duplicate:
        rel += struct.pack('<2I', 4, (3 << 8) | 28)
    contents = [code, b'original-string\0', rel, symbols, b'\0probe\0external\0', names]
    attributes = [(1, 6, 0, 0, 4, 0), (1, 2, 0, 0, 1, 0),
                  (9, 0, 4, 1, 4, 8), (2, 0, 5, 2, 4, 16),
                  (3, 0, 0, 0, 1, 0), (3, 0, 0, 0, 1, 0)]
    section_names = ['.text', '.rodata', '.rel.text', '.symtab', '.strtab', '.shstrtab']
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
                     0x5000000, 52, 0, 0, 40, 7, 6)
    return data


class StorageTraceTests(unittest.TestCase):
    def test_real_elf_relocations_and_pc_literals(self):
        function = inspect_module(module_fixture(), ['probe'])[0]
        rows = {row['offset']: row for row in function['rows']}
        self.assertEqual(function['section'], '.text')
        self.assertEqual(rows[0]['literal']['section_offset'], 8)
        self.assertEqual(rows[0]['literal']['relocation']['string_candidate'], 'original-string')
        self.assertEqual(rows[4]['call_symbol'], 'external')
        self.assertEqual(rows[4]['relocation']['symbol_section'], 'SHN_UNDEF')
        self.assertEqual(rows[8]['kind'], 'literal_data')
        self.assertNotIn('mnemonic', rows[8])
        self.assertEqual(rows[12]['mnemonic'], 'bx')

    def test_out_of_section_and_duplicate_relocations_rejected(self):
        with self.assertRaisesRegex(ValueError, 'outside'):
            inspect_module(module_fixture(relocation_offset=16), ['probe'])
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            inspect_module(module_fixture(duplicate=True), ['probe'])

    def test_wrong_elf_type_and_missing_function_rejected(self):
        data = module_fixture()
        struct.pack_into('<H', data, 16, 2)
        with self.assertRaisesRegex(ValueError, 'relocatable'):
            inspect_module(data, ['probe'])
        with self.assertRaisesRegex(ValueError, 'Unique evidence symbol'):
            inspect_module(module_fixture(), ['missing'])

    def test_range_bounds_and_alignment(self):
        for start, size in ((-4, 4), (1, 4), (0, 3), (0, 0), (4, 16)):
            with self.assertRaises(ValueError):
                decode_arm_range(bytes(16), start, size, {})

    def test_backward_pc_literal_is_data(self):
        # PC at 4 is 12; a displacement of -12 points to the first word.
        data = struct.pack('<3I', 0x11223344, 0xe51f000c, 0xe12fff1e)
        rows = decode_arm_range(data, 0, len(data), {})
        self.assertEqual(rows[0]['kind'], 'literal_data')
        self.assertEqual(rows[0]['value'], 0x11223344)
        self.assertEqual(rows[1]['literal']['section_offset'], 0)

    def test_original_style_parameter_copy_executes_without_kernel_responses(self):
        # Constructed ARM loads/stores; the integration tool uses preserved code.
        words = (0xe1d530b6, 0xe5843028, 0xe1d530ba, 0xe5843030,
                 0xe1d530b8, 0xe3a05b01, 0xe5845088, 0xe1c458bc, 0xe584302c)
        code = struct.pack('<9I', *words)
        for first_minor in (0, 128):
            record = struct.pack('<I4H', 0, 1, 252, first_minor, 32)
            report = execute_parameter_copy(code, record)
            self.assertEqual(report['output_words'], {'0x28': 252, '0x2c': first_minor, '0x30': 32})
            self.assertEqual(report['instructions_executed'], 9)
            self.assertEqual(report['kernel_responses_supplied'], 0)
            raw = bytes.fromhex(report['output_hex'])
            self.assertEqual(raw[:0x28], b'\xa5' * 0x28)

    def test_copy_window_loop_is_not_success(self):
        with self.assertRaisesRegex(ValueError, 'complete exactly'):
            execute_parameter_copy(struct.pack('<9I', *([0xeafffffe] * 9)), bytes(12))
        with self.assertRaises(ValueError):
            execute_parameter_copy(bytes(32), bytes(12))
