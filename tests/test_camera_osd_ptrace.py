import json
import tempfile
import unittest
from pathlib import Path

from src.a6400.execution.guest_display import DISPLAY_SURFACES
from tools.research.capture_camera_osd_ptrace import (
    CHUNK, capture, parse_stream_mappings, read_mapping,
)

MAPS = """\
08048000-08049000 r-xp 00000000 00:00 0          /usr/bin/test
08a5f000-0aa5f000 rw-s 202e0000 fc:07 287        /dev/stream
0bfd0000-0c066000 rw-s 23a80000 fc:07 287        /dev/stream
0cfdd000-0d073000 rw-s 23b16000 fc:07 287        /dev/stream
"""


class FakeDebugger:
    def __init__(self, maps=MAPS, data=b''):
        self.maps = maps.encode()
        self.data = data
        self.reads = 0

    def read_all(self, path, limit=2 * 1024 * 1024):
        assert path == '/proc/149/maps'
        return self.maps, False

    def memory(self, pid, address, size):
        assert pid == 149
        self.reads += 1
        return (b'\x00' * size)


class TestOsdPtrace(unittest.TestCase):
    def test_parse_only_osd_stream_mappings(self):
        found = parse_stream_mappings(MAPS)
        self.assertEqual(set(found), {'osd_a', 'osd_b'})
        self.assertEqual(found['osd_a']['virtual_start'], 0x0BFD0000)
        self.assertEqual(found['osd_a']['physical'], 0x23A80000)
        self.assertEqual(found['osd_a']['length'], 0x96000)
        self.assertEqual(found['osd_b']['virtual_start'], 0x0CFDD000)

    def test_capture_reads_exact_surface_and_writes_manifest(self):
        fake = FakeDebugger()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'camera'
            manifest = capture(fake, 149, out)
            surface = DISPLAY_SURFACES['osd_a']
            self.assertEqual((out / 'osd_a.raw').stat().st_size, 0x96000)
            self.assertEqual(manifest['surfaces']['osd_a']['raw_sha256'],
                             __import__('hashlib').sha256(bytes(0x96000)).hexdigest())
            self.assertEqual(manifest['surfaces']['osd_a']['nonzero_bytes'], 0)
            self.assertEqual(manifest['chunks'], (0x96000 + CHUNK - 1) // CHUNK)
            self.assertTrue((out / 'osd_a-rgba4444.png').exists())
            stored = json.loads((out / 'manifest.json').read_text(encoding='utf-8'))
            self.assertTrue(stored['no_dev_stream_open'])
            self.assertTrue(stored['no_camera_write'])

    def test_capture_requires_osd_a_mapping(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                capture(FakeDebugger(maps='08048000-08049000 r-xp 0 00:00 0 /x\n'), 149, Path(tmp))

    def test_read_mapping_stops_on_short_read(self):
        class Short(FakeDebugger):
            def memory(self, pid, address, size):
                return b'\x00' * (size - 1)
        with self.assertRaises(ValueError):
            read_mapping(Short(), 149, {'virtual_start': 0x1000, 'length': 8})


if __name__ == '__main__':
    unittest.main()
