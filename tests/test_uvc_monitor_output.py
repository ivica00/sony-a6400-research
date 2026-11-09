import unittest
from tools.research.capture_uvc_monitor_output import ring_ranges,translate_mapping


class MonitorOutputBounds(unittest.TestCase):
    def test_empty_and_contiguous(self):
        self.assertEqual(ring_ranges(3,3,8),[])
        self.assertEqual(ring_ranges(2,6,8),[(2,4)])

    def test_wrap_and_maximum_occupancy(self):
        self.assertEqual(ring_ranges(6,3,8),[(6,2),(0,3)])
        self.assertEqual(sum(n for _,n in ring_ranges(3,2,8)),7)

    def test_bad_cursors_rejected(self):
        for r,w,n in [(-1,0,8),(0,8,8),(0,0,1),(8,0,8)]:
            with self.assertRaises(ValueError):ring_ranges(r,w,n)

    def test_backing_translation(self):
        lines=['044bb000-04537000 rw-s 20098000 fc:07 136 /dev/mem']
        self.assertEqual(translate_mapping(lines,0x0450e400,0x8000)[0],0x200eb400)

    def test_unmapped_partial_or_ambiguous_rejected(self):
        line='044bb000-04537000 rw-s 20098000 fc:07 136 /dev/mem'
        for lines,a,n in [([line],0x04536000,0x2000),([],0x0450e400,16),([line,line],0x0450e400,16),([line],0x0450e400,0)]:
            with self.assertRaises(ValueError):translate_mapping(lines,a,n)


if __name__=='__main__':unittest.main()
