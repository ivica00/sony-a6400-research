"""Focused fixtures for the pure PTP liveview frame validation."""
import unittest

from tools.research.ptp_frame import evaluate_frame, jpeg_sof_dimensions, parse_expect


def build(w, h, sof=0xC0, app0=True, fill=0):
    data = bytearray([0xFF, 0xD8])
    data += bytes([0xFF, 0xFE, 0x00, 0x80]) + b'\x00' * 126  # comment segment, >100 B frame
    if app0:
        data += bytes([0xFF, 0xE0, 0x00, 0x10]) + b'\x11' * 14
    data += b'\xFF' * fill
    data += bytes([0xFF, sof, 0x00, 0x11, 0x08,
                   (h >> 8) & 0xFF, h & 0xFF, (w >> 8) & 0xFF, w & 0xFF]) + b'\x22' * 9
    data += bytes([0xFF, 0xD9])
    return bytes(data)


class SofTests(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(jpeg_sof_dimensions(build(1024, 680)), (1024, 680))
        self.assertEqual(jpeg_sof_dimensions(build(1280, 720, sof=0xC2)), (1280, 720))
        self.assertEqual(jpeg_sof_dimensions(build(640, 480, app0=False, fill=3)), (640, 480))

    def test_invalid(self):
        data = build(1024, 680)
        self.assertIsNone(jpeg_sof_dimensions(b''))
        self.assertIsNone(jpeg_sof_dimensions(b'\x00\x00\x00\x00'))
        self.assertIsNone(jpeg_sof_dimensions(data[:10]))
        self.assertIsNone(jpeg_sof_dimensions(bytes([0xFF, 0xD8, 0xFF, 0xD9])))
        self.assertIsNone(jpeg_sof_dimensions(bytes([0xFF, 0xD8, 0xFF, 0xDA, 0x00, 0x02])))
        self.assertIsNone(jpeg_sof_dimensions(build(0, 680)))
        self.assertIsNone(jpeg_sof_dimensions(build(1024, 0)))
        self.assertIsNone(jpeg_sof_dimensions(bytes([0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x01, 0x00])))
        self.assertIsNone(jpeg_sof_dimensions(bytes([0xFF, 0xD8, 0xFF, 0xE0, 0xFF, 0xFF, 0x00, 0x00])))


class EvaluateTests(unittest.TestCase):
    def test_ok(self):
        result = evaluate_frame(build(1024, 680), expected=(1024, 680))
        self.assertTrue(result['ok'], result['reasons'])
        self.assertEqual(result['dimensions'], (1024, 680))
        self.assertEqual(result['bytes'], len(build(1024, 680)))
        self.assertIsNotNone(result['sha256'])

    def test_failures(self):
        self.assertIn('too_small', evaluate_frame(b'\x00' * 10)['reasons'])
        self.assertIn('no_sof', evaluate_frame(b'x' * 200)['reasons'])
        mismatch = evaluate_frame(build(1280, 720), expected=(1024, 680))
        self.assertFalse(mismatch['ok'])
        self.assertIn('dimension_mismatch', mismatch['reasons'])
        self.assertEqual(evaluate_frame(build(1280, 720), expected=None)['ok'], True)

    def test_expect_parser(self):
        self.assertEqual(parse_expect('1024x680'), (1024, 680))
        self.assertIsNone(parse_expect(''))
        for bad in ('1024', '0x680', 'axb', '1024x-1'):
            with self.assertRaises(ValueError):
                parse_expect(bad)


if __name__ == '__main__':
    unittest.main()
