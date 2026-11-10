"""Fixtures for the offline PC Remote vs composite descriptor diff."""
import unittest

from tools.research.compare_pc_remote_descriptors import (config_summary, device_summary,
                                                         diff_summaries, iad_present)

PTP = {'number': 0, 'alternate': 0, 'class': 6, 'subclass': 1, 'protocol': 1,
       'endpoints': [
           {'address': '0x81', 'attributes': 2, 'max_packet': 512, 'interval': 0},
           {'address': '0x2', 'attributes': 2, 'max_packet': 512, 'interval': 0},
           {'address': '0x83', 'attributes': 3, 'max_packet': 32, 'interval': 7}]}
VC = {'number': 1, 'alternate': 0, 'class': 14, 'subclass': 1, 'protocol': 0, 'endpoints': []}
VS = {'number': 2, 'alternate': 0, 'class': 14, 'subclass': 2, 'protocol': 0,
      'endpoints': [{'address': '0x84', 'attributes': 2, 'max_packet': 512, 'interval': 0}]}


def config_hex(interfaces, iad=False):
    body = bytearray()
    if iad:
        body += bytes([8, 11, 1, 2, 14, 3, 0, 0])
    for interface in interfaces:
        body += bytes([9, 4, interface['number'], interface['alternate'],
                       len(interface['endpoints']), interface['class'],
                       interface['subclass'], interface['protocol'], 0])
        for endpoint in interface['endpoints']:
            packet = endpoint['max_packet']
            address = endpoint['address']
            if isinstance(address, str):
                address = int(address, 0)
            body += bytes([7, 5, address, endpoint['attributes'],
                           packet & 0xFF, packet >> 8, endpoint['interval']])
    total = 9 + len(body)
    return bytes([9, 2, total & 0xFF, total >> 8, 1, 1, 0, 0x80, 50]) + bytes(body)


def device(interfaces, device_class, iad=False):
    descriptor = bytes([18, 1, 0, 2, device_class[0], device_class[1], device_class[2], 64,
                        0x4C, 0x05, 0xAA, 0x0C, 0x00, 0x01, 1, 2, 3, 1])
    cfg = {'value': 1, 'raw_hex': config_hex(interfaces, iad).hex(), 'interfaces': interfaces}
    return {'vid': '0x54c', 'pid': '0xcaa', 'device_descriptor_hex': descriptor.hex(),
            'configurations': [cfg]}


class IadTests(unittest.TestCase):
    def test_present(self):
        self.assertTrue(iad_present(config_hex([PTP], iad=True)))
        self.assertFalse(iad_present(config_hex([PTP])))
        self.assertIsNone(iad_present(b'\x09\x02'))

    def test_summary(self):
        summary = config_summary({'value': 1, 'raw_hex': config_hex([PTP], iad=True).hex(),
                                  'interfaces': [PTP]})
        self.assertEqual(summary['interface_count'], 1)
        self.assertTrue(summary['iad_present'])
        self.assertEqual(summary['interfaces'][0]['endpoints'][0]['address'], '0x81')


class DiffTests(unittest.TestCase):
    def test_pc_vs_composite(self):
        pc = device([PTP], (0, 0, 0), iad=False)
        composite = device([PTP, VC, VS], (0xEF, 2, 1), iad=True)
        summary_pc = device_summary(pc)
        summary_composite = device_summary(composite)
        result = diff_summaries(summary_pc, summary_composite)
        self.assertEqual(summary_pc['vid'], '0x54c')
        self.assertEqual(summary_pc['device_class'], [0, 0, 0])
        self.assertEqual(summary_composite['device_class'], [0xEF, 2, 1])
        self.assertTrue(result['device_class_changed'])
        self.assertEqual((result['interface_count_pc'], result['interface_count_composite']), (1, 3))
        self.assertFalse(result['iad_pc'])
        self.assertTrue(result['iad_composite'])
        self.assertTrue(result['ptp_interface_equal'])
        self.assertEqual([i['number'] for i in result['composite_extra_interfaces']], [1, 2])


if __name__ == '__main__':
    unittest.main()
