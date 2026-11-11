"""Focused checks for the transport-aware UVC module audit mode (defect B5).

The audit tool must never treat an enumeration-only manifest as a transport
build (or the reverse), must never guess an ambiguous manifest, and must keep
the explicit --allow-transport confirmation honest. These tests only exercise
the pure mode resolver; no module is built, linked or executed here.
"""
import unittest

from tools.research.audit_uvc_ptp_module import resolve_audit_mode


class ResolveAuditModeTests(unittest.TestCase):
    def test_enumeration_manifest(self):
        manifest = {'shared_ptp_enumeration_candidate': True, 'start_probe_only': True}
        self.assertEqual(resolve_audit_mode(manifest), 'enumeration')

    def test_builder_transport_manifest_without_explicit_flag(self):
        # The current builder writes start_probe_only=False and no
        # composite_transport key for --composite-transport builds.
        manifest = {'shared_ptp_enumeration_candidate': True, 'start_probe_only': False}
        self.assertEqual(resolve_audit_mode(manifest), 'transport')

    def test_declared_transport_manifest(self):
        manifest = {'shared_ptp_enumeration_candidate': True,
                    'start_probe_only': False, 'composite_transport': True}
        self.assertEqual(resolve_audit_mode(manifest), 'transport')

    def test_declared_transport_without_probe_key(self):
        manifest = {'shared_ptp_enumeration_candidate': True, 'composite_transport': True}
        self.assertEqual(resolve_audit_mode(manifest), 'transport')

    def test_allow_transport_confirms_transport_build(self):
        manifest = {'shared_ptp_enumeration_candidate': True, 'start_probe_only': False}
        self.assertEqual(resolve_audit_mode(manifest, allow_transport=True), 'transport')

    def test_allow_transport_rejects_enumeration_build(self):
        manifest = {'shared_ptp_enumeration_candidate': True, 'start_probe_only': True}
        with self.assertRaises(ValueError):
            resolve_audit_mode(manifest, allow_transport=True)

    def test_non_shared_candidate_rejected(self):
        manifest = {'shared_ptp_enumeration_candidate': False, 'start_probe_only': False}
        with self.assertRaises(ValueError):
            resolve_audit_mode(manifest)

    def test_missing_mode_keys_rejected(self):
        manifest = {'shared_ptp_enumeration_candidate': True}
        with self.assertRaises(ValueError):
            resolve_audit_mode(manifest)

    def test_conflicting_mode_declarations_rejected(self):
        manifest = {'shared_ptp_enumeration_candidate': True,
                    'start_probe_only': True, 'composite_transport': True}
        with self.assertRaises(ValueError):
            resolve_audit_mode(manifest)


if __name__ == '__main__':
    unittest.main()
