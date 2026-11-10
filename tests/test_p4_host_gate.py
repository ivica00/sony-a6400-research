"""Fixtures for the pre-teardown host enumeration gate."""
import unittest

from tools.research.p4_policy import pre_teardown_host_gate


class HostGateTests(unittest.TestCase):
    def test_ready(self):
        binding = {'composite_parent_ready': True, 'ptp_ready': True,
                   'ptp_children': [{'InstanceId': 'USB\\VID_054C&PID_0CAA\\X'}]}
        self.assertTrue(pre_teardown_host_gate(binding)['ok'])

    def test_missing_child(self):
        binding = {'composite_parent_ready': True, 'ptp_ready': False, 'ptp_children': []}
        result = pre_teardown_host_gate(binding)
        self.assertFalse(result['ok'])
        self.assertIn('ptp_not_ready', result['reasons'])
        self.assertIn('no_ptp_child', result['reasons'])

    def test_missing_parent(self):
        binding = {'composite_parent_ready': False, 'ptp_ready': True, 'ptp_children': [{}]}
        result = pre_teardown_host_gate(binding)
        self.assertFalse(result['ok'])
        self.assertIn('composite_parent_not_ready', result['reasons'])

    def test_no_sample(self):
        self.assertEqual(pre_teardown_host_gate(None)['reasons'], ['no_host_binding_sample'])


if __name__ == '__main__':
    unittest.main()
