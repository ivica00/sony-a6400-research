import unittest

from src.a6400.execution.guest_usb_video import (
    GuestUsbVideo,
    UnsupportedUsbVideo,
    ZVE10_USB_VIDEO_DEVICE,
    ZVE10_USB_AUDIO_DEVICE,
    A6400_DEVNO_SHA256,
    A6400_MISSING_USB_NODES,
    devno_usb_video_evidence,
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
