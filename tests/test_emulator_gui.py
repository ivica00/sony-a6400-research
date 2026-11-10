import json
import pickle
import struct
import tempfile
import unittest
import zlib
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from src.a6400.execution.guest_display import GL_COMMON_POOL
from tools.research.emulator_gui import (
    CheckpointMemory, FramePump, checkpoint_display, save_frame,
)

TINY_PROFILE = {
    'name': 'test-contract',
    'surfaces': {
        'tiny': {
            'name': 'tiny', 'physical_base': 0x202E1000, 'width': 2, 'height': 2,
            'pixel_format': 'rgba4444', 'bytes_per_pixel': 2,
            'evidence': 'unit-test', 'format_source': 'evidence-hypothesis', 'note': '',
        }
    },
    'pool': GL_COMMON_POOL,
    'presentation_order': ['tiny'],
}


def write_checkpoint(path: Path) -> None:
    region = bytearray(0x2000)
    struct.pack_into('<4H', region, 0x1000, 0xF00F, 0x0FFF, 0x1234, 0xFFFF)
    payload = {
        'version': 1,
        'regions': [{'begin': 0x1000, 'end': 0x2FFF, 'perms': 3, 'size': 0x2000,
                     'data': zlib.compress(bytes(region), level=1)}],
        'subsystems': {
            'mmap': {'mappings': [{'device': 'stream', 'path': '/dev/stream',
                                   'address': 0x1000, 'length': 0x2000,
                                   'physical_start': 0x202E0000, 'prot': 3, 'flags': 1}]},
        },
    }
    path.write_bytes(pickle.dumps(payload))


class TestCheckpointDisplay(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.checkpoint = self.root / 'tiny.ckpt'
        write_checkpoint(self.checkpoint)

    def tearDown(self):
        self.tmp.cleanup()

    def test_checkpoint_memory_reads_only_mapped_ranges(self):
        memory = CheckpointMemory(self.checkpoint)
        self.assertEqual(memory.stream_mapping()['address'], 0x1000)
        self.assertEqual(memory.read(0x2000, 2), struct.pack('<H', 0xF00F))
        with self.assertRaises(ValueError):
            memory.read(0x9000, 4)

    def test_checkpoint_display_extracts_guest_pixels_without_host_drawing(self):
        model, frame = checkpoint_display(self.checkpoint, profile=TINY_PROFILE)
        self.assertEqual(frame.surface.name, 'tiny')
        self.assertEqual(frame.status, 'snapshot-content')
        self.assertEqual(frame.rgba[0:4], bytes((255, 0, 0, 255)))
        self.assertEqual(frame.metadata()['format_source'], 'evidence-hypothesis')

    def test_save_frame_writes_png_and_receipt(self):
        _, frame = checkpoint_display(self.checkpoint, profile=TINY_PROFILE)
        receipt = save_frame(frame, self.root / 'out', stem='tiny')
        with Image.open(self.root / 'out' / 'tiny.png') as image:
            self.assertEqual(image.size, (2, 2))
        self.assertFalse(receipt['host_drawing'])
        stored = json.loads((self.root / 'out' / 'tiny.json').read_text(encoding='utf-8'))
        self.assertEqual(stored['surface'], 'tiny')
        self.assertEqual(stored['status'], 'snapshot-content')


class TestFramePump(unittest.TestCase):
    class FakeProbe:
        def __init__(self):
            self.calls = 0
            self.paused = False

        def capture_display(self):
            self.calls += 1
            return SimpleNamespace(raw_sha256=f'hash-{self.calls}')

        def pause(self):
            self.paused = True

    def test_deduplicates_and_stops_at_frame_limit(self):
        probe = self.FakeProbe()
        seen = []
        pump = FramePump(probe, seen.append, max_frames=2, min_interval=0.0)
        pump.capture()
        pump.capture()
        self.assertEqual(len(seen), 2)
        self.assertTrue(probe.paused)
        # Same hash is not emitted again.
        pump.last_sha = f'hash-{probe.calls + 1}'
        pump.capture()
        self.assertEqual(len(seen), 2)


class TestWindow(unittest.TestCase):
    def test_window_shows_guest_frame_and_labels_status(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / 'tiny.ckpt'
        write_checkpoint(path)
        _, frame = checkpoint_display(path, profile=TINY_PROFILE)
        try:
            from tools.research.emulator_gui import EmulatorScreenWindow
            window = EmulatorScreenWindow(scale=1.0)
        except Exception as error:  # Tk unavailable in this environment
            self.skipTest(f'Tk unavailable: {error}')
        try:
            window.show_frame(frame)
            self.assertIn('tiny', window.status.cget('text'))
            self.assertIn('snapshot-content', window.status.cget('text'))
        finally:
            window.root.destroy()


if __name__ == '__main__':
    unittest.main()
