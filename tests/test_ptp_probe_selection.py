"""Fixtures for the WPD device selection policy."""
import unittest

from tools.research.run_ptp_liveview_probe import select_device_index


class SelectTests(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(select_device_index(3, 0), 0)
        self.assertEqual(select_device_index(3, 2), 2)

    def test_invalid(self):
        for count, index in ((0, 0), (3, -1), (3, 3), (1, 1)):
            with self.assertRaises(ValueError):
                select_device_index(count, index)


if __name__ == '__main__':
    unittest.main()
