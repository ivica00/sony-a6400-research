"""Tests for the read-only UVC/DMA probe's report contract.

The report is generated at test time by `probes/build_probe.py --host-check`
(synthetic /proc-/sys-/dev-like tree in WSL; no camera, no hardware). When WSL is
unreachable from the test interpreter — this sandbox runs workspace binaries at
low integrity, and WSL refuses to start from a low-integrity process — the test
reuses the report the last host check generated, and skips only when neither is
available.
"""
import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / 'probes' / 'test_probe_report.py'
BUILDER = ROOT / 'probes' / 'build_probe.py'
LAST_REPORT = ROOT / 'probes' / 'build' / 'host-check' / 'report.json'

_spec = importlib.util.spec_from_file_location('probe_report_validator', VALIDATOR)
validator = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(validator)

_ORIGIN = None
_REPORT = None


def _generate():
    """Return (report, origin) from a fresh host check or the last one it produced."""
    global _ORIGIN, _REPORT
    if _REPORT is not None:
        return _REPORT, _ORIGIN
    reason = 'no report'
    with tempfile.TemporaryDirectory(prefix='probe-report-') as tmp:
        try:
            proc = subprocess.run(
                [sys.executable, str(BUILDER), '--host-check', '--output-dir', tmp],
                cwd=str(ROOT), capture_output=True, text=True, timeout=900)
            if proc.returncode == 0:
                produced = Path(tmp) / 'host-check' / 'report.json'
                if produced.is_file():
                    _REPORT = json.loads(produced.read_text(encoding='utf-8'))
                    _ORIGIN = 'host-check generated at test time'
                    return _REPORT, _ORIGIN
                reason = 'host check produced no report'
            else:
                tail = (proc.stderr or proc.stdout or '').strip().splitlines()
                reason = tail[-1] if tail else f'host check exit {proc.returncode}'
        except (OSError, subprocess.TimeoutExpired) as exc:
            reason = f'{type(exc).__name__}: {exc}'
    if LAST_REPORT.is_file():
        _REPORT = json.loads(LAST_REPORT.read_text(encoding='utf-8'))
        _ORIGIN = f'reused the last generated host-check report ({reason})'
        return _REPORT, _ORIGIN
    raise unittest.SkipTest(f'no host-check report available: {reason}')


def setUpModule():
    report, origin = _generate()
    validator.validate_report(report)
    if origin.startswith('reused'):
        sys.stderr.write(f'\n[test_probes_report] note: {origin}\n')


def _report_copy():
    return copy.deepcopy(_generate()[0])


class ReportContractTests(unittest.TestCase):
    def test_report_satisfies_the_contract(self):
        report = _generate()[0]
        self.assertTrue(validator.validate_report(report))
        self.assertEqual(report['schema'], 'a6400-uvc-dma-probe/1')
        self.assertIn(report['exit_code'], (0, 2))

    def test_fixture_run_collected_the_expected_sections(self):
        report = _generate()[0]
        self.assertTrue(report['identity']['uptime'])
        self.assertTrue(report['identity']['version'])
        self.assertTrue(report['modules'])
        self.assertEqual([u['name'] for u in report['udc']], ['dwc3.0'])
        self.assertTrue(report['pid149']['mappings'])
        self.assertEqual(report['pid149']['thread_count'], 3)
        found = [k for k, v in report['kallsyms']['symbols'].items() if v]
        self.assertIn('usb_gadgetcore_register_driver', found)
        counts = {c['qid']: c for c in report['uipc']['counts']}
        self.assertEqual(counts['0x0167046a']['raw_le_bytes'], 1)
        self.assertEqual(counts['0x0167046a']['ascii_8hex_lower'], 1)
        self.assertIsNone(report['get_jpeg_polls'])
        self.assertEqual(report['exit_code'], 0)

    def test_report_declares_bounded_read_only_behaviour(self):
        bounds = _generate()[0]['bounds']
        self.assertLessEqual(bounds['get_jpeg_polls_cap'], 100)
        self.assertLessEqual(bounds['devmem_len_cap'], 4096)
        self.assertLessEqual(bounds['uipc_bytes_read'], 131072)
        self.assertLessEqual(bounds['maps_bytes_read'], 65536)
        self.assertFalse(bounds['bulk_devmem_scan'])
        self.assertFalse(bounds['device_node_opened_for_io'])


class RejectedClaimTests(unittest.TestCase):
    def assertRejected(self, report):
        with self.assertRaises(validator.ReportError):
            validator.validate_report(report)

    def test_missing_top_level_section(self):
        report = _report_copy()
        del report['kallsyms']
        self.assertRejected(report)

    def test_unexpected_top_level_section(self):
        report = _report_copy()
        report['extra_claims'] = {}
        self.assertRejected(report)

    def test_kallsyms_entry_without_address(self):
        report = _report_copy()
        report['kallsyms']['symbols']['osal_snd_msg'] = {'type': 'T'}
        self.assertRejected(report)

    def test_zero_kallsyms_address_needs_restricted_flag(self):
        report = _report_copy()
        report['kallsyms']['symbols']['osal_snd_msg'] = {'address': '0x00000000', 'type': 'T'}
        self.assertRejected(report)
        report['kallsyms']['symbols']['osal_snd_msg']['restricted'] = True
        validator.validate_report(report)

    def test_device_node_without_major_minor_or_errno(self):
        report = _report_copy()
        entry = next(e for e in report['devnodes']['stat'] if e['present'])
        entry.pop('major')
        entry.pop('minor')
        self.assertRejected(report)

    def test_absent_device_node_needs_an_errno(self):
        report = _report_copy()
        entry = next(e for e in report['devnodes']['stat'] if not e['present'])
        entry['errno'] = None
        self.assertRejected(report)

    def test_more_than_one_hundred_polls(self):
        report = _report_copy()
        report['get_jpeg_polls'] = [
            {'index': i, 'err': 0, 'ready': 0, 'size_shift': None, 'handle1': None,
             'handle2': None, 'recv_ret': 0, 'dmm_cleanup': None}
            for i in range(101)
        ]
        self.assertRejected(report)

    def test_poll_with_frame_but_no_handles(self):
        report = _report_copy()
        report['get_jpeg_polls'] = [
            {'index': 0, 'err': 0, 'ready': 1, 'size_shift': None, 'handle1': None,
             'handle2': None, 'recv_ret': 0, 'dmm_cleanup': None},
        ]
        self.assertRejected(report)

    def test_devmem_read_above_4096_bytes(self):
        report = _report_copy()
        report['devmem'] = {'pa': '0x00001000', 'len': 8192, 'bytes_read': 8192,
                            'nonzero_bytes': 0, 'head_hex': '', 'errno': None}
        self.assertRejected(report)

    def test_declared_poll_cap_above_the_hard_limit(self):
        report = _report_copy()
        report['bounds']['get_jpeg_polls_cap'] = 101
        self.assertRejected(report)

    def test_device_node_opened_without_an_opt_in_section(self):
        report = _report_copy()
        report['bounds']['device_node_opened_for_io'] = True
        self.assertRejected(report)
        report['get_jpeg_polls'] = []
        validator.validate_report(report)

    def test_bulk_devmem_scan_can_never_be_claimed(self):
        report = _report_copy()
        report['bounds']['bulk_devmem_scan'] = True
        self.assertRejected(report)


if __name__ == '__main__':
    unittest.main()
