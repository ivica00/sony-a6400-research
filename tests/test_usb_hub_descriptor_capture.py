import unittest

from tools.research.capture_sony_usb_hub import parse_configuration


class UsbHubDescriptorTests(unittest.TestCase):
    RAW = bytes.fromhex('0902270001010080fa090400000306010100070581020002000705020200020007058303200007')

    def test_physical_pc_remote_descriptor(self):
        config = parse_configuration(self.RAW)
        interface = config['interfaces'][0]
        self.assertEqual(interface['class'], 6)
        self.assertEqual([e['address'] for e in interface['endpoints']], ['0x81', '0x2', '0x83'])
        self.assertEqual([e['attributes'] for e in interface['endpoints']], [2, 2, 3])

    def test_truncated_capture_rejected(self):
        with self.assertRaises(ValueError):
            parse_configuration(self.RAW[:-1])

    def test_zero_length_descriptor_rejected(self):
        raw = bytearray(self.RAW)
        raw[18] = 0
        with self.assertRaises(ValueError):
            parse_configuration(raw)

    def test_endpoint_count_mismatch_rejected(self):
        raw = bytearray(self.RAW)
        raw[13] = 2
        with self.assertRaises(ValueError):
            parse_configuration(raw)

    def test_interface_count_mismatch_rejected(self):
        raw = bytearray(self.RAW)
        raw[4] = 2
        with self.assertRaises(ValueError):
            parse_configuration(raw)
