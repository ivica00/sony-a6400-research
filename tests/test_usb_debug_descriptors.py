import struct
import unittest

from src.a6400 import usb_debug_descriptors as d


def msc_config():
    config = struct.pack('<BBHBBBBB', 9, 2, 32, 1, 1, 0x80, 250, 0)
    interface = struct.pack('<BBBBBBBBB', 9, 4, 0, 0, 2, 8, 6, 0x50, 0)
    ep_in = struct.pack('<BBBBHB', 7, 5, 0x81, 2, 512, 0)
    ep_out = struct.pack('<BBBBHB', 7, 5, 0x02, 2, 512, 0)
    return config + interface + ep_in + ep_out


def ptp_uvc_config():
    config = struct.pack('<BBHBBBBB', 9, 2, 9 + 9 + 7 * 3 + 9 + 9 + 7, 3, 1, 0x80, 250, 0)
    ptp = struct.pack('<BBBBBBBBB', 9, 4, 0, 0, 3, 6, 1, 1, 0)
    eps = (struct.pack('<BBBBHB', 7, 5, 0x81, 2, 512, 0)
           + struct.pack('<BBBBHB', 7, 5, 0x02, 2, 512, 0)
           + struct.pack('<BBBBHB', 7, 5, 0x83, 3, 32, 7))
    vc = struct.pack('<BBBBBBBBB', 9, 4, 1, 0, 0, 0x0E, 1, 0, 0)
    vs = struct.pack('<BBBBBBBBB', 9, 4, 2, 0, 1, 0x0E, 2, 0, 0)
    vs_ep = struct.pack('<BBBBHB', 7, 5, 0x84, 2, 512, 0)
    return config + ptp + eps + vc + vs + vs_ep


class DescriptorMergeTests(unittest.TestCase):
    def test_msc_configuration_gets_one_vendor_interface(self):
        base = msc_config()
        result = d.merge_vendor_interface(base)
        merged = result['bytes']
        self.assertEqual(result['interface_number'], 1)
        self.assertEqual(result['in_endpoint'], 0x85)
        self.assertEqual(result['out_endpoint'], 0x05)
        self.assertEqual(struct.unpack_from('<H', merged, 2)[0], len(merged))
        self.assertEqual(merged[4], 2)
        descriptors = list(d._walk(merged))
        self.assertEqual([kind for _, _, kind in descriptors].count(d.DESCRIPTOR_INTERFACE), 2)
        vendor_at = descriptors[-3][0]
        self.assertEqual(merged[vendor_at + 5], d.VENDOR_INTERFACE_CLASS)
        self.assertEqual(merged[vendor_at + 6], d.VENDOR_INTERFACE_SUBCLASS)
        self.assertEqual(merged[vendor_at + 7], d.VENDOR_INTERFACE_PROTOCOL)
        self.assertEqual(merged[vendor_at + 2], 1)
        self.assertEqual(merged[vendor_at + 4], 2)

    def test_composite_configuration_gets_next_free_interface_and_endpoints(self):
        result = d.merge_vendor_interface(ptp_uvc_config())
        self.assertEqual(result['interface_number'], 3)
        self.assertEqual(result['base_endpoints'], [0x02, 0x81, 0x83, 0x84])
        merged = result['bytes']
        self.assertEqual(struct.unpack_from('<H', merged, 2)[0], len(merged))
        self.assertEqual(merged[4], 4)

    def test_endpoint_and_interface_collisions_are_rejected(self):
        base = msc_config()
        with self.assertRaises(d.DescriptorError):
            d.merge_vendor_interface(base, in_address=0x81)
        with self.assertRaises(d.DescriptorError):
            d.merge_vendor_interface(base, out_address=0x02)
        with self.assertRaises(d.DescriptorError):
            d.merge_vendor_interface(base, interface_number=0)

    def test_structural_inconsistency_is_rejected(self):
        broken = bytearray(msc_config())
        broken[4] = 5
        with self.assertRaises(d.DescriptorError):
            d.merge_vendor_interface(bytes(broken))
        with self.assertRaises(d.DescriptorError):
            d.merge_vendor_interface(b'\x00' * 9)
        with self.assertRaises(d.DescriptorError):
            d.merge_vendor_interface(msc_config()[:-3])

    def test_interface_descriptor_rejects_bad_endpoint_pairing(self):
        with self.assertRaises(d.DescriptorError):
            d.vendor_interface_bytes(1, in_address=0x05, out_address=0x85)
        with self.assertRaises(d.DescriptorError):
            d.vendor_interface_bytes(1, in_address=0x05, out_address=0x05)


