"""Constructed checks for the observed-dump /dev/nflasha4 policy (E0305)."""
import hashlib
import unittest

from src.a6400.execution.guest_nflasha4 import (
    ERASED_STATE_IOCTL,
    Nflasha4Dump,
    Nflasha4DumpError,
)

PATTERN_SIZE = 64


def make_dump(erased=0x00):
    image = bytes((index * 7) & 0xff for index in range(PATTERN_SIZE))
    return Nflasha4Dump(image, erased, expected_size=PATTERN_SIZE)


class Nflasha4DumpReadTests(unittest.TestCase):
    def test_read_is_bounded_and_stops_at_the_end(self):
        dump = make_dump()
        self.assertEqual(dump.size, PATTERN_SIZE)
        self.assertEqual(dump.read(0, 4).hex(), '00070e15')
        self.assertEqual(dump.read(60, 8), dump.image[60:64])
        self.assertEqual(len(dump.read(PATTERN_SIZE, 16)), 0)

    def test_invalid_ranges_are_explicit_boundaries(self):
        dump = make_dump()
        with self.assertRaises(Nflasha4DumpError):
            dump.read(-1, 4)
        with self.assertRaises(Nflasha4DumpError):
            dump.read(PATTERN_SIZE + 1, 1)
        with self.assertRaises(Nflasha4DumpError):
            dump.read(0, -1)
        with self.assertRaises(Nflasha4DumpError):
            dump.read('0', 1)

    def test_ioctl_serves_only_the_observed_read_query(self):
        dump = Nflasha4Dump(bytes(PATTERN_SIZE), 0x00, expected_size=PATTERN_SIZE)
        self.assertEqual(dump.ioctl_erased_state(ERASED_STATE_IOCTL), 0x00)
        with self.assertRaises(Nflasha4DumpError):
            dump.ioctl_erased_state(0xC0045321)
        with self.assertRaises(Nflasha4DumpError):
            dump.ioctl_erased_state(ERASED_STATE_IOCTL + 1)

    def test_flush_is_answered_only_for_a_clean_model_page_state(self):
        dump = make_dump()
        self.assertEqual(dump.flush_result(False), 0)
        with self.assertRaises(Nflasha4DumpError):
            dump.flush_result(True)

    def test_identity_hash_and_size_are_enforced(self):
        image = bytes(PATTERN_SIZE)
        digest = hashlib.sha256(image).hexdigest()
        Nflasha4Dump(image, 0, image_sha256=digest, expected_size=PATTERN_SIZE)
        with self.assertRaises(ValueError):
            Nflasha4Dump(image, 0, image_sha256='0' * 64, expected_size=PATTERN_SIZE)
        with self.assertRaises(ValueError):
            Nflasha4Dump(image + b'\x00', 0, expected_size=PATTERN_SIZE)


if __name__ == '__main__':
    unittest.main()


class Nflasha4WriteTests(unittest.TestCase):
    def writable(self):
        dump = make_dump()
        dump.writable = True
        return dump

    def test_read_only_policy_refuses_writes(self):
        with self.assertRaises(Nflasha4DumpError):
            make_dump().write(0, b'x')

    def test_write_then_read_back_and_source_bytes_untouched(self):
        source = bytes((i * 7) & 0xff for i in range(PATTERN_SIZE))
        dump = self.writable()
        self.assertEqual(dump.write(4, b'abcd'), 4)
        self.assertEqual(dump.read(2, 8), source[2:4] + b'abcd' + source[8:10])
        self.assertIsInstance(dump.read(0, 4), bytes)
        self.assertTrue(dump.modified)
        self.assertEqual(dump.flush_result(True), 0)

    def test_write_past_end(self):
        dump = self.writable()
        self.assertEqual(dump.write(PATTERN_SIZE - 2, b'wxyz'), 2)  # short write
        self.assertEqual(dump.read(PATTERN_SIZE - 2, 8), b'wx')
        self.assertEqual(dump.write(PATTERN_SIZE, b'q'), -28)  # -ENOSPC
        self.assertEqual(len(dump.image), PATTERN_SIZE)

    def test_checkpoint_pickle_round_trip(self):
        import pickle
        dump = self.writable()
        dump.write(10, b'keep')
        copy = pickle.loads(pickle.dumps(dump))
        self.assertEqual(copy.read(10, 4), b'keep')
        self.assertTrue(copy.writable and copy.modified)
        copy.write(0, b'z')  # still a bytearray after restore


class Nflasha4SyntheticTests(unittest.TestCase):
    def test_default_fill_is_0xff_writable_and_ioctl_byte_stays_observed(self):
        dump = Nflasha4Dump.synthetic()
        self.assertEqual(dump.size, 12582912)
        self.assertEqual(dump.read(0, 4), b'\xff' * 4)
        self.assertEqual(dump.read(dump.size - 2, 8), b'\xff\xff')
        self.assertEqual(dump.ioctl_erased_state(ERASED_STATE_IOCTL), 0x00)
        self.assertEqual(dump.write(0, b'CMMe'), 4)
        self.assertEqual(dump.read(0, 5), b'CMMe\xff')

    def test_file_image_is_loaded_and_host_file_never_written(self):
        import tempfile
        from pathlib import Path
        image = b'CMMe' + b'\xff' * (12582912 - 4)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'n4.bin'
            path.write_bytes(image)
            dump = Nflasha4Dump.synthetic(image_path=path)
            self.assertEqual(dump.read(0, 6), b'CMMe\xff\xff')
            dump.write(0, b'XXXX')
            self.assertEqual(path.read_bytes(), image)
            path.write_bytes(b'short')
            with self.assertRaises(ValueError):
                Nflasha4Dump.synthetic(image_path=path)
