import unittest

from src.a6400.execution.guest_usb_video import (
    GuestUsbVideo,
    UnsupportedUsbVideo,
    ZVE10_USB_VIDEO_DEVICE,
    ZVE10_USB_AUDIO_DEVICE,
    A6400_DEVNO_SHA256,
    A6400_MISSING_USB_NODES,
    devno_usb_video_evidence,
    usb_video_gap_boundaries,
)
from src.a6400.execution.usb_video_contract import (
    USB_VIDEO_PROBE_INFO_SIZE,
    USB_VIDEO_REQUEST_OBJECT,
    USB_VIDEO_DMA_INFO_OBJECT,
)


class TestGuestUsbVideo(unittest.TestCase):
    """E0319/E0320: ZV-E10 device identity + fail-closed usbg_video model."""

    def setUp(self):
        self.dev = GuestUsbVideo()

    def test_device_identity(self):
        self.assertEqual(self.dev.major, 248)
        self.assertEqual(self.dev.minor, 0x21)
        self.assertEqual(self.dev.path, '/dev/usb/video')
        self.assertEqual(ZVE10_USB_AUDIO_DEVICE['minor'], 0x20)
        self.assertEqual(len(A6400_DEVNO_SHA256), 64)

    def test_open_close_transactions(self):
        owner = self.dev.open(flags=2, caller_pid=1018, caller_tgid=1000)
        self.assertIn(owner, self.dev.owners)
        self.assertEqual(self.dev.close(owner), 0)
        self.assertNotIn(owner, self.dev.owners)
        self.assertEqual([t['operation'] for t in self.dev.transactions],
                         ['open', 'close'])

    def test_known_ioctl_stops_explicitly(self):
        owner = self.dev.open(flags=2)
        with self.assertRaises(UnsupportedUsbVideo) as caught:
            self.dev.ioctl(owner, 0x4038E000, argument=0x1000)
        self.assertEqual(caught.exception.reason,
                         'usb_video_ioctl_contract_unresolved')
        self.assertEqual(caught.exception.details['name'], 'uvc_request_write')
        self.assertEqual(self.dev.stopped,
                         'usb_video_ioctl_contract_unresolved')
        ioctl = [t for t in self.dev.transactions
                 if t['operation'] == 'ioctl'][-1]
        self.assertTrue(ioctl['known'])

    def test_unknown_ioctl_records_generic_decode(self):
        owner = self.dev.open(flags=2)
        with self.assertRaises(UnsupportedUsbVideo):
            self.dev.ioctl(owner, 0x4038E001)
        ioctl = [t for t in self.dev.transactions
                 if t['operation'] == 'ioctl'][-1]
        self.assertFalse(ioctl['known'])

    def test_write_and_read_stop(self):
        owner = self.dev.open(flags=2)
        with self.assertRaises(UnsupportedUsbVideo) as caught:
            self.dev.write(owner, 512)
        self.assertEqual(caught.exception.reason,
                         'usb_video_write_buffer_contract_unresolved')
        with self.assertRaises(UnsupportedUsbVideo) as caught:
            self.dev.read(owner, 64)
        self.assertEqual(caught.exception.reason,
                         'usb_video_read_completion_contract_unresolved')

    def test_unknown_owner_rejected(self):
        with self.assertRaises(UnsupportedUsbVideo) as caught:
            self.dev.close(99)
        self.assertEqual(caught.exception.reason, 'usb_video_owner_unknown')

    def test_devno_evidence(self):
        evidence = devno_usb_video_evidence()
        self.assertEqual(evidence['a6400']['devno_sha256'],
                         A6400_DEVNO_SHA256)
        self.assertEqual(set(evidence['a6400']['missing_nodes']),
                         set(A6400_MISSING_USB_NODES))
        zve10 = evidence['zve10']['nodes']
        self.assertEqual([(n['major'], n['minor']) for n in zve10],
                         [(248, 0x20), (248, 0x21)])
        self.assertEqual(evidence['command_table'],
                         [0x0000E001, 0x4008F000, 0x4038E000])


