"""Fixtures for the probe close() lifecycle."""
import unittest

from tools.research.ptp_liveview_client import SonyWpdPTPLiveView


class FakeDevice:
    def __init__(self):
        self.closed = 0

    def Close(self):
        self.closed += 1


class FakeDriver:
    def __init__(self):
        self.device = FakeDevice()


class BrokenDevice:
    def Close(self):
        raise RuntimeError('already gone')


class BrokenDriver:
    def __init__(self):
        self.device = BrokenDevice()


def make_client(driver):
    client = SonyWpdPTPLiveView.__new__(SonyWpdPTPLiveView)
    client.drv = driver
    return client


class CloseTests(unittest.TestCase):
    def test_closes_device_once(self):
        driver = FakeDriver()
        client = make_client(driver)
        client.close()
        self.assertEqual(driver.device.closed, 1)
        self.assertIsNone(client.drv)
        client.close()
        self.assertEqual(driver.device.closed, 1)

    def test_no_driver_is_safe(self):
        client = make_client(None)
        client.close()

    def test_close_error_is_swallowed(self):
        client = make_client(BrokenDriver())
        client.close()
        self.assertIsNone(client.drv)


if __name__ == '__main__':
    unittest.main()
