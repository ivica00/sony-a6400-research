import struct
import unittest

from src.a6400.execution.zve10_uvc_enablement import (
    ZVE10_UVC_COMPONENTS,
    ZVE10_REQUIRED_USB_NODES,
    A6400_DEVNO_SHA256,
    compare_components,
    enablement_verdict,
    parse_devno_table,
)


class TestZve10UvcEnablement(unittest.TestCase):
    """E0321: enablement manifest helpers (pure, no firmware access)."""

    def _devno_table(self):
        names = b'nflasha\x00usb/video\x00'
        rows = b''.join([
            struct.pack('<III', 0, 0x00FC0001, 0x200000),
            struct.pack('<III', 8, 0x00F80000, 0x10021),
        ])
        return rows, names

    def test_parse_devno_table(self):
        table, names = self._devno_table()
        entries = parse_devno_table(table, names)
        self.assertEqual(entries['nflasha']['major'], 252)
        self.assertEqual(entries['nflasha']['minor'], 1)
        self.assertEqual(entries['usb/video']['major'], 248)
        self.assertEqual(entries['usb/video']['minor'], 0x21)

    def test_parse_requires_anchor(self):
        self.assertEqual(parse_devno_table(b'\x00' * 24, b'no-anchor'), {})

    def test_compare_components(self):
        name = 'usbg_video.ko'
        pinned = ZVE10_UVC_COMPONENTS[name]
        verified = {name: {'size': pinned['size'], 'sha256': pinned['sha256']}}
        report = compare_components(verified)
        self.assertEqual(report[name]['status'], 'verified')
        for other in ZVE10_UVC_COMPONENTS:
            if other != name:
                self.assertEqual(report[other]['status'], 'missing')

    def test_verdict_ready_and_blocked(self):
        verified = {name: {'status': 'verified'}
                    for name in ZVE10_UVC_COMPONENTS}
        nodes = {path: {'major': row['major'], 'minor': row['minor']}
                 for path, row in ZVE10_REQUIRED_USB_NODES.items()}
        ready = enablement_verdict(verified, nodes, vermagic_equal=True)
        self.assertTrue(ready['enabled'])
        self.assertEqual(ready['verdict'], 'ready_for_declared_overlay')
        blocked = enablement_verdict(verified, {}, vermagic_equal=False)
        self.assertFalse(blocked['enabled'])
        self.assertTrue(any('device_node_gaps' in r for r in blocked['reasons']))
        self.assertIn('module_vermagic_mismatch', blocked['reasons'])

    def test_pinned_constants(self):
        self.assertEqual(len(A6400_DEVNO_SHA256), 64)
        self.assertEqual(ZVE10_REQUIRED_USB_NODES['/dev/usb/video']['minor'], 0x21)
        self.assertEqual(len(ZVE10_UVC_COMPONENTS), 5)