class MicrosoftOsDescriptorTests(unittest.TestCase):
    def test_os_string_descriptor_matches_the_ms_os_1_0_layout(self):
        raw = d.ms_os_string_descriptor()
        self.assertEqual(len(raw), 18)
        self.assertEqual(raw[0], 0x12)
        self.assertEqual(raw[1], 0x03)
        self.assertEqual(raw[2:16].decode('utf-16-le'), 'MSFT100')
        self.assertEqual(raw[16], d.MS_OS_VENDOR_CODE)
        self.assertEqual(raw[17], 0)

    def test_compat_id_descriptor_matches_the_ms_os_1_0_layout(self):
        raw = d.ms_os_compat_id_descriptor(3)
        self.assertEqual(len(raw), 40)
        length, version, index, count = struct.unpack_from('<IHHB', raw, 0)
        self.assertEqual((length, version, index, count), (40, 0x0100, 0x0004, 1))
        self.assertEqual(raw[9:16], b'\0' * 7)
        self.assertEqual(raw[16], 3)
        self.assertEqual(raw[17], 0)
        self.assertEqual(raw[18:26], b'WINUSB\0\0')
        self.assertEqual(raw[26:40], b'\0' * 14)

    def test_binding_validation_accepts_correct_payloads_and_rejects_tampering(self):
        string = d.ms_os_string_descriptor()
        compat = d.ms_os_compat_id_descriptor(2)
        verified = d.validate_winusb_binding(string, compat, 2)
        self.assertTrue(verified['verified'])
        self.assertEqual(verified['compatible_id'], 'WINUSB')
        for bad_string, bad_compat in (
                (string[:17], compat),
                (string[:16] + b'\x02', compat),
                (string, compat[:39]),
                (string, compat[:18] + b'NOTUSB\0\0' + compat[26:])):
            with self.assertRaises(d.DescriptorError):
                d.validate_winusb_binding(bad_string, bad_compat, 2)

    def test_ep0_model_answers_only_the_ms_os_requests(self):
        os_string = bytes([0x80, 0x06, 0xEE, 0x03, 0x00, 0x00, 18, 0])
        reply = d.ep0_reply(os_string, 3)
        self.assertTrue(reply['handled'])
        self.assertEqual(reply['name'], 'ms_os_string')
        self.assertEqual(len(reply['payload']), 18)
        compat = bytes([0xC0, d.MS_OS_VENDOR_CODE, 0x00, 0x00, 0x04, 0x00, 40, 0])
        reply = d.ep0_reply(compat, 3)
        self.assertTrue(reply['handled'])
        self.assertEqual(reply['name'], 'ms_os_compat_id')
        self.assertEqual(len(reply['payload']), 40)
        other = bytes([0x80, 0x06, 0x00, 0x01, 0x00, 0x00, 64, 0])  # device descriptor
        self.assertFalse(d.ep0_reply(other, 3)['handled'])
        short = bytes([0x80, 0x06, 0xEE, 0x03, 0x00, 0x00, 4, 0])
        self.assertEqual(d.ep0_reply(short, 3)['payload'], d.ms_os_string_descriptor()[:4])


