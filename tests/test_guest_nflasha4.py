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
