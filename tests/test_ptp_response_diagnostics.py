"""Fixtures for the PTP GetObject response diagnostics."""
import unittest

from tools.research.ptp_liveview_client import PTP_RC_OK, SonyWpdPTPLiveView


class FakeDriver:
    def __init__(self, responses):
        self.responses = list(responses)

    def sendReadCommand(self, code, args):
        if not self.responses:
            raise RuntimeError('no response')
        return self.responses.pop(0)


def client_with(driver):
    client = SonyWpdPTPLiveView.__new__(SonyWpdPTPLiveView)
    client.drv = driver
    return client


class DiagnosticsTests(unittest.TestCase):
    def test_empty_response_records_rc_and_len(self):
        client = client_with(FakeDriver([(0x2001, b'')] * 4))
        self.assertIsNone(client.get_frame(retries=3))
        self.assertEqual(client.last_response, {'rc': 0x2001, 'len': 0})

    def test_ok_short_data_not_a_frame(self):
        client = client_with(FakeDriver([(PTP_RC_OK, b'\x00' * 64)] * 4))
        self.assertIsNone(client.get_frame(retries=2))
        self.assertEqual(client.last_response, {'rc': PTP_RC_OK, 'len': 64})

    def test_exception_recorded(self):
        client = client_with(FakeDriver([]))
        self.assertIsNone(client.get_frame(retries=2))
        self.assertIn('error', client.last_response)


if __name__ == '__main__':
    unittest.main()