class MicrosoftOs20DescriptorTests(unittest.TestCase):
    def test_os_20_string_descriptor_matches_the_signature(self):
        raw = d.ms_os_20_string_descriptor()
        self.assertEqual(len(raw), 18)
        self.assertEqual(raw[0], 0x12)
        self.assertEqual(raw[1], 0x03)
        self.assertEqual(raw[2:16].decode('utf-16-le'), 'MSFT20\0')
        self.assertEqual(raw[16], d.MS_OS_20_VENDOR_CODE)
        self.assertEqual(raw[17], 0)

    def test_descriptor_set_is_a_winusb_compatible_id_feature(self):
        raw = d.ms_os_20_descriptor_set()
        self.assertEqual(len(raw), 30)
        length, kind, version, total = struct.unpack_from('<HHIH', raw, 0)
        self.assertEqual((length, kind, version, total), (30, 0, d.MS_OS_20_WINDOWS_VERSION_8_1, 30))
        feature_length, feature_type = struct.unpack_from('<HH', raw, 10)
        self.assertEqual((feature_length, feature_type), (20, d.MS_OS_20_FEATURE_COMPATIBLE_ID))
        self.assertEqual(raw[14:22], b'WINUSB\0\0')
        self.assertEqual(raw[22:30], b'\0' * 8)

    def test_vendor_request_model_returns_the_set_only_for_index_7(self):
        descriptor_set = d.ms_os_20_descriptor_set()
        request = bytes([0xC0, d.MS_OS_20_VENDOR_CODE, 0, 0, 7, 0, 30, 0])
        reply = d.ms_os_20_vendor_reply(request, descriptor_set)
        self.assertTrue(reply['handled'])
        self.assertEqual(reply['payload'], descriptor_set)
        short = bytes([0xC0, d.MS_OS_20_VENDOR_CODE, 0, 0, 7, 0, 10, 0])
        self.assertEqual(len(d.ms_os_20_vendor_reply(short, descriptor_set)['payload']), 10)
        subset = bytes([0xC0, d.MS_OS_20_VENDOR_CODE, 0, 0, 8, 0, 12, 0])
        reply = d.ms_os_20_vendor_reply(subset, descriptor_set)
        self.assertTrue(reply['handled'])
        self.assertEqual(reply['payload'], descriptor_set[10:22])
        wrong = bytes([0xC0, 0x03, 0, 0, 7, 0, 30, 0])
        self.assertFalse(d.ms_os_20_vendor_reply(wrong, descriptor_set)['handled'])

    def test_binding_validation_enforces_bcdusb_and_the_set(self):
        device = struct.pack('<BBHBBBB', 18, 1, 0x0210, 0, 0, 0, 64)
        verified = d.validate_winusb_20_binding(device, d.ms_os_20_descriptor_set())
        self.assertTrue(verified['verified'])
        self.assertEqual(verified['compatible_id'], 'WINUSB')
        old = struct.pack('<BBHBBBB', 18, 1, 0x0200, 0, 0, 0, 64)
        with self.assertRaises(d.DescriptorError):
            d.validate_winusb_20_binding(old, d.ms_os_20_descriptor_set())
        tampered = bytearray(d.ms_os_20_descriptor_set())
        tampered[14:22] = b'NOTUSB\0\0'
        with self.assertRaises(d.DescriptorError):
            d.validate_winusb_20_binding(device, bytes(tampered))


class MicrosoftOs20CompositeTests(unittest.TestCase):
    def test_composite_set_has_configuration_and_function_subsets(self):
        raw = d.ms_os_20_composite_descriptor_set(1, 1)
        self.assertEqual(len(raw), 46)
        self.assertTrue(d.validate_winusb_20_composite_binding(raw, 1, 1)['verified'])
        # Descriptor-set header, configuration subset header, function subset
        # header, compatible-ID feature.
        self.assertEqual(struct.unpack_from('<HHIH', raw, 0), (46, 0, 0x06030000, 46))
        self.assertEqual(struct.unpack_from('<HHBBH', raw, 10), (36, 1, 1, 0, 36))
        self.assertEqual(struct.unpack_from('<HHBBH', raw, 18), (28, 2, 1, 0, 28))
        self.assertEqual(struct.unpack_from('<HH', raw, 26), (20, 3))
        self.assertEqual(raw[30:38], b'WINUSB\0\0')

    def test_composite_validation_rejects_wrong_scope_and_lengths(self):
        raw = d.ms_os_20_composite_descriptor_set(1, 2)
        with self.assertRaises(d.DescriptorError):
            d.validate_winusb_20_composite_binding(raw, 1, 1)
        tampered = bytearray(d.ms_os_20_composite_descriptor_set(1, 1))
        tampered[6:8] = struct.pack('<H', 45)
        with self.assertRaises(d.DescriptorError):
            d.validate_winusb_20_composite_binding(bytes(tampered), 1, 1)
        tampered = bytearray(d.ms_os_20_composite_descriptor_set(1, 1))
        tampered[30:38] = b'NOTUSB\0\0'
        with self.assertRaises(d.DescriptorError):
            d.validate_winusb_20_composite_binding(bytes(tampered), 1, 1)

    def test_vendor_reply_serves_whole_set_and_configuration_subset(self):
        raw = d.ms_os_20_composite_descriptor_set(1, 1)
        whole = bytes([0xC0, d.MS_OS_20_VENDOR_CODE, 0, 0, 7, 0, 46, 0])
        reply = d.ms_os_20_vendor_reply(whole, raw)
        self.assertTrue(reply['handled'])
        self.assertEqual(reply['payload'], raw)
        subset = bytes([0xC0, d.MS_OS_20_VENDOR_CODE, 0, 0, 8, 0, 36, 0])
        reply = d.ms_os_20_vendor_reply(subset, raw)
        self.assertTrue(reply['handled'])
        self.assertEqual(reply['payload'], raw[10:])


if __name__ == '__main__':
    unittest.main()
