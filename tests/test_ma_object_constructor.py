"""Constructed Thumb code verifies uninitialized object and write bounds."""
import struct
import unittest

from tools.research.ma_object_constructor import execute, OBJECT


def fixture(code):
    raw = bytearray(0x2500)
    ident = b'\x7fELF' + bytes((1, 1, 1)) + bytes(9)
    raw[:52] = ident + struct.pack('<HHIIIIIHHHHHH', 3, 40, 1, 0x71fbf5, 0, 0x2200,
                                  0x5000000, 52, 0, 0, 40, 5, 4)
    entries = ((1, 1, 6, 0x71f000, 0x100, 4096, 0, 0, 4, 0),
               (7, 1, 3, 0x1370000, 0x1100, 4096, 0, 0, 4, 0),
               (12, 9, 0, 0, 0x2100, 16, 0, 0, 4, 8),
               (21, 3, 0, 0, 0x2400, 31, 0, 0, 1, 0))
    for index, entry in enumerate(entries, 1):
        struct.pack_into('<10I', raw, 0x2200 + index * 40, *entry)
    raw[0x2400:0x241f] = b'\0.text\0.got\0.rel.dyn\0.shstrtab\0'
    struct.pack_into('<4I', raw, 0x2100, 0x13704f0, 23, 0x1370a18, 23)
    raw[0xcf4:0xcf4 + len(code)] = code
    return bytes(raw)


class ObjectConstructorBoundsTests(unittest.TestCase):
    def test_poison_backing_is_not_initialized_object_state(self):
        # ldr r1,[r0] must not consume the backing poison as object state.
        result = execute(fixture(bytes.fromhex('0168')))
        self.assertEqual(result['status'], 'uninitialized_object_read')
        self.assertEqual(result['boundary']['address'], OBJECT)
        self.assertEqual(result['initialized_offsets'], [])

    def test_original_stores_release_only_written_bytes(self):
        # movs r1,0; str r1,[r0]; ldr r2,[r0]; b .
        result = execute(fixture(bytes.fromhex('002101600268fee7')))
        self.assertEqual(result['status'], 'instruction_limit')
        self.assertEqual(result['initialized_offsets'], [0, 1, 2, 3])
        self.assertEqual(result['object_bytes_at_stop'][:8], '00000000')

    def test_mapped_padding_does_not_extend_object_write_permission(self):
        # adds r0,184; str r1,[r0] targets mapped padding beyond the object.
        result = execute(fixture(bytes.fromhex('b8300160')))
        self.assertEqual(result['status'], 'unsupported_write')
        self.assertEqual(result['boundary']['address'], OBJECT + 184)
        self.assertEqual(result['initialized_offsets'], [])
