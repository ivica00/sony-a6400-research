import struct
import unittest
import zlib

from src.a6400.usb_debug_ring import (DEFAULT_CAPACITY, HEADER_SIZE, MAGIC_WORD,
                                      RingFormatError, analyze, cross_check,
                                      magic_bit_distance, parse_header,
                                      parse_ring_info)


def build_ring(segments, capacity=DEFAULT_CAPACITY, magic=b'klog'):
    body = b''.join(segments)
    header = magic + struct.pack('<II', len(body), 0)
    raw = header + body
    return raw.ljust(capacity, b'\x55')


def boot_stamp(seconds, text):
    return ('[%12.6f] %s\n' % (seconds, text)).encode()


class RingAnalyzeTests(unittest.TestCase):
    def capture(self, boots, capacity=DEFAULT_CAPACITY):
        segments = []
        for index, text in enumerate(boots):
            segments.append(boot_stamp(0.01 + index, 'WARMBOOT'))
            segments.append(boot_stamp(0.02 + index, 'PM: Low-level resume complete.'))
            if index:
                segments.append(boot_stamp(0.03 + index, 'klog: keep logging buffer: 0x00020000@0x035a5000, magic wrong nbit: 0'))
            else:
                segments.append(boot_stamp(0.03 + index, 'klog: initialize logging buffer: 0x00020000@0x035a5000, magic wrong nbit: 20(0x00000000)'))
            segments.append(boot_stamp(0.5 + index, text))
        raw = build_ring(segments, capacity)
        return raw, analyze(raw, capacity)

    def test_header_and_crc_match_captured_bytes(self):
        raw, result = self.capture(['boot one', 'boot two'])
        self.assertTrue(result['valid'])
        self.assertEqual(result['header']['magic'], 'klog')
        self.assertEqual(result['header']['magic_bit_distance'], 0)
        end = HEADER_SIZE + result['data_bytes']
        self.assertEqual(result['crc32'], zlib.crc32(raw[:end]) & 0xffffffff)
        self.assertEqual(result['header']['write_position'], result['data_bytes'])

    def test_two_warm_boots_are_recognised_and_labelled(self):
        _, result = self.capture(['boot one', 'boot two'])
        self.assertEqual(result['boot_count'], 2)
        first, second = result['boots']
        self.assertTrue(first['initialized_buffer'])
        self.assertFalse(first['kept_previous_buffer'])
        self.assertTrue(second['kept_previous_buffer'])
        self.assertFalse(second['initialized_buffer'])
        self.assertEqual(result['preamble_bytes'], 0)

    def test_magic_with_one_or_two_bit_damage_is_accepted_like_the_kernel(self):
        for flips in (1, 2):
            damaged = MAGIC_WORD ^ ((1 << flips) - 1)
            raw = build_ring([boot_stamp(0.1, 'WARMBOOT')], magic=struct.pack('<I', damaged))
            result = analyze(raw)
            self.assertEqual(result['header']['magic_bit_distance'], flips)
        self.assertEqual(magic_bit_distance(MAGIC_WORD), 0)

    def test_magic_damage_beyond_the_kernel_tolerance_is_rejected(self):
        damaged = struct.pack('<I', MAGIC_WORD ^ 0b111)
        with self.assertRaises(RingFormatError):
            analyze(build_ring([boot_stamp(0.1, 'WARMBOOT')], magic=damaged))

    def test_write_position_outside_capacity_is_rejected(self):
        raw = bytearray(build_ring([boot_stamp(0.1, 'WARMBOOT')]))
        struct.pack_into('<I', raw, 4, DEFAULT_CAPACITY + 1)
        with self.assertRaises(RingFormatError):
            analyze(bytes(raw))

    def test_short_capture_is_rejected_instead_of_truncated(self):
        raw = build_ring([boot_stamp(0.1, 'x' * 64)])
        with self.assertRaises(RingFormatError):
            analyze(raw[:HEADER_SIZE + 8])

    def test_preamble_before_the_first_boot_is_preserved(self):
        preamble = b'residual bytes from an older writer\n'
        raw = build_ring([preamble, boot_stamp(0.1, 'WARMBOOT')])
        result = analyze(raw)
        self.assertEqual(result['preamble_bytes'], len(preamble))
        self.assertEqual(result['text'][:len(preamble)], preamble)

    def test_capacity_bounds_are_checked(self):
        raw = build_ring([boot_stamp(0.1, 'WARMBOOT')])
        for capacity in (0, 0x100001):
            with self.assertRaises(RingFormatError):
                analyze(raw, capacity)


class RingReceiptTests(unittest.TestCase):
    RECEIPT = '\n'.join([
        'KLOG_RING_V1', 'valid=1', 'source=/proc/cmdline',
        'klog.addr=0x035a5000', 'klog.size=0x00020000',
        'ram=00000000-3fffffff System RAM', 'header.magic=klog',
        'header.write_position=33634', 'header.wrap=0', 'data_bytes=33634',
        'crc32=0x12345678', 'warmboot_markers=2', ''])

    def test_valid_receipt_is_parsed(self):
        receipt = parse_ring_info(self.RECEIPT)
        self.assertTrue(receipt['valid'])
        self.assertEqual(receipt['klog.address'], 0x035A5000)
        self.assertEqual(receipt['klog.capacity'], 0x20000)
        self.assertEqual(receipt['header.write_position'], 33634)
        self.assertEqual(receipt['crc32'], 0x12345678)

    def test_invalid_receipt_reports_the_daemon_error(self):
        receipt = parse_ring_info('KLOG_RING_V1\nvalid=0\nerror=klog_not_in_system_ram(-34)\n')
        self.assertFalse(receipt['valid'])
        self.assertEqual(receipt['error'], 'klog_not_in_system_ram(-34)')

    def test_foreign_or_incomplete_receipts_are_rejected(self):
        for text in ('', 'OTHER_V1\nvalid=1\n', 'KLOG_RING_V1\nvalid=1\nklog.addr=0x1\n'):
            with self.assertRaises(RingFormatError):
                parse_ring_info(text)

    def test_cross_check_passes_and_reports_each_dimension(self):
        raw = build_ring([boot_stamp(0.1, 'WARMBOOT')])
        result = analyze(raw)
        receipt = {'valid': True, 'klog.capacity': DEFAULT_CAPACITY,
                   'header.write_position': result['header']['write_position'],
                   'crc32': result['crc32'], 'data_bytes': result['data_bytes']}
        verification = cross_check(result, receipt)
        self.assertTrue(verification['verified'])
        self.assertEqual(len(verification['checks']), 4)

    def test_cross_check_rejects_a_tampered_capture(self):
        raw = build_ring([boot_stamp(0.1, 'WARMBOOT')])
        result = analyze(raw)
        receipt = {'valid': True, 'klog.capacity': DEFAULT_CAPACITY,
                   'header.write_position': result['header']['write_position'],
                   'crc32': result['crc32'] ^ 1, 'data_bytes': result['data_bytes']}
        with self.assertRaises(RingFormatError):
            cross_check(result, receipt)


if __name__ == '__main__':
    unittest.main()
