"""Focused fixtures for the pure P4 preflight/receipt/recovery policy."""
import unittest

from tools.research.p4_policy import (evaluate_after, evaluate_preflight,
                                      evaluate_receipt, module_loaded, parse_uptime)

MODULES = b'foo 45 0 - Live 0x0\nbar 12 0 - Live 0x0\n'
LOADED = MODULES + b'usbg_video 123 0 - Live 0x0\n'
STATUS = b'Name:\tinit\nState:\tS (sleeping)\nTracerPid:\t0\n'
SHA = 'a' * 64
AUDIT = {'status': 'offline_module_audit_passed', 'module_sha256': SHA}


def receipt(*, init=True, stop=True, retire=True, complete=True, order=None, extra=b''):
    parts = []
    if init:
        parts.append('IOCTL_UVC_INIT returned ret=0 errno=0 (Success)')
    if stop:
        parts.append('STEP 3: Composite session stopped; IDLE/unpinned/no hooks/no error verified.')
    if retire:
        parts.append('STEP 4: Entry hook retired, 0xe1a0c00d restored, 4-core sync complete, threads resumed.')
    if complete:
        parts.append('SESSION_RUNNER complete result=0')
    if order == 'stop-before-init':
        parts = [p for p in parts if not p.startswith('IOCTL')] + [p for p in parts if p.startswith('IOCTL')]
    return ('\n'.join(parts) + '\n').encode() + extra


class ReceiptTests(unittest.TestCase):
    def test_success(self):
        result = evaluate_receipt(receipt())
        self.assertTrue(result['ok'], result['reasons'])
        self.assertTrue(all(result['markers'].values()))

    def test_missing_markers(self):
        for flag, reason in [('init', 'missing_init'), ('stop', 'missing_stop_verified'),
                             ('retire', 'missing_retired'), ('complete', 'missing_completed')]:
            result = evaluate_receipt(receipt(**{flag: False}))
            self.assertFalse(result['ok'])
            self.assertIn(reason, result['reasons'])

    def test_forbidden_markers(self):
        for extra, reason in [(b'SESSION_RUNNER RETAINED fd=3 phase=0\n', 'forbidden_retained'),
                              (b'CRITICAL freeze_resume failed\n', 'forbidden_critical'),
                              (b'FAIL IOCTL_UVC_INIT: ret=-1\n', 'forbidden_fail')]:
            result = evaluate_receipt(receipt(extra=extra))
            self.assertFalse(result['ok'])
            self.assertIn(reason, result['reasons'])

    def test_out_of_order(self):
        result = evaluate_receipt(receipt(order='stop-before-init'))
        self.assertFalse(result['ok'])
        self.assertIn('markers_out_of_order', result['reasons'])

    def test_missing_or_empty(self):
        self.assertEqual(evaluate_receipt(None)['reasons'], ['receipt_missing'])
        self.assertEqual(evaluate_receipt(b'')['reasons'], ['receipt_missing'])


class PreflightTests(unittest.TestCase):
    def test_clean(self):
        result = evaluate_preflight(module_sha=SHA, runner_sha='b' * 64, audit=AUDIT,
                                    modules=MODULES, status149=STATUS)
        self.assertTrue(result['ok'], result['reasons'])

    def test_audit_failures(self):
        bad = dict(AUDIT, status='failed')
        self.assertIn('audit_not_passed', evaluate_preflight(module_sha=SHA, runner_sha='x', audit=bad,
                                                             modules=MODULES, status149=STATUS)['reasons'])
        bad = dict(AUDIT, module_sha256='c' * 64)
        self.assertIn('audit_module_mismatch', evaluate_preflight(module_sha=SHA, runner_sha='x', audit=bad,
                                                                  modules=MODULES, status149=STATUS)['reasons'])
        self.assertIn('missing_identity', evaluate_preflight(module_sha='', runner_sha='x', audit=AUDIT,
                                                             modules=MODULES, status149=STATUS)['reasons'])

    def test_loaded_and_traced(self):
        loaded = LOADED
        self.assertIn('module_already_loaded', evaluate_preflight(module_sha=SHA, runner_sha='x', audit=AUDIT,
                                                                  modules=loaded, status149=STATUS)['reasons'])
        traced = STATUS.replace(b'TracerPid:\t0', b'TracerPid:\t149')
        self.assertIn('tracer_not_clean', evaluate_preflight(module_sha=SHA, runner_sha='x', audit=AUDIT,
                                                             modules=MODULES, status149=traced)['reasons'])


class AfterTests(unittest.TestCase):
    def test_clean(self):
        result = evaluate_after(modules_before=MODULES, modules_after=MODULES,
                                uptime_before=b'100.0 200.0\n', uptime_after=b'260.0 300.0\n',
                                receipt_ok=True)
        self.assertTrue(result['ok'], result['reasons'])
        self.assertFalse(result['reboot'])
        self.assertTrue(result['module_restored'])

    def test_module_not_restored(self):
        result = evaluate_after(modules_before=MODULES, modules_after=LOADED,
                                uptime_before=b'100.0 200.0\n', uptime_after=b'260.0 300.0\n',
                                receipt_ok=True)
        self.assertFalse(result['ok'])
        self.assertIn('modules_not_restored', result['reasons'])
        self.assertIn('usbg_video_loaded', result['reasons'])

    def test_reboot_and_receipt(self):
        result = evaluate_after(modules_before=MODULES, modules_after=MODULES,
                                uptime_before=b'100.0 200.0\n', uptime_after=b'5.0 9.0\n',
                                receipt_ok=False)
        self.assertIn('reboot_detected', result['reasons'])
        self.assertIn('receipt_not_verified', result['reasons'])

    def test_uptime_helpers(self):
        self.assertEqual(parse_uptime(b'5039.72 18174.67\n'), 5039.72)
        self.assertTrue(module_loaded(LOADED))
        self.assertFalse(module_loaded(b'foo 1 0 - Live 0x0\n'))


if __name__ == '__main__':
    unittest.main()
