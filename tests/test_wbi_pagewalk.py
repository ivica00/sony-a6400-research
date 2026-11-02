import struct
import unittest

from tools.research.wbi_pagewalk import translate, read_virtual


class Sparse:
    def __init__(self):
        self.data = {}

    def put(self, address, data):
        self.data.update((address + i, b) for i, b in enumerate(data))

    def word(self, address, value):
        self.put(address, struct.pack('<I', value))

    def read(self, address, size):
        try:
            return bytes(self.data[address + i] for i in range(size))
        except KeyError:
            raise ValueError('Unsupplied fixture memory') from None


class PageWalkTests(unittest.TestCase):
    def test_coarse_small_pages_and_cross_page_read(self):
        m = Sparse()
        m.word(4, 0x8001)
        m.word(0x8000, 0x20002)
        m.word(0x8004, 0x30003)
        m.put(0x20ffe, b'ab')
        m.put(0x30000, b'cd')
        self.assertEqual(translate(m, 0, 0x100ffe)[0], 0x20ffe)
        self.assertEqual(read_virtual(m, 0, 0x100ffe, 4), b'abcd')
        with self.assertRaises(ValueError):
            read_virtual(m, 0, 0x100ffe, 5)

    def test_section_and_replicated_supersection(self):
        m = Sparse()
        m.word(4, 0x12300002)
        self.assertEqual(translate(m, 0, 0x100abc)[0], 0x12300abc)
        m.put(0x80, struct.pack('<I', 0x34040002) * 16)
        self.assertEqual(translate(m, 0, 0x02345678)[0], 0x34345678)
        m.word(0x80, 0)
        with self.assertRaises(ValueError):
            translate(m, 0, 0x02345678)

    def test_unknown_descriptor_extended_address_and_bounds_stop(self):
        m = Sparse()
        for value in (0, 3, 0x00140002):
            m.word(0, value)
            with self.assertRaises(ValueError):
                translate(m, 0, 0)
        m.word(0, 0x8001)
        for value in (0, 1):
            m.word(0x8000, value)
            with self.assertRaises(ValueError):
                translate(m, 0, 0)
        for root, address in ((1, 0), (0, -1), (0, 1 << 32)):
            with self.assertRaises(ValueError):
                translate(m, root, address)
        with self.assertRaises(ValueError):
            read_virtual(m, 0, 0xffffffff, 2)


if __name__ == '__main__':
    unittest.main()
