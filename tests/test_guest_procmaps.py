"""Own /proc/<pid>/maps rendering: kernel line format and merge/split rules."""
import unittest

from src.a6400.execution.guest_procmaps import render_proc_maps

R, W, X = 1, 2, 4


class ProcMapsTests(unittest.TestCase):
    def test_kernel_format_and_naming(self):
        regions = [(0x8000, 0xd000, R | X), (0x14000, 0x15000, R | W), (0x15000, 0x315000, R | W),
                   (0x50000000, 0x50008000, R | X), (0x50008000, 0x50009000, R),
                   (0x60000000, 0x60002000, R | W)]
        mappings = [{'address': 0x8000, 'length': 0x5000, 'path': '/usr/bin/im.elf', 'offset': 0, 'flags': 2},
                    {'address': 0x50000000, 'length': 0x9000, 'path': '/usr/lib/libx.so', 'offset': 0, 'flags': 2},
                    {'address': 0x60000000, 'length': 0x2000, 'anonymous': True, 'flags': 0x22}]
        named = [(0x15000, 0x315000, '[heap]')]
        text = render_proc_maps(regions, mappings, named, lambda p: (0xfc, 0xf, 16268)).decode().split('\n')
        self.assertEqual(text[0], '00008000-0000d000 r-xp 00000000 fc:0f 16268      /usr/bin/im.elf')
        self.assertEqual(text[1], '00014000-00015000 rw-p 00000000 00:00 0')  # anonymous: no name, no padding
        self.assertEqual(text[2], '00015000-00315000 rw-p 00000000 00:00 0          [heap]')
        self.assertEqual(text[3], '50000000-50008000 r-xp 00000000 fc:0f 16268      /usr/lib/libx.so')
        self.assertEqual(text[4], '50008000-50009000 r--p 00008000 fc:0f 16268      /usr/lib/libx.so')  # offset advances
        self.assertEqual(text[5], '60000000-60002000 rw-p 00000000 00:00 0')
        self.assertEqual(text[6], '')  # trailing newline

    def test_adjacent_equal_regions_merge_and_shared_flag(self):
        regions = [(0x1000, 0x2000, R | W), (0x2000, 0x3000, R | W)]
        mappings = [{'address': 0x1000, 'length': 0x2000, 'path': '/dev/stream', 'offset': 0, 'flags': 1}]
        text = render_proc_maps(regions, mappings).decode()
        self.assertEqual(text.count('\n'), 1)
        self.assertIn('00001000-00003000 rw-s 00000000 00:00 0', text)

    def test_later_mapping_wins_and_empty_is_empty(self):
        mappings = [{'address': 0x1000, 'length': 0x1000, 'path': '/a', 'offset': 0, 'flags': 2},
                    {'address': 0x1000, 'length': 0x1000, 'anonymous': True, 'flags': 0x22}]
        self.assertNotIn('/a', render_proc_maps([(0x1000, 0x2000, R)], mappings).decode())
        self.assertEqual(render_proc_maps([], []), b'')


if __name__ == '__main__':
    unittest.main()
