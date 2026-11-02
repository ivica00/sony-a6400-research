"""Redistributable preset fixtures and actual Thumb window stop checks."""
import struct
import unittest

from unicorn import arm_const as arm
from tools.research.backup_state_trace import checked_bk4
from tools.research.liro_startup_trace import BASE, run_slice


def fixture():
    raw = bytearray(0x124)
    raw[12:16] = b'BK4\0'
    struct.pack_into('<4I', raw, 0x10, 1, 1, 0x120, 4)
    raw[0x120:] = b'\x01\x02\x03\x04'
    struct.pack_into('<I', raw, 0x20, sum(raw))
    return raw


class BackupPresetPreflightTests(unittest.TestCase):
    def test_complete_fixture_has_checked_payload_extent(self):
        result = checked_bk4(bytes(fixture()))
        self.assertEqual((result['subsystems'], result['properties'], result['data_offset'], result['data_size']),
                         (1, 1, 0x120, 4))

    def test_changed_payload_is_rejected(self):
        raw = fixture()
        raw[-1] ^= 1
        with self.assertRaisesRegex(ValueError, 'checksum'):
            checked_bk4(raw)

    def test_truncated_payload_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'exceeds'):
            checked_bk4(fixture()[:-1])

    def test_tables_cannot_overlap_payload(self):
        raw = fixture()
        struct.pack_into('<I', raw, 0x10, 0xffffffff)
        with self.assertRaisesRegex(ValueError, 'tables overlap'):
            checked_bk4(raw)

    def test_extent_cannot_wrap_at_32_bits(self):
        raw = fixture()
        struct.pack_into('<2I', raw, 0x18, 0xfffffff0, 0x30)
        with self.assertRaisesRegex(ValueError, 'exceeds'):
            checked_bk4(raw)

    def test_other_revisions_and_partial_headers_are_not_admitted(self):
        raw = fixture()
        raw[14] = ord('2')
        for candidate in (raw, bytes(255)):
            with self.subTest(length=len(candidate)):
                with self.assertRaisesRegex(ValueError, 'BK4'):
                    checked_bk4(candidate)


class BackupThumbWindowTests(unittest.TestCase):
    def test_thumb_stops_before_call_and_preserves_decoded_arguments(self):
        # movs r0,#62; movs r1,#8; movs r2,#1; bl +0
        code = bytes.fromhex('3e200821012200f000f8')
        report, _ = run_slice(code, 0, [(0, 6)], {6: 'call_boundary'}, {}, thumb=True)
        self.assertEqual(report['status'], 'call_boundary')
        self.assertEqual([report['registers'][r] for r in ('r0', 'r1', 'r2')], [62, 8, 1])
        self.assertEqual([row['offset'] for row in report['trace']], [0, 2, 4])
        self.assertEqual(report['kernel_responses_supplied'], 0)

    def test_thumb_branch_outside_window_is_not_completion(self):
        report, _ = run_slice(bytes.fromhex('704700bf'), 0, [(0, 2)], {},
                              {arm.UC_ARM_REG_LR: BASE + 3}, thumb=True)
        self.assertEqual(report['status'], 'unexpected_control_flow')
        self.assertEqual(report['boundary_offset'], 2)

    def test_thumb_budget_limit_is_not_completion(self):
        report, _ = run_slice(bytes.fromhex('fee7'), 0, [(0, 2)], {}, {}, budget=5, thumb=True)
        self.assertEqual(report['status'], 'instruction_budget_exhausted')
        self.assertEqual(len(report['trace']), 5)
