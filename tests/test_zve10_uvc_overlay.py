import unittest

from src.a6400.execution.zve10_uvc_enablement import (
    ZVE10_API_SYMBOLS,
    ZVE10_VERMAGIC,
    assess_enablement_hygiene,
)
from src.a6400.execution.zve10_uvc_overlay import (
    OVERLAY_DEVNO_NODES,
    OVERLAY_TARGETS,
    OVERLAY_OPEN_ITEMS,
    build_overlay_plan,
)


def manifest_with(statuses,
                  reasons=(),
                  hygiene=None,
                  load_authorization=None):
    manifest = {
        'component_check': {
            name: {'status': status, 'pinned_sha256': 'a' * 64}
            for name, status in statuses.items()
        },
        'verdict': {'reasons': list(reasons)},
    }
    if hygiene is not None:
        manifest['hygiene'] = hygiene
    if load_authorization is not None:
        manifest['load_authorization'] = load_authorization
    return manifest


def verified_manifest():
    statuses = {name: 'verified' for name in OVERLAY_TARGETS}
    return manifest_with(statuses, [])


def full_authorization():
    return {'authorized': True, 'explicit_scope': True,
            'recovery_plan': True, 'teardown_receipts': True}


class TestZve10UvcOverlayPlan(unittest.TestCase):
    """E0322: declared overlay plan is data-only and always fail-closed."""

    def test_blocked_when_components_missing(self):
        statuses = {name: 'missing' for name in OVERLAY_TARGETS}
        plan = build_overlay_plan(manifest_with(
            statuses, ['device_node_gaps: /dev/usb/video (absent)']))
        self.assertEqual(plan['readiness'], 'blocked')
        self.assertFalse(plan['executable'])
        self.assertTrue(plan['blocking_reasons'])
        self.assertEqual(len(plan['operations']), len(OVERLAY_TARGETS))

    def test_ready_components_still_blocked_and_non_executable(self):
        plan = build_overlay_plan(verified_manifest())
        self.assertEqual(plan['readiness'], 'blocked')
        self.assertFalse(plan['executable'])
        self.assertFalse(plan['would_be_ready_if_authorized'])
        # No load authorization was supplied: explicit refusal reason.
        self.assertTrue(any('load_authorization_missing' in reason
                            for reason in plan['blocking_reasons']))
        self.assertTrue(any('declared_plan_is_data_only' in reason
                            for reason in plan['blocking_reasons']))

    def test_never_ready_even_with_full_authorization(self):
        plan = build_overlay_plan(verified_manifest(),
                                  load_authorization=full_authorization())
        self.assertEqual(plan['readiness'], 'blocked')
        self.assertFalse(plan['executable'])
        self.assertTrue(plan['verification']['load_authorization']['authorized'])
        self.assertTrue(any('declared_plan_is_data_only' in reason
                            for reason in plan['blocking_reasons']))

    def test_operations_are_hash_pinned_and_targeted(self):
        plan = build_overlay_plan(manifest_with(
            {name: 'hash_mismatch' for name in OVERLAY_TARGETS}))
        by_component = {row['component']: row for row in plan['operations']}
        self.assertEqual(by_component['usbg_video.ko']['target'],
                         '/usr/kmod/usbg_video.ko')
        self.assertEqual(by_component['usbg_video.ko']['action'], 'add')
        self.assertEqual(by_component['libInfraUsbCmn.so']['target'],
                         '/usr/lib/libInfraUsbCmn.so')
        self.assertEqual(by_component['libInfraUsbCmn.so']['action'], 'replace')
        self.assertEqual(by_component['devno.ko']['action'], 'replace')
        for row in plan['operations']:
            self.assertEqual(row['pinned_sha256'], 'a' * 64)
            self.assertEqual(row['source_tree'], 'zve10')

    def test_devno_operation_carries_offline_node_model(self):
        plan = build_overlay_plan(verified_manifest())
        devno = {row['component']: row
                 for row in plan['operations']}['devno.ko']
        self.assertEqual(devno['node_registration_policy'],
                         'declared_overlay_only_no_write')
        registrations = {row['path']: row
                         for row in devno['node_registrations']}
        self.assertEqual(registrations['/dev/usb/audio']['dev'], '248:32')
        self.assertEqual(registrations['/dev/usb/video']['dev'], '248:33')
        self.assertEqual(plan['devno_namespace_model']['installable'], False)
        self.assertEqual(
            plan['devno_namespace_model']['install_policy'],
            'declared_overlay_only_no_write')
        self.assertEqual(set(OVERLAY_DEVNO_NODES),
                         {'/dev/usb/audio', '/dev/usb/video'})

    def test_refuses_when_nodes_absent(self):
        plan = build_overlay_plan(manifest_with(
            {name: 'verified' for name in OVERLAY_TARGETS},
            ['device_node_gaps: /dev/usb/audio (absent); /dev/usb/video (absent)']))
        self.assertEqual(plan['readiness'], 'blocked')
        self.assertTrue(any('device node' in reason.lower()
                            for reason in plan['blocking_reasons']))

    def test_refuses_unauthorized_load(self):
        plan = build_overlay_plan(verified_manifest(),
                                  load_authorization={
                                      'authorized': True,
                                      'explicit_scope': False,
                                      'recovery_plan': False,
                                      'teardown_receipts': False})
        self.assertFalse(plan['verification']['load_authorization']['authorized'])
        self.assertTrue(any('load_authorization_missing' in reason
                            for reason in plan['blocking_reasons']))

    def test_refuses_vermagic_and_api_gaps_from_hygiene(self):
        hygiene = assess_enablement_hygiene(
            {'components': {name: {'status': 'verified'}
                            for name in OVERLAY_TARGETS}},
            {},
            vermagic_by_component={'usbg_video.ko': 'wrong vermagic'},
            provider_symbols={'usbg_cmn.ko': ()},
            consumer_symbols={'usbg_video.ko': ()},
            load_authorization=full_authorization())
        plan = build_overlay_plan(manifest_with(
            {name: 'verified' for name in OVERLAY_TARGETS},
            hygiene=hygiene))
        self.assertEqual(plan['readiness'], 'blocked')
        reasons = ' '.join(plan['blocking_reasons'])
        self.assertIn('vermagic_mismatch', reasons)
        self.assertIn('api_provider_missing', reasons)
        self.assertIn('api_consumer_missing', reasons)

    def test_plan_never_claims_execution(self):
        plan = build_overlay_plan(verified_manifest())
        self.assertFalse(plan['executable'])
        self.assertTrue(plan['prerequisites'])
        self.assertEqual(plan['open_items'], list(OVERLAY_OPEN_ITEMS))
        self.assertEqual(plan['e'], 'E0322')
