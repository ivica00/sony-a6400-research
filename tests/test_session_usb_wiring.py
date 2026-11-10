"""Session wiring for opt-in otgcore gadget-function policies (E0304)."""
import unittest
from types import SimpleNamespace

from src.a6400.execution.guest_usb_otgcore import GuestUsbOtgCore
from tools.research.emulator_session import usb_otgcore_options
from tools.research.experiment_ui_boot import build_parser


class UsbOtgcoreWiringTests(unittest.TestCase):
    def test_defaults_keep_the_legacy_policy(self):
        options = usb_otgcore_options(SimpleNamespace())
        self.assertEqual(options['reply_policy'], 'legacy-zero-stubs')
        self.assertEqual(options['function_policy'], 'legacy')
        self.assertIsNone(options['configured_functions'])
        device = GuestUsbOtgCore(**options)
        self.assertEqual(device.function_policy, 'legacy')
        self.assertEqual(device.configured_functions, ('mass-storage',))

    def test_descriptor_table_and_functions_are_forwarded(self):
        args = SimpleNamespace(usb_reply_policy='verified-connect',
                               usb_function_policy='descriptor-table',
                               usb_configured_functions=('mass-storage', 'ptp'))
        options = usb_otgcore_options(args)
        self.assertEqual(options['reply_policy'], 'verified-connect')
        self.assertEqual(options['function_policy'], 'descriptor-table')
        self.assertEqual(options['configured_functions'], ('mass-storage', 'ptp'))
        device = GuestUsbOtgCore(**options)
        self.assertEqual(device.function_policy, 'descriptor-table')
        self.assertEqual(device.configured_functions, ('mass-storage', 'ptp'))

    def test_parser_exposes_opt_in_defaults_and_values(self):
        parser = build_parser()
        defaults = parser.parse_args([])
        self.assertEqual(defaults.usb_function_policy, 'legacy')
        self.assertEqual(defaults.usb_configured_functions, ('mass-storage',))
        explicit = parser.parse_args(['--usb-function-policy', 'descriptor-table',
                                      '--usb-configured-functions', 'mass-storage,ptp,uvc-control'])
        self.assertEqual(explicit.usb_function_policy, 'descriptor-table')
        self.assertEqual(explicit.usb_configured_functions,
                         ('mass-storage', 'ptp', 'uvc-control'))
        # The legacy default must be what the session forwards to the device.
        options = usb_otgcore_options(SimpleNamespace(
            usb_reply_policy=defaults.usb_reply_policy,
            usb_function_policy=defaults.usb_function_policy,
            usb_configured_functions=defaults.usb_configured_functions))
        self.assertEqual(options['function_policy'], 'legacy')


if __name__ == '__main__':
    unittest.main()
