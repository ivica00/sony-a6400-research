"""Sony LZ77 block decoder: a hand-built stored + 0xf0 stream round-trips exactly."""
import unittest

from src.a6400.execution.lz77 import inflate_block


class Lz77Tests(unittest.TestCase):
    def test_stored_then_match_block_decode_with_exact_consumption(self):
        stored = bytes([0x0f, 0, 3, 0]) + b'abc'
        # flags 0b110: literal 'x', match (dist 1, len 3), terminator (dist 0)
        matched = bytes([0xf0, 0x06]) + b'x' + bytes([0x00, 0x01, 0x00, 0x00])
        stream = stored + matched
        first, pos = inflate_block(stream, 0, 4096)
        second, end = inflate_block(stream, pos, 4096)
        self.assertEqual((first, pos), (b'abc', len(stored)))
        self.assertEqual((second, end), (b'xxxx', len(stream)))


if __name__ == '__main__':
    unittest.main()
