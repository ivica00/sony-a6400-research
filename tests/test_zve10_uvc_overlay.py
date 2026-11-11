import unittest

from src.a6400.execution.zve10_uvc_overlay import (
    OVERLAY_TARGETS,
    OVERLAY_OPEN_ITEMS,
    build_overlay_plan,
)


def manifest_with(statuses, reasons=()):
    return {
        'component_check': {
            name: {'status': status, 'pinned_sha256': 'a' * 64}
            for name, status in statuses.items()
        },
        'verdict': {'reasons': list(reasons)},
    }


class TestZve10UvcOverlayPlan(unittest.TestCase):
    """E0322: declared overlay plan is data-only and fail-closed."""

    def test_blocked_when_components_missing(self):
        statuses = {name: 'missing' for name in OVERLAY_TARGETS}
        plan = build_overlay_plan(manifest_with(
            statuses, ['device_node_gaps: /dev/usb/video (absent)']))
        self.assertEqual(plan['readiness'], 'blocked')
        self.assertFalse(plan['executable'])
        self.assertTrue(plan['blocking_reasons'])
        self.assertEqual(len(plan['operations']), len(OVERLAY_TARGETS))

    def test_ready_when_components_present_and_nodes_ok(self):
        statuses = {}
        for name in OVERLAY_TARGETS:
            statuses[name] = 'verified'
        plan = build_overlay_plan(manifest_with(statuses, []))
        self.assertEqual(plan['readiness'], 'ready')
        self.assertFalse(plan['executable'])
        self.assertEqual(plan['blocking_reasons'], [])

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

    def test_plan_never_claims_execution(self):
        plan = build_overlay_plan(manifest_with(
            {name: 'verified' for name in OVERLAY_TARGETS}))
        self.assertFalse(plan['executable'])
        self.assertTrue(plan['prerequisites'])
        self.assertEqual(plan['open_items'], list(OVERLAY_OPEN_ITEMS))
