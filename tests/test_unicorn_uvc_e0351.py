"""E0351 offline checks: EP0 UVC class decode and START endpoint selection.

Pure offline (Unicorn/capstone over the shipped objects). No camera, USB or
module access. Deterministic; runs in well under a second.
"""
import unittest
from pathlib import Path

from tools.research import unicorn_uvc_ep0_select as e0351

FIXTURES = (e0351.SELECTOR_ELF, e0351.BRIDGE_ELF, e0351.REFLASS_ELF)


class ClassHandlerDecodeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.static = e0351.decode_class_handler()

    def test_class_handler_identical_in_shipped_build(self):
        self.assertTrue(self.static['class_handler_identical_in_shipped_build'])
        self.assertEqual(self.static['reference_sha256'], e0351.REF_SHA)

    def test_probe_template_is_26_bytes(self):
        tpl = self.static['uvc_streaming_control_template']
        self.assertEqual(len(bytes.fromhex(tpl['bytes_hex'])), 26)
        self.assertEqual(tpl['parsed']['bFormatIndex'], 1)
        self.assertEqual(tpl['parsed']['bFrameIndex'], 1)
        self.assertEqual(tpl['parsed']['dwFrameInterval'], 333333)
        self.assertEqual(tpl['parsed']['dwMaxPayloadTransferSize'], 300000)
        self.assertFalse(tpl['parsed']['dwClockFrequency_present'])

    def test_relocations_name_the_helper_calls(self):
        rel = self.static['relocations_in_range']
        self.assertEqual(rel['0x188c']['symbol'], 'usbg_video_get_ep0_buffer')
        self.assertEqual(rel['0x19e8']['symbol'], 'usbg_video_call_user_cb')
        self.assertEqual(rel['0x11e4']['symbol'], 'memcpy')

    def test_decision_table_covers_probe_and_commit(self):
        rows = {row['id']: row for row in self.static['decision_table']}
        self.assertEqual(rows['T4']['return'].split()[0], '0')
        self.assertIn('0x0200', rows['T5']['request'])
        self.assertIn('0x0100/0x0200', rows['T6b']['request'])
        self.assertEqual(rows['T1']['return'].split()[0], '2')


class SelectorUnicornTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = {c['case']: c for c in e0351.run_selector_cases()}

    def test_all_selector_cases_pass(self):
        failed = [n for n, c in self.cases.items() if not c['pass']]
        self.assertEqual(failed, [])

    def test_expected_live_layout_returns_wrapper(self):
        row = self.cases['expected-live-0x84-one-wrapper']
        self.assertEqual(row['result'], e0351.WRAP0)
        self.assertEqual(row['reads'][0]['addr'], hex(e0351.DWC + 0xF4))

    def test_session_gate_requires_high_speed(self):
        self.assertEqual(self.cases['expected-live-session-gate-speed3']['result'],
                         e0351.WRAP0)
        self.assertEqual(self.cases['session-gate-speed-not-3']['result'], 0)

    def test_disabled_endpoint_flag_returns_zero(self):
        row = self.cases['dep-disabled-flag-rejected']
        self.assertEqual(row['result'], 0)
        self.assertEqual(row['reads'][1]['addr'], hex(e0351.DEP + 0x4C))
        self.assertEqual(row['reads'][1]['value'], '0x0')

    def test_wrong_endpoint_address_returns_zero(self):
        self.assertEqual(self.cases['endpoint-0x81-rejected']['result'], 0)


class BridgeAndReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bridge = {c['case']: c for c in e0351.run_bridge_cases()}
        cls.ref = {c['case']: c for c in e0351.run_reference_class_cases()}

    def test_bridge_cases_pass(self):
        self.assertEqual([n for n, c in self.bridge.items() if not c['pass']], [])

    def test_vs_probe_and_commit_are_forwarded(self):
        self.assertTrue(self.bridge['vs-set-cur-probe-iface2']['forwarded'])
        self.assertTrue(self.bridge['vs-set-cur-commit-iface2']['forwarded'])

    def test_mismatched_interface_is_not_handled(self):
        row = self.bridge['mismatched-interface-iface2-on-shadow0']
        self.assertFalse(row['forwarded'])
        self.assertEqual(row['steps']['result'], 2)

    def test_reference_class_cases_pass(self):
        self.assertEqual([n for n, c in self.ref.items() if not c['pass']], [])

    def test_get_cur_probe_reply_is_template_plus_stack_tail(self):
        row = self.ref['get-cur-probe-34']
        self.assertEqual(row['result'], 0)
        reply = bytes.fromhex(row['ep0_reply_hex'])
        self.assertEqual(len(reply), 34)
        self.assertEqual(reply[:26], bytes.fromhex(
            e0351.decode_class_handler()['uvc_streaming_control_template']['bytes_hex']))
        self.assertEqual(reply[26:], b'\xa5' * 8)

    def test_standard_set_interface_is_not_handled(self):
        self.assertEqual(self.ref['set-interface-standard']['result'], 2)

    def test_get_len_is_stalled(self):
        self.assertEqual(self.ref['get-len']['result'], 1)


@unittest.skipUnless(all(p.exists() for p in FIXTURES), 'E0351 Unicorn fixtures absent')
class FixtureIdentityTests(unittest.TestCase):
    def test_fixtures_are_linked_elf_with_symbols(self):
        for path in FIXTURES:
            elf = e0351.Elf32(path)
            self.assertTrue(elf.segments, path.name)
            self.assertTrue(elf.symbols(), path.name)

    def test_selector_exports_the_live_start_selector(self):
        symbols = e0351.Elf32(e0351.SELECTOR_ELF).symbols()
        self.assertIn('a6400_uvc_ptp_select_endpoint', symbols)
        self.assertIn('shared_endpoint', symbols)


if __name__ == '__main__':
    unittest.main()
