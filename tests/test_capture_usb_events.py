"""Fixtures for the read-only USB transition capture."""
import unittest

from tools.research.capture_usb_events import detect_transitions, summarize


class SummaryTests(unittest.TestCase):
    def test_counts_and_flags(self):
        binding = {'parents': [{}], 'ptp_children': [{}], 'uvc_children': [],
                   'composite_parent_ready': True, 'ptp_ready': True, 'uvc_ready': False}
        summary = summarize(binding)
        self.assertEqual(summary['parents'], 1)
        self.assertEqual(summary['ptp_children'], 1)
        self.assertTrue(summary['composite_parent_ready'])
        self.assertFalse(summary['uvc_ready'])


class TransitionTests(unittest.TestCase):
    def test_transitions_only_on_change(self):
        a = {'parents': 1, 'ptp_children': 1, 'uvc_children': 1,
             'composite_parent_ready': True, 'ptp_ready': True, 'uvc_ready': True}
        b = {'parents': 1, 'ptp_children': 0, 'uvc_children': 0,
             'composite_parent_ready': False, 'ptp_ready': False, 'uvc_ready': False}
        samples = [{'utc': 't0', 'summary': a}, {'utc': 't1', 'summary': a},
                   {'utc': 't2', 'summary': b}]
        transitions = detect_transitions(samples)
        self.assertEqual([t['index'] for t in transitions], [0, 2])
        self.assertEqual(transitions[1]['summary']['ptp_children'], 0)

    def test_empty(self):
        self.assertEqual(detect_transitions([]), [])


if __name__ == '__main__':
    unittest.main()
