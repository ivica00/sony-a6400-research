"""Constructed Thumb fixtures verify response/error flow and unknown-byte guards."""
import struct
import unittest

from tools.research.wbi_ma_client import consume


def fixture(status_load=b'\x58\x69'):
    raw = bytearray(0x1240)
    ident = b'\x7fELF' + bytes((1, 1, 1)) + bytes(9)
    raw[:52] = ident + struct.pack('<HHIIIIIHHHHHH', 3, 40, 1, 0x720987, 0, 0x1100,
                                  0x5000000, 52, 0, 0, 40, 3, 2)
    names = b'\0.text\0.shstrtab\0'
    raw[0x1200:0x1200 + len(names)] = names
    raw[0x1128:0x1150] = struct.pack('<10I', 1, 1, 6, 0x720000, 0x100, 4096, 0, 0, 4, 0)
    raw[0x1150:0x1178] = struct.pack('<10I', 7, 3, 0, 0, 0x1200, len(names), 0, 0, 1, 0)
    # ldr r3,[r4,#4]; ldr r0,[r3,#20]; pop {r3,r4,r7,pc}
    raw[0xa86:0xa8c] = b'\x63\x68' + status_load + b'\x98\xbd'
    # mov r5,r0; cbnz r0,error_boundary; movs r0,#184
    raw[0x100a:0x1010] = b'\x05\x46\xe8\xb9\xb8\x20'
    return bytes(raw)


def packet(status):
    return struct.pack('<HH16s4I', 7, 0, b'test', status & 0xffffffff, 0x12345000, 0x2000, 0xdeadbeef)


class ClientConsumerTests(unittest.TestCase):
    def test_original_style_thumb_status_flow_stops_before_allocation(self):
        result = consume(fixture(), packet(0))
        self.assertEqual(result['status'], 'operator_new_call_boundary')
        self.assertEqual(result['boundary']['requested_size'], 184)
        self.assertEqual(result['reads'][1]['bytes'], '00000000')

    def test_error_values_propagate_to_cleanup_without_allocation(self):
        for status in (-9, -257, -1):
            with self.subTest(status=status):
                result = consume(fixture(), packet(status))
                self.assertEqual(result['status'], 'lookup_error_cleanup_boundary')
                self.assertEqual(result['boundary']['error'], status & 0xffffffff)

    def test_mapped_response_padding_cannot_be_consumed_as_zero(self):
        # Change the fixture's load to [r3,#36], outside supplied packet bytes.
        result = consume(fixture(b'\x58\x6a'), packet(0))
        self.assertEqual(result['status'], 'unsupplied_read')
        self.assertEqual(result['boundary']['address'], 0x08200024)
