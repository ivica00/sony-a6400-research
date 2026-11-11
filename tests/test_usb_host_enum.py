"""Tests for the offline fail-closed UVC+PTP host enumeration module (E0614/E0321)."""

import json
import tempfile
import unittest
from pathlib import Path

from src.a6400.execution.usb_host_enum import (
    EXPECTED_DESCRIPTOR_LENGTH,
    EXPECTED_DESCRIPTOR_SHA256,
    EXPECTED_PTP_ENDPOINTS,
    EXPECTED_VIDEO_STREAMING_ENDPOINTS,
    SET_CONFIG_CATEGORY,
    SET_CONFIG_CONFIGURATION_VALUE,
    SET_CONFIG_FSM_EVENT,
    SET_CONFIG_MESSAGE_ID,
    SET_CONFIG_PARAM_ID,
    SET_CONFIG_PARAM_TYPE,
    SET_CONFIG_PARAM_VALUE,
    DescriptorHashMismatch,
    UnsupportedConfiguration,
    UnsupportedDescriptorLayout,
    UsbHostEnumError,
    load_configuration,
    load_descriptor_bytes,
    parse_configuration_descriptor,
    plan_set_configuration,
    select_uvc_ptp_configuration,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DESCRIPTOR_MANIFEST = (
    PROJECT_ROOT / 'artifacts' / 'native' / 'uvc-ptp-descriptors-e0154'
    / 'manifest.json')


def _valid_raw() -> bytes:
    data = json.loads(DESCRIPTOR_MANIFEST.read_text(encoding='utf-8'))
    return bytes.fromhex(data['configuration']['raw_hex'])


def _write_temp_manifest(root: Path,
                         raw: bytes,
                         name: str = 'descriptor.json') -> Path:
    path = root / name
    path.write_text(json.dumps({
        'e': 'E0154',
        'configuration': {'raw_hex': raw.hex()},
    }), encoding='utf-8')
    return path


class TestUsbHostEnumDescriptor(unittest.TestCase):
    """Descriptor facts pinned by E0154/E0317/E0321."""

    @classmethod
    def setUpClass(cls):
        cls.configuration, cls.provenance = load_configuration()

    def test_pinned_hash_and_length(self):
        raw, provenance = load_descriptor_bytes()
        self.assertEqual(len(raw), EXPECTED_DESCRIPTOR_LENGTH)
        self.assertEqual(provenance['descriptor_sha256'],
                         EXPECTED_DESCRIPTOR_SHA256)
        self.assertEqual(provenance['descriptor_length'],
                         EXPECTED_DESCRIPTOR_LENGTH)

    def test_configuration_header(self):
        cfg = self.configuration
        self.assertEqual(cfg.value, SET_CONFIG_CONFIGURATION_VALUE)
        self.assertEqual(cfg.total_length, EXPECTED_DESCRIPTOR_LENGTH)
        self.assertEqual(cfg.num_interfaces, 3)
        self.assertEqual([item.number for item in cfg.interfaces], [0, 1, 2])

    def test_ptp_interface_and_endpoints(self):
        ptp = [item for item in self.configuration.interfaces
               if item.kind == 'ptp']
        self.assertEqual(len(ptp), 1)
        interface = ptp[0]
        self.assertEqual((interface.number, interface.interface_class,
                          interface.interface_subclass,
                          interface.interface_protocol), (0, 0x06, 0x01, 0x01))
        self.assertEqual(tuple(
            f'0x{endpoint.address:02x}' for endpoint in interface.endpoints),
            EXPECTED_PTP_ENDPOINTS)
        by_address = {endpoint.address: endpoint
                      for endpoint in interface.endpoints}
        self.assertEqual(by_address[0x81].transfer_type, 'bulk')
        self.assertEqual(by_address[0x81].direction, 'in')
        self.assertEqual(by_address[0x81].max_packet_size, 512)
        self.assertEqual(by_address[0x02].transfer_type, 'bulk')
        self.assertEqual(by_address[0x02].direction, 'out')
        self.assertEqual(by_address[0x02].max_packet_size, 512)
        self.assertEqual(by_address[0x83].transfer_type, 'interrupt')
        self.assertEqual(by_address[0x83].direction, 'in')
        self.assertEqual(by_address[0x83].max_packet_size, 32)
        self.assertEqual(by_address[0x83].interval, 7)

    def test_video_control_and_streaming_endpoints(self):
        vc = [item for item in self.configuration.interfaces
              if item.kind == 'video_control']
        vs = [item for item in self.configuration.interfaces
              if item.kind == 'video_streaming']
        self.assertEqual(len(vc), 1)
        self.assertEqual(len(vs), 1)
        self.assertEqual(vc[0].number, 1)
        self.assertEqual(vs[0].number, 2)
        self.assertEqual(vc[0].endpoints, ())
        self.assertEqual(tuple(f'0x{endpoint.address:02x}'
                               for endpoint in vs[0].endpoints),
                         EXPECTED_VIDEO_STREAMING_ENDPOINTS)
        self.assertEqual(vs[0].endpoints[0].transfer_type, 'bulk')
        self.assertEqual(vs[0].endpoints[0].max_packet_size, 512)

    def test_interface_association(self):
        associations = [item for item in self.configuration.associations
                        if item.function_class == 0x0e]
        self.assertEqual(len(associations), 1)
        association = associations[0]
        self.assertEqual((association.first_interface,
                          association.interface_count,
                          association.function_subclass), (1, 2, 3))

    def test_provenance_chain(self):
        provenance = self.provenance
        self.assertEqual(provenance['e'], 'E0322')
        self.assertEqual(provenance['linked_e'], 'E0321')
        self.assertEqual(provenance['descriptor_sha256'],
                         EXPECTED_DESCRIPTOR_SHA256)
        self.assertTrue(provenance['descriptor_manifest'].endswith(
            'manifest.json'))


class TestUsbHostEnumPlan(unittest.TestCase):
    """SET_CONFIGURATION planning for the decoded UsbControl path."""

    def test_plan_set_configuration_verified_value(self):
        plan = plan_set_configuration(1)
        request = plan['request']
        self.assertEqual(request['configuration_value'], 1)
        self.assertEqual(request['category'], SET_CONFIG_CATEGORY)
        self.assertEqual(request['message_id'], SET_CONFIG_MESSAGE_ID)
        self.assertEqual(request['params'], [{
            'id': SET_CONFIG_PARAM_ID,
            'type': SET_CONFIG_PARAM_TYPE,
            'value': SET_CONFIG_PARAM_VALUE,
        }])
        event = plan['event']
        self.assertEqual(event['category'], SET_CONFIG_CATEGORY)
        self.assertEqual(event['message_id'], SET_CONFIG_MESSAGE_ID)
        self.assertEqual(event['param_0x1006'], SET_CONFIG_PARAM_VALUE)
        self.assertEqual(event['fsm_event'], SET_CONFIG_FSM_EVENT)

    def test_plan_endpoint_counts(self):
        counts = plan_set_configuration(1)['configuration']['endpoint_counts']
        self.assertEqual(counts, {'ptp': 3, 'video_control': 0,
                                  'video_streaming': 1})

    def test_plan_provenance(self):
        provenance = plan_set_configuration(1)['provenance']
        self.assertEqual(provenance['descriptor_sha256'],
                         EXPECTED_DESCRIPTOR_SHA256)
        self.assertEqual(provenance['descriptor_length'],
                         EXPECTED_DESCRIPTOR_LENGTH)

    def test_plan_refuses_unknown_configuration(self):
        for value in (0, 2, 0x100, -1, True, '1', None):
            with self.subTest(value=value):
                with self.assertRaises(UnsupportedConfiguration):
                    plan_set_configuration(value)


class TestUsbHostEnumRefusals(unittest.TestCase):
    """Fail-closed behavior: no fallback, no fabricated descriptor."""

    def test_hash_mismatch_refused_before_parse(self):
        raw = bytearray(_valid_raw())
        raw[3] ^= 0x01  # same length, changed wTotalLength/hash
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_temp_manifest(Path(tmp), bytes(raw))
            with self.assertRaises(DescriptorHashMismatch):
                load_descriptor_bytes(descriptor_manifest_path=path)

    def test_missing_descriptor_manifest_refused(self):
        with self.assertRaises(UsbHostEnumError):
            load_descriptor_bytes(
                descriptor_manifest_path=PROJECT_ROOT / 'missing.json')

    def test_bad_enablement_manifest_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'bad-enablement.json'
            path.write_text(json.dumps({'e': 'NOT-A-MANIFEST'}),
                            encoding='utf-8')
            with self.assertRaises(UsbHostEnumError):
                load_descriptor_bytes(enablement_manifest_path=path)

    def test_unknown_layout_refused(self):
        raw = bytearray(_valid_raw())
        # PTP interface class byte offset: config header 9 + interface class 5.
        raw[14] = 0x07
        with self.assertRaises(UnsupportedDescriptorLayout):
            select_uvc_ptp_configuration(
                parse_configuration_descriptor(bytes(raw)))

    def test_truncated_descriptor_refused(self):
        with self.assertRaises(UnsupportedDescriptorLayout):
            parse_configuration_descriptor(_valid_raw()[:-1])

    def test_non_configuration_blob_refused(self):
        with self.assertRaises(UnsupportedDescriptorLayout):
            parse_configuration_descriptor(b'\x09' * 64)

    def test_unsupported_configuration_value_in_select(self):
        cfg, _ = load_configuration()
        # A non-1 config value is refused before layout validation.
        from dataclasses import replace
        with self.assertRaises(UnsupportedConfiguration):
            select_uvc_ptp_configuration(replace(cfg, value=2))


if __name__ == '__main__':
    unittest.main()
