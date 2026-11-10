"""Fixtures for the minimal WPD presence probe."""
import unittest

from tools.research.wpd_presence_probe import summarize_devices, typeof_string


class DeviceSummaryTests(unittest.TestCase):
    def test_handles(self):
        class D:
            def __init__(self, handle):
                self.handle = handle
        self.assertEqual(summarize_devices([D('a'), D('b')]), ['a', 'b'])
        self.assertEqual(summarize_devices([]), [])

    def test_open_state(self):
        self.assertIsNone(typeof_string(None))
        self.assertEqual(typeof_string('err'), 'err')
        self.assertEqual(typeof_string(object()), 'opened+closed')


if __name__ == '__main__':
    unittest.main()
