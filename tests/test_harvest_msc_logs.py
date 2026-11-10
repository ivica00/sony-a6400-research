"""Fixtures for the read-only MSC log harvest helpers."""
import unittest

from tools.research.harvest_msc_logs import parse_ls, scan_keywords


class ParseLsTests(unittest.TestCase):
    def test_regular_files_only(self):
        sample = (b'total 24\n'
                  b'drwxr-xr-x    2 0        0            16384 Jan  1 00:00 .\n'
                  b'-rw-r--r--    1 0        0              149 Jan  1  1980 autoexec.log\n'
                  b'-rw-r--r--    1 0        0          1957888 Jan  1  1980 kikilog.dat\n'
                  b'lrwxrwxrwx    1 0        0               14 Jan  1  2011 mtab -> ../proc/mounts\n')
        self.assertEqual(parse_ls(sample), [('autoexec.log', 149), ('kikilog.dat', 1957888)])

    def test_garbage(self):
        self.assertEqual(parse_ls(b'not an ls line\n'), [])


class ScanTests(unittest.TestCase):
    def test_hits_and_context(self):
        data = b'\x00boot liveview ready SDIOConnect 0xFFFFC002 usbg_video PTP\x00'
        hits = scan_keywords(data)
        keywords = {h['keyword'].lower() for h in hits}
        self.assertIn('liveview', keywords)
        self.assertIn('sdio', keywords)
        self.assertIn('ffffc002', keywords)
        self.assertIn('usbg_video', keywords)
        self.assertTrue(all(isinstance(h['offset'], int) and h['context'] for h in hits))

    def test_no_hits(self):
        self.assertEqual(scan_keywords(b'\x00firmware only\x00'), [])


if __name__ == '__main__':
    unittest.main()
