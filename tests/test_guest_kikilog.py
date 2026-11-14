import unittest

from src.a6400.execution.guest_kikilog import GuestKikilog, UnsupportedKikilog


class KikilogTests(unittest.TestCase):
    def test_open_close_identity_and_no_owner_reuse(self):
        device = GuestKikilog('constructed-fixture')
        first = device.open(2, 1000, 1000)
        device.close(first)
        second = device.open(2, 1001, 1000)
        self.assertNotEqual(first, second)
        with self.assertRaisesRegex(UnsupportedKikilog, 'invalid_owner'):
            device.ioctl(first, 0x80044a21, 0)

    def test_open_only_does_not_acknowledge_resume(self):
        device = GuestKikilog('constructed-fixture')
        owner = device.open(2, 1000, 1000)
        with self.assertRaisesRegex(UnsupportedKikilog, 'state_not_supplied'):
            device.ioctl(owner, 0x80044a21, 0)
        self.assertFalse(hasattr(device, 'mutexes_initialized'))

    def test_observed_running_resume_keeps_notifications_unknown(self):
        device = GuestKikilog('constructed-fixture', policy='observed-running-e0301')
        owner = device.open(2, 1000, 1000)
        self.assertEqual(device.ioctl(owner, 0x80044a21, 0), 0)
        self.assertEqual(device.get_flag, 0)
        self.assertEqual(device.timer_list, [])
        self.assertEqual(device.status_list, [])
        before = list(device.transactions)
        with self.assertRaisesRegex(UnsupportedKikilog, 'state_not_supplied'):
            device.ioctl(owner, 0x80044a11, 0x1234)
        self.assertEqual(device.transactions, before)