class TestGuestUsbVideoGapContracts(unittest.TestCase):
    """E0319 gaps: probe-info/transfer decoding stays fail-closed."""

    def setUp(self):
        self.dev = GuestUsbVideo()

    def _probe_info(self):
        data = bytearray(USB_VIDEO_PROBE_INFO_SIZE)
        data[0x24:0x28] = (0x00010002).to_bytes(4, 'little')
        data[0x30:0x34] = (0).to_bytes(4, 'little')
        data[0x34:0x38] = (0).to_bytes(4, 'little')
        return bytes(data)

    def test_register_ioctl_parses_probe_info_then_stops(self):
        owner = self.dev.open(flags=2)
        with self.assertRaises(UnsupportedUsbVideo) as caught:
            self.dev.ioctl(owner, 0x4038E000, data=self._probe_info())
        self.assertEqual(caught.exception.reason,
                         'usb_video_register_probe_info_unresolved')
        self.assertEqual(
            caught.exception.details['probe_info']['probe_info']
            ['buffer_table_pointer'], 0x00010002)
        self.assertFalse(
            caught.exception.details['probe_info']['flags']
            ['buffer_table_size_checked'])
        probe = [t for t in self.dev.transactions
                 if t['operation'] == 'probe_info'][-1]
        self.assertEqual(probe['buffer_table_pointer'], 0x00010002)
        self.assertFalse(probe['blob_present'])

    def test_short_probe_info_rejected(self):
        owner = self.dev.open(flags=2)
        with self.assertRaises(UnsupportedUsbVideo) as caught:
            self.dev.ioctl(owner, 0x4038E000, data=b'\x00' * 0x37)
        self.assertEqual(caught.exception.reason,
                         'usb_video_probe_info_invalid')

    def test_transfer_ioctl_decodes_argument_then_stops(self):
        owner = self.dev.open(flags=2)
        raw = (0x12340000).to_bytes(4, 'little') + (0).to_bytes(4, 'little')
        with self.assertRaises(UnsupportedUsbVideo) as caught:
            self.dev.ioctl(owner, 0x4008F000, data=raw)
        self.assertEqual(caught.exception.reason,
                         'usb_video_transfer_contract_unresolved')
        self.assertEqual(caught.exception.details['expected_size'], 8)
        self.assertEqual(caught.exception.details['raw_value'], 0x12340000)

    def test_transfer_ioctl_wrong_argument_size_rejected(self):
        owner = self.dev.open(flags=2)
        with self.assertRaises(UnsupportedUsbVideo) as caught:
            self.dev.ioctl(owner, 0x4008F000, data=b'\x00' * 4)
        self.assertEqual(caught.exception.reason,
                         'usb_video_transfer_argument_invalid')

    def test_unregister_with_payload_rejected(self):
        owner = self.dev.open(flags=2)
        with self.assertRaises(UnsupportedUsbVideo) as caught:
            self.dev.ioctl(owner, 0x0000E001, data=b'\x01')
        self.assertEqual(caught.exception.reason, 'usb_video_ioctl_data_invalid')

    def test_ioctl_non_bytes_data_rejected(self):
        owner = self.dev.open(flags=2)
        with self.assertRaises(UnsupportedUsbVideo) as caught:
            self.dev.ioctl(owner, 0x4038E000, data='probe')
        self.assertEqual(caught.exception.reason, 'usb_video_ioctl_data_invalid')
        self.assertEqual(caught.exception.details['data_type'], 'str')

    def test_parse_open_objects_decodes_without_ownership(self):
        owner = self.dev.open(flags=2)
        request = b'\x00' * USB_VIDEO_REQUEST_OBJECT['size']
        dma = bytearray(USB_VIDEO_DMA_INFO_OBJECT['size'])
        dma[0x00:0x04] = (1).to_bytes(4, 'little')
        dma[0x04:0x08] = (1).to_bytes(4, 'little')
        result = self.dev.parse_open_objects(request_object=request,
                                             dma_info_object=bytes(dma))
        self.assertEqual(result['request_object']['size'], 0xD0)
        self.assertEqual(result['dma_info_object']['fields'][0x00]['value'], 1)
        self.assertEqual(result['operation'], 'open_objects')

    def test_parse_open_objects_rejects_short_buffers(self):
        owner = self.dev.open(flags=2)
        with self.assertRaises(UnsupportedUsbVideo) as caught:
            self.dev.parse_open_objects(request_object=b'\x00' * 4)
        self.assertEqual(caught.exception.reason,
                         'usb_video_request_object_invalid')
        with self.assertRaises(UnsupportedUsbVideo) as caught:
            self.dev.parse_open_objects(dma_info_object=b'\x00' * 4)
        self.assertEqual(caught.exception.reason,
                         'usb_video_dma_info_object_invalid')

    def test_frame_source_refused(self):
        owner = self.dev.open(flags=2)
        with self.assertRaises(UnsupportedUsbVideo) as caught:
            self.dev.frame_source('jpeg')
        self.assertEqual(caught.exception.reason,
                         'usb_video_frame_source_unresolved')
        self.assertEqual(caught.exception.details['kind'], 'jpeg')
        with self.assertRaises(UnsupportedUsbVideo) as caught:
            self.dev.frame_source('raw')
        self.assertEqual(caught.exception.reason,
                         'usb_video_frame_source_unknown')

    def test_write_pointer_bounds(self):
        owner = self.dev.open(flags=2)
        with self.assertRaises(UnsupportedUsbVideo) as caught:
            self.dev.write(owner, 512, data_info_pointer=self.dev.address_limit)
        self.assertEqual(caught.exception.reason,
                         'usb_video_write_argument_out_of_range')
        with self.assertRaises(UnsupportedUsbVideo) as caught:
            self.dev.write(owner, 512, data_info_pointer=0x13E6C0)
        self.assertEqual(caught.exception.reason,
                         'usb_video_write_buffer_contract_unresolved')
        self.assertEqual(caught.exception.details['data_info_pointer'],
                         0x13E6C0)

    def test_gap_boundaries_exposed(self):
        report = usb_video_gap_boundaries()
        self.assertEqual(report['request_object']['size'], 0xD0)
        self.assertEqual(report['dma_info_object']['size'], 0x24)
        self.assertEqual(report['context_count_writer']['writer'],
                         'unresolved_external')
        self.assertEqual(report['frame_source']['status'], 'unresolved')
