import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tools.research.capture_display_ground_truth import (
    CHUNK, OSD_SIZE, SUGILITE_SIZE, _summary_total, capture, compare_manifest, remote_read,
)


class FakeDebugger:
    def __init__(self):
        self.files = {}
        self.commands = []
        self.pushed = None

    def push(self, path, data):
        self.pushed = (path, data)
        return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
                'readback_verified': True}

    def request(self, op, payload=b'', arg0=0, arg1=0):
        if op == 1:
            return {'status': 0, 'flags': 0, 'payload': b'A6400_USB_DEBUG_V1\n'}
        if op != 3:
            raise AssertionError(op)
        command = payload.decode()
        self.commands.append(command)
        if command.startswith('chmod'):
            return {'status': 0, 'flags': 0, 'payload': b''}
        if command.startswith('rm -f'):
            self.files.pop(command.split()[-1], None)
            return {'status': 0, 'flags': 0, 'payload': b''}
        if command.endswith('summary'):
            return {'status': 0, 'flags': 0,
                    'payload': b'BLOCK offset=0x0 nonzero=12\nGL_COMMON nonzero_total=12\nEND result=0\n'}
        parts = command.split()
        remote = parts[-1]
        size = 0
        for index, part in enumerate(parts):
            if part in ('osd_a', 'osd_b', 'sugilite'):
                size = int(parts[index + 2])
                break
        self.files[remote] = bytes(size)
        return {'status': 0, 'flags': 0, 'payload': b'DUMP ok\nEND result=0\n'}

    def read(self, path, offset=0, size=4064):
        data = self.files.get(path, b'')
        return data[offset:offset + size]


class TestCaptureFlow(unittest.TestCase):
    def test_capture_writes_manifest_and_cleans_remote_dumps(self):
        fake = FakeDebugger()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            helper = root / 'helper.elf'
            helper.write_bytes(b'HELPER')
            out = root / 'camera'
            manifest = capture(fake, out, helper)
            self.assertEqual(fake.pushed[0], '/tmp_bt/a6400_capture_display.elf')
            self.assertEqual(manifest['raw']['osd_a']['bytes'], OSD_SIZE)
            self.assertEqual(manifest['raw']['osd_a']['sha256'], hashlib.sha256(bytes(OSD_SIZE)).hexdigest())
            self.assertEqual(manifest['raw']['sugilite_b']['bytes'], SUGILITE_SIZE - CHUNK)
            self.assertEqual(manifest['gl_common_summary']['nonzero_total'], 12)
            self.assertTrue((out / 'osd_a-rgba4444.png').exists())
            self.assertTrue((out / 'sugilite-rgb565.png').exists())
            self.assertTrue((out / 'manifest.json').exists())
            self.assertFalse(any(path.endswith('.raw') for path in fake.files))
            self.assertTrue(any(command.startswith('chmod') for command in fake.commands))
            self.assertGreaterEqual(sum(command.startswith('rm -f') for command in fake.commands), 4)

    def test_short_remote_read_is_rejected(self):
        fake = FakeDebugger()
        with self.assertRaises(ValueError):
            remote_read(fake, '/tmp_bt/missing.raw', 10)

    def test_summary_and_comparison(self):
        self.assertEqual(_summary_total('a\nGL_COMMON nonzero_total=42\n'), 42)
        self.assertIsNone(_summary_total('none'))
        manifest = {'raw': {'osd_a': {'bytes': 614400}}}
        comparison = compare_manifest(manifest, {'surface': 'sugilite_color0',
                                                 'pixel_format': 'rgba4444',
                                                 'format_source': 'evidence-hypothesis'})
        self.assertEqual(comparison['camera_osd_bytes'], 614400)
        self.assertIn('not an emulator frame', comparison['note'])


if __name__ == '__main__':
    unittest.main()
