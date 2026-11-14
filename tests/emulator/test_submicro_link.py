"""Unit tests for Sony BIONZ X sub-microcontroller link transport & TLV codec."""

from __future__ import annotations

import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.a6400.execution.submicro_link import (
    FRAME_SIZE,
    MAX_CMD_DATA_LEN,
    SLOT_B_TYPE_CPU_TO_MICRO,
    SLOT_B_TYPE_MICRO_TO_CPU,
    crc16_ccitt_false,
    decode_command_header,
    decode_slot_b_frame,
    encode_command_header,
    encode_slot_b_frame,
    verify_frame_crc,
)


class TestSubmicroSlotB(unittest.TestCase):
    def test_snapshot_slot_b_frame_matches_documented_crc_and_tlvs(self) -> None:
        # Snapshot Slot B TLVs documented in Oein/a5000-emulator RE_SUBMICRO_LINK.md §4.
        tlvs = [
            (0x00, bytes.fromhex('01 00 00 30')),
            (0x01, bytes.fromhex('00 01 00 00')),
            (0x02, bytes.fromhex('00 00 00 00')),
            (0x03, bytes.fromhex('00 40 00 02')),
            (0x0A, bytes(8) + b'\xff' * 8 + bytes(16)),
            (0x0B, bytes.fromhex('02 40 02 00 c0 00 00 00 31 15 00 00 00 00 00 00')),
            (0x0C, bytes(4)),
            (0x10, bytes(4)),
        ]
        frame = encode_slot_b_frame(SLOT_B_TYPE_MICRO_TO_CPU, tlvs)
        self.assertEqual(len(frame), FRAME_SIZE)
        self.assertEqual(frame[2], 0x68)
        self.assertEqual(crc16_ccitt_false(frame[:126]), 0xA659)
        self.assertEqual(frame[126:128], b'\x59\xa6')
        self.assertTrue(verify_frame_crc(frame))

        decoded = decode_slot_b_frame(frame)
        self.assertTrue(decoded.crc_valid)
        self.assertEqual(decoded.frame_type, SLOT_B_TYPE_MICRO_TO_CPU)
        self.assertEqual(decoded.tlv_byte_count, 0x68)
        self.assertEqual(decoded.version_code, 100)
        self.assertEqual(decoded.by_id()[0x03], bytes.fromhex('00 40 00 02'))

    def test_corrupted_crc_is_detected(self) -> None:
        frame = bytearray(encode_slot_b_frame(SLOT_B_TYPE_CPU_TO_MICRO, [(0x00, b'\x01\x00\x00\x00')]))
        frame[10] ^= 0x01
        self.assertFalse(verify_frame_crc(bytes(frame)))
        decoded = decode_slot_b_frame(bytes(frame))
        self.assertFalse(decoded.crc_valid)

    def test_payload_limit_122_bytes_is_enforced(self) -> None:
        with self.assertRaises(ValueError):
            encode_slot_b_frame(SLOT_B_TYPE_MICRO_TO_CPU, [(0x0D, b'\x00' * 119)])  # 4 + 119 = 123 > 122


class TestSubmicroCommandHeader(unittest.TestCase):
    def test_encode_and_decode_command_headers(self) -> None:
        hdr_ab = encode_command_header(category=5, command=4, direction=0, data_length=256)
        dec_ab = decode_command_header(hdr_ab)
        self.assertTrue(dec_ab.is_slot_ab_exchange)
        self.assertFalse(dec_ab.is_cpu_to_micro)
        self.assertEqual(dec_ab.data_length, 256)

        hdr_tx = encode_command_header(category=3, command=1, direction=2, data_length=16)
        dec_tx = decode_command_header(hdr_tx)
        self.assertTrue(dec_tx.is_cpu_to_micro)
        self.assertFalse(dec_tx.is_slot_ab_exchange)

    def test_length_limit_enforced(self) -> None:
        with self.assertRaises(ValueError):
            encode_command_header(category=5, command=4, direction=0, data_length=MAX_CMD_DATA_LEN + 1)


if __name__ == '__main__':
    unittest.main()
