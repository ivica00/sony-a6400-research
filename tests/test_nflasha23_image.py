"""nflasha23 reuses the nflasha4 in-memory partition model with its own size (--nflasha-image 23=<path>)."""
import pickle
import tempfile
import unittest
from pathlib import Path

from src.a6400.execution.guest_nflasha4 import Nflasha4Dump
from tools.research.experiment_ui_boot import build_parser


class Nflasha23Tests(unittest.TestCase):
    def _image(self):
        f = tempfile.NamedTemporaryFile(delete=False)
        f.write(bytes(range(256)) * 8192)  # 2 MiB
        f.close()
        return f.name

    def test_synthetic_takes_its_own_size_and_nflasha4_default_is_unchanged(self):
        path = self._image()
        dump = Nflasha4Dump.synthetic(0xff, path, expected_size=2097152)
        self.assertEqual(dump.size, 2097152)
        self.assertEqual(dump.read(256, 4), bytes([0, 1, 2, 3]))
        with self.assertRaises(ValueError):
            Nflasha4Dump.synthetic(0xff, path)  # nflasha4 still demands 12 MiB

    def test_writes_stay_in_memory_and_survive_pickle(self):
        path = self._image()
        before = Path(path).read_bytes()
        dump = Nflasha4Dump.synthetic(0xff, path, expected_size=2097152)
        self.assertEqual(dump.write(0, b'abc'), 3)
        self.assertTrue(dump.modified)
        again = pickle.loads(pickle.dumps(dump))
        self.assertEqual(again.read(0, 3), b'abc')
        self.assertEqual(Path(path).read_bytes(), before)
        self.assertEqual(dump.write(2097152, b'x'), -28)

    def test_block_layer_queries(self):
        dump = Nflasha4Dump.synthetic(0xff, self._image(), expected_size=2097152)
        self.assertEqual(dump.block_ioctl(0x1268), (512).to_bytes(4, 'little'))
        self.assertEqual(dump.block_ioctl(0x1260), (4096).to_bytes(4, 'little'))
        self.assertEqual(dump.block_ioctl(0x80041272), (2097152).to_bytes(8, 'little'))
        self.assertIsNone(dump.block_ioctl(0x80014123))

    def test_cli_accepts_23_only_besides_4(self):
        args = build_parser().parse_args(['--nflasha-image', '23=x.bin', '--nflasha-image', '4=y.bin'])
        self.assertEqual(args.nflasha_image, [(23, 'x.bin'), (4, 'y.bin')])
        with self.assertRaises(SystemExit):
            build_parser().parse_args(['--nflasha-image', '5=x.bin'])


if __name__ == '__main__':
    unittest.main()
