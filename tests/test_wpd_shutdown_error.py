"""Fixtures for the WPD shutdown/reconnect detection."""
import unittest

from tools.research.ptp_liveview_client import is_wpd_shutdown_error


class ShutdownErrorTests(unittest.TestCase):
    def test_matches_com_error(self):
        exc = RuntimeError("COMError(-2144731134, 'Shutdown was already called on this object or the object that owns it.', ...)")
        self.assertTrue(is_wpd_shutdown_error(exc))

    def test_matches_object_owner_phrase(self):
        self.assertTrue(is_wpd_shutdown_error(Exception('shutdown was already called')))

    def test_other_errors_false(self):
        self.assertFalse(is_wpd_shutdown_error(Exception('Entity not found')))
        self.assertFalse(is_wpd_shutdown_error(Exception('')))


class ReconnectRetryTests(unittest.TestCase):
    def test_no_driver_retries_connect_without_attribute_error(self):
        from tools.research.ptp_liveview_client import SonyWpdPTPLiveView
        client = SonyWpdPTPLiveView.__new__(SonyWpdPTPLiveView)
        client.drv = None

        def fail_connect(index):
            raise RuntimeError('no Sony camera found')

        client.connect = fail_connect
        self.assertIsNone(client.get_frame(retries=2))
        self.assertIn('reconnect_error', client.last_response)


if __name__ == '__main__':
    unittest.main()
