import struct
import unittest

from src.a6400.execution.zve10_uvc_enablement import (
    ZVE10_UVC_COMPONENTS,
    ZVE10_REQUIRED_USB_NODES,
    ZVE10_VERMAGIC,
    ZVE10_API_SYMBOLS,
    A6400_DEVNO_SHA256,
    assess_enablement_hygiene,
    assess_load_authorization,
    compare_components,
    enablement_verdict,
    model_devno_usb_namespace,
    parse_devno_table,
    verify_api_symbols,
    verify_component_hashes,
    verify_vermagic,
)


def _devno(table_rows, names):
    rows = b''.join(struct.pack('<III', *row) for row in table_rows)
    return rows, names


class TestZve10UvcEnablement(unittest.TestCase):
    """E0321: enablement manifest helpers (pure, no firmware access)."""

    def _devno_table(self):
        names = b'nflasha\x00usb/audio\x00usb/video\x00'
        rows = b''.join([
            struct.pack('<III', 0, 0x00FC0001, 0x200000),
            struct.pack('<III', 8, 0x00F80000, 0x10020),
            struct.pack('<III', 18, 0x00F80000, 0x10021),
        ])
        return rows, names

    def test_parse_devno_table(self):
        table, names = self._devno_table()
        entries = parse_devno_table(table, names)
        self.assertEqual(entries['nflasha']['major'], 252)
        self.assertEqual(entries['nflasha']['minor'], 1)
        self.assertEqual(entries['usb/audio']['major'], 248)
        self.assertEqual(entries['usb/audio']['minor'], 0x20)
        self.assertEqual(entries['usb/video']['major'], 248)
        self.assertEqual(entries['usb/video']['minor'], 0x21)

    def test_parse_requires_anchor(self):
        self.assertEqual(parse_devno_table(b'\x00' * 24, b'no-anchor'), {})

    def test_parse_keeps_entries_without_anchor_mismatch(self):
        table, names = _devno([(0x100, 0x00F80020, 0x10020)],
                              b'nflasha\x00usb/audio\x00')
        # An offset past the name blob is refused, not guessed.
        self.assertEqual(parse_devno_table(table, names), {})

    def test_compare_components(self):
        name = 'usbg_video.ko'
        pinned = ZVE10_UVC_COMPONENTS[name]
        verified = {name: {'size': pinned['size'], 'sha256': pinned['sha256']}}
        report = compare_components(verified)
        self.assertEqual(report[name]['status'], 'verified')
        for other in ZVE10_UVC_COMPONENTS:
            if other != name:
                self.assertEqual(report[other]['status'], 'missing')

    def test_verify_component_hashes_refusals(self):
        pinned = ZVE10_UVC_COMPONENTS['usbg_video.ko']
        good = verify_component_hashes({
            'usbg_video.ko': {'size': pinned['size'],
                              'sha256': pinned['sha256']}})
        self.assertFalse(good['verified'])
        self.assertTrue(any('component_missing' in r for r in good['refusals']))
        bad = verify_component_hashes({
            'usbg_video.ko': {'size': pinned['size'], 'sha256': '0' * 64}})
        self.assertFalse(bad['verified'])
        self.assertTrue(any('component_hash_mismatch' in r
                            for r in bad['refusals']))

    def test_vermagic_verification(self):
        equal = verify_vermagic({'usbg_video.ko': ZVE10_VERMAGIC})
        self.assertTrue(equal['equal'])
        self.assertEqual(equal['refusals'], [])
        mismatch = verify_vermagic({'usbg_video.ko': 'wrong vermagic'})
        self.assertFalse(mismatch['equal'])
        self.assertTrue(any('vermagic_mismatch' in r
                            for r in mismatch['refusals']))
        missing = verify_vermagic({'usbg_video.ko': None})
        self.assertFalse(missing['equal'])
        self.assertTrue(any('vermagic_missing' in r
                            for r in missing['refusals']))
        empty = verify_vermagic({})
        self.assertFalse(empty['equal'])

    def test_api_symbol_verification(self):
        good_providers = {'usbg_cmn.ko': ZVE10_API_SYMBOLS['providers']}
        good_consumers = {'usbg_video.ko':
                          tuple(ZVE10_API_SYMBOLS['consumers']) +
                          tuple(ZVE10_API_SYMBOLS['consumer_specific']
                                ['usbg_video.ko'])}
        ok = verify_api_symbols(good_providers, good_consumers)
        self.assertTrue(ok['ok'])
        self.assertEqual(ok['refusals'], [])
        missing_provider = verify_api_symbols(
            {'usbg_cmn.ko': ('usbg_cmn_reg',)}, good_consumers)
        self.assertFalse(missing_provider['ok'])
        self.assertTrue(any('api_provider_missing' in r
                            for r in missing_provider['refusals']))
        missing_consumer = verify_api_symbols(
            good_providers, {'usbg_video.ko': ('osal_snd_msg',)})
        self.assertFalse(missing_consumer['ok'])
        self.assertTrue(any('api_consumer_missing' in r
                            for r in missing_consumer['refusals']))
        empty = verify_api_symbols({}, {})
        self.assertFalse(empty['ok'])
        self.assertEqual(len(empty['refusals']), 2)

    def test_devno_namespace_model_positive(self):
        table, names = self._devno_table()
        entries = parse_devno_table(table, names)
        model = model_devno_usb_namespace(entries)
        self.assertTrue(model['registered'])
        self.assertFalse(model['installable'])
        self.assertEqual(model['install_policy'],
                         'declared_overlay_only_no_write')
        audio = model['nodes']['/dev/usb/audio']
        video = model['nodes']['/dev/usb/video']
        self.assertEqual(audio['found_dev'], '248:32')
        self.assertEqual(video['found_dev'], '248:33')
        self.assertTrue(audio['registered'] and audio['spec_matches'])
        self.assertTrue(video['registered'] and video['spec_matches'])
        self.assertEqual(model['refusals'], [])

    def test_devno_namespace_model_absent_nodes(self):
        model = model_devno_usb_namespace({})
        self.assertFalse(model['registered'])
        self.assertEqual(sorted(model['missing']),
                         sorted(ZVE10_REQUIRED_USB_NODES))
        self.assertTrue(any('device_node_absent' in r
                            for r in model['refusals']))

    def test_devno_namespace_model_mismatched_nodes(self):
        table, names = _devno(
            [(0, 0x00FC0001, 0x200000),
             (8, 0x00F80000, 0x10021),
             (18, 0x00F80000, 0x10020)],
            b'nflasha\x00usb/audio\x00usb/video\x00')
        model = model_devno_usb_namespace(parse_devno_table(table, names))
        self.assertFalse(model['registered'])
        self.assertIn('/dev/usb/audio', model['mismatched'])
        self.assertIn('/dev/usb/video', model['mismatched'])
        self.assertTrue(any('device_node_mismatch' in r
                            for r in model['refusals']))

    def test_devno_namespace_model_rejects_non_usb_major(self):
        entries = {'usb/video': {'major': 247, 'minor': 33},
                   'usb/audio': {'major': 248, 'minor': 32},
                   'usb/bogus': {'major': 247, 'minor': 9}}
        model = model_devno_usb_namespace(entries)
        self.assertFalse(model['registered'])
        self.assertTrue(any('device_node_invalid_usb_major' in r
                            for r in model['refusals']))

    def test_load_authorization_default_refusal(self):
        refused = assess_load_authorization(None)
        self.assertFalse(refused['authorized'])
        self.assertEqual(refused['refusal'], 'load_unauthorized')
        self.assertEqual(len(refused['reasons']), 4)
        partial = assess_load_authorization({'authorized': True})
        self.assertFalse(partial['authorized'])
        full = assess_load_authorization({
            'authorized': True, 'explicit_scope': True,
            'recovery_plan': True, 'teardown_receipts': True})
        self.assertTrue(full['authorized'])
        self.assertIsNone(full['refusal'])

    def test_hygiene_blocked_by_default_and_never_executable(self):
        pinned = ZVE10_UVC_COMPONENTS
        present = {name: {'size': row['size'], 'sha256': row['sha256']}
                   for name, row in pinned.items()}
        table, names = self._devno_table()
        entries = parse_devno_table(table, names)
        hygiene = assess_enablement_hygiene(
            present, entries,
            vermagic_by_component={'usbg_video.ko': ZVE10_VERMAGIC},
            provider_symbols={'usbg_cmn.ko': ZVE10_API_SYMBOLS['providers']},
            consumer_symbols={'usbg_video.ko':
                              tuple(ZVE10_API_SYMBOLS['consumers']) +
                              tuple(ZVE10_API_SYMBOLS['consumer_specific']
                                    ['usbg_video.ko'])},

            load_authorization=None)
        self.assertFalse(hygiene['ready'])
        self.assertTrue(hygiene['refusals'])
        self.assertFalse(hygiene['executable'])
        self.assertEqual(hygiene['readiness'], 'blocked')
        # Even with an explicit, complete authorization the offline gate stays
        # non-executable (physical load is a separate scope).
        authorized = assess_enablement_hygiene(
            present, entries,
            vermagic_by_component={'usbg_video.ko': ZVE10_VERMAGIC},
            provider_symbols={'usbg_cmn.ko': ZVE10_API_SYMBOLS['providers']},
            consumer_symbols={'usbg_video.ko':
                              tuple(ZVE10_API_SYMBOLS['consumers']) +
                              tuple(ZVE10_API_SYMBOLS['consumer_specific']
                                    ['usbg_video.ko'])},

            load_authorization={'authorized': True, 'explicit_scope': True,
                                'recovery_plan': True,
                                'teardown_receipts': True})
        self.assertTrue(authorized['ready'])
        self.assertFalse(authorized['executable'])
        self.assertEqual(authorized['readiness'], 'blocked')

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
        self.assertEqual(ZVE10_REQUIRED_USB_NODES['/dev/usb/audio']['minor'], 0x20)
        self.assertEqual(len(ZVE10_UVC_COMPONENTS), 5)
        self.assertEqual(ZVE10_VERMAGIC,
                         '3.0.27_nl-rt106+ SMP preempt mod_unload ARMv7')

