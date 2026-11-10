import struct
import unittest
from src.a6400.execution.guest_usb_otgcore import (
    GuestUsbOtgCore,
    UnsupportedUsbOtgCore,
    USB_OTGCORE_IOCTL_SET_PORT_DESC,
    USB_OTGCORE_IOCTL_START,
    USB_OTGCORE_IOCTL_STOP,
    USB_OTGCORE_IOCTL_RESET,
    USB_OTGCORE_IOCTL_SET_CONFIG,
    USB_OTGCORE_IOCTL_GET_STATUS,
    USB_OTGCORE_IOCTL_GET_INFO,
    USB_OTGCORE_IOCTL_SET_MODE,
    USB_OTGCORE_IOCTL_SET_FLAG,
    USB_OTGCORE_IOCTL_SET_SELECT_PORT,
    USB_OTGCORE_IOCTL_SET_PARAM,
    USB_OTGCORE_IOCTL_CMD_0XE305,
    USB_OTGCORE_IOCTL_CMD_0XE312,
    USB_OTGCORE_REPLY_POLICY_LEGACY,
    USB_OTGCORE_REPLY_POLICY_VERIFIED,
    USB_OTGCORE_FUNCTION_POLICY_LEGACY,
    USB_OTGCORE_FUNCTION_POLICY_DESCRIPTOR_TABLE,
    USB_OTGCORE_CONFIG_SIZE,
    USB_OTGCORE_CONFIG_MAX_ENTRIES,
    GADGET_FUNCTION_TABLE,
    gadget_function,
    parse_otgcore_config,
)


class TestGuestUsbOtgCore(unittest.TestCase):
    def setUp(self):
        self.dev = GuestUsbOtgCore(address_limit=0x5f000000)

    def test_device_numbers(self):
        self.assertEqual(self.dev.major, 242)
        self.assertEqual(self.dev.minor, 2)

    def test_open_close(self):
        owner = self.dev.open(flags=2, caller_pid=1012, caller_tgid=1000)
        self.assertEqual(owner['owner_id'], 1)
        self.assertEqual(owner['flags'], 2)
        self.assertEqual(owner['caller_pid'], 1012)
        self.assertEqual(self.dev.close(1), 0)
        self.assertEqual(self.dev.close(1), -9)

    def test_ioctl_set_port_desc(self):
        owner = self.dev.open(flags=2)
        payload = b'\x11' * 36
        mem = {0x1000: payload}

        ret = self.dev.ioctl(
            owner['owner_id'],
            USB_OTGCORE_IOCTL_SET_PORT_DESC,
            0x1000,
            lambda addr, sz: mem[addr][:sz],
            lambda addr, data: None
        )
        self.assertEqual(ret, 0)
        self.assertEqual(self.dev.port_desc, payload)

    def test_ioctl_start_stop_reset(self):
        owner = self.dev.open(flags=2)
        self.assertFalse(self.dev.started)

        ret = self.dev.ioctl(owner['owner_id'], USB_OTGCORE_IOCTL_START, 0, lambda a, s: b'', lambda a, d: None)
        self.assertEqual(ret, 0)
        self.assertTrue(self.dev.started)

        ret = self.dev.ioctl(owner['owner_id'], USB_OTGCORE_IOCTL_STOP, 0, lambda a, s: b'', lambda a, d: None)
        self.assertEqual(ret, 0)
        self.assertFalse(self.dev.started)

        ret = self.dev.ioctl(owner['owner_id'], USB_OTGCORE_IOCTL_RESET, 0, lambda a, s: b'', lambda a, d: None)
        self.assertEqual(ret, 0)
        self.assertFalse(self.dev.started)

    def test_ioctl_set_config(self):
        owner = self.dev.open(flags=2)
        payload = b'\x22' * 64
        mem = {0x2000: payload}

        ret = self.dev.ioctl(
            owner['owner_id'],
            USB_OTGCORE_IOCTL_SET_CONFIG,
            0x2000,
            lambda addr, sz: mem[addr][:sz],
            lambda addr, data: None
        )
        self.assertEqual(ret, 0)
        self.assertEqual(self.dev.config, payload)

    def test_ioctl_get_status_and_info(self):
        owner = self.dev.open(flags=2)
        mem = {}

        def write_mem(addr, data):
            mem[addr] = data

        ret = self.dev.ioctl(
            owner['owner_id'],
            USB_OTGCORE_IOCTL_GET_STATUS,
            0x3000,
            lambda a, s: b'',
            write_mem
        )
        self.assertEqual(ret, 0)
        self.assertEqual(mem[0x3000], b'\x00')

        ret = self.dev.ioctl(
            owner['owner_id'],
            USB_OTGCORE_IOCTL_GET_INFO,
            0x4000,
            lambda a, s: b'',
            write_mem
        )
        self.assertEqual(ret, 0)
        self.assertEqual(mem[0x4000], b'\x00' * 8)

    def test_user_pointer_outside_task_limit(self):
        owner = self.dev.open(flags=2)
        with self.assertRaises(UnsupportedUsbOtgCore) as ctx:
            self.dev.ioctl(
                owner['owner_id'],
                USB_OTGCORE_IOCTL_SET_PORT_DESC,
                0x60000000,  # kernel address
                lambda a, s: b'',
                lambda a, d: None
            )
        self.assertEqual(ctx.exception.details['reason'], 'user_pointer_outside_task_limit')

    def test_invalid_owner_and_unknown_ioctl(self):
        with self.assertRaises(UnsupportedUsbOtgCore):
            self.dev.ioctl(999, USB_OTGCORE_IOCTL_START, 0, lambda a, s: b'', lambda a, d: None)

        owner = self.dev.open(flags=2)
        ret = self.dev.ioctl(owner['owner_id'], 0xdeadbeef, 0, lambda a, s: b'', lambda a, d: None)
        self.assertEqual(ret, -22)


class TestGuestUsbOtgCoreVerifiedPolicy(unittest.TestCase):
    """Opt-in 'verified-connect' policy: authentic values or explicit boundary."""

    def setUp(self):
        self.dev = GuestUsbOtgCore(reply_policy=USB_OTGCORE_REPLY_POLICY_VERIFIED)
        self.owner = self.dev.open(flags=2, caller_pid=1012, caller_tgid=1000)
        self.mem = {}
        self.written = {}

    def mem_read(self, addr, size):
        return self.mem[addr][:size]

    def mem_write(self, addr, data):
        self.written[addr] = bytes(data)

    def ioctl(self, cmd, arg=0, payload=None):
        if payload is not None:
            self.mem[arg] = payload
        return self.dev.ioctl(self.owner['owner_id'], cmd, arg, self.mem_read, self.mem_write)

    # ---------------------------------------------------------- policy shape
    def test_default_policy_is_legacy(self):
        default = GuestUsbOtgCore()
        self.assertEqual(default.reply_policy, USB_OTGCORE_REPLY_POLICY_LEGACY)
        self.assertEqual(default.config_count, 0)
        self.assertEqual(default.selected_port, 0)

    def test_unknown_policy_rejected(self):
        with self.assertRaises(ValueError):
            GuestUsbOtgCore(reply_policy='invented')

    # ------------------------------------------------------ verified setters
    def test_verified_set_config_returns_zero_and_records_count(self):
        payload = bytes([2]) + b'\x00' * 63
        ret = self.ioctl(USB_OTGCORE_IOCTL_SET_CONFIG, 0x2000, payload)
        self.assertEqual(ret, 0)
        self.assertEqual(self.dev.config, payload)
        self.assertEqual(self.dev.config_count, 2)
        self.assertEqual(self.dev.transactions[-1]['entry_count'], 2)

    def test_verified_set_param_returns_zero(self):
        payload = b'\xa5' * 16
        self.assertEqual(self.ioctl(USB_OTGCORE_IOCTL_SET_PARAM, 0x3000, payload), 0)
        self.assertEqual(self.dev.param, payload)

    def test_verified_set_flag_returns_zero(self):
        for flag in (1, 5, 10, 0, 11):
            self.assertEqual(self.ioctl(USB_OTGCORE_IOCTL_SET_FLAG, 0x4000, bytes([flag])), 0)
        self.assertEqual(self.dev.flag, 11)

    def test_verified_set_port_desc_first_and_busy(self):
        payload = struct.pack('<I', 0x0002b5c0) + b'\xdd' * 32
        self.assertEqual(self.ioctl(USB_OTGCORE_IOCTL_SET_PORT_DESC, 0x5000, payload), 0)
        self.assertEqual(self.dev.port_desc, payload)
        # A second registration before RESET reproduces the kernel -EBUSY path.
        self.assertEqual(self.ioctl(USB_OTGCORE_IOCTL_SET_PORT_DESC, 0x5000, payload), -16)

    def test_verified_set_port_desc_zero_word_is_einval(self):
        payload = b'\x00' * 36
        self.assertEqual(self.ioctl(USB_OTGCORE_IOCTL_SET_PORT_DESC, 0x5000, payload), -22)
        self.assertIsNone(self.dev.port_desc)

    def test_verified_select_port_zero(self):
        self.assertEqual(self.ioctl(USB_OTGCORE_IOCTL_SET_SELECT_PORT, 0x6000,
                                    struct.pack('<I', 0)), 0)
        self.assertEqual(self.dev.selected_port, 0)

    def test_verified_select_port_nonzero_is_boundary(self):
        with self.assertRaises(UnsupportedUsbOtgCore) as ctx:
            self.ioctl(USB_OTGCORE_IOCTL_SET_SELECT_PORT, 0x6000, struct.pack('<I', 1))
        self.assertEqual(ctx.exception.details['reason'],
                         'usb_otgcore_select_port_reply_not_derivable')
        self.assertEqual(ctx.exception.details['request_field'], 'port=1')
        self.assertEqual(self.dev.selected_port, 0)

    # ------------------------------------------------------ verified queries
    def test_verified_get_info_before_app_config_is_zero_struct(self):
        self.assertEqual(self.ioctl(USB_OTGCORE_IOCTL_GET_INFO, 0x7000), 0)
        self.assertEqual(self.written[0x7000], b'\x00' * 8)

    def test_verified_get_info_derived_from_set_config(self):
        self.ioctl(USB_OTGCORE_IOCTL_SET_CONFIG, 0x2000, bytes([1]) + b'\x00' * 63)
        self.assertEqual(self.ioctl(USB_OTGCORE_IOCTL_GET_INFO, 0x7000), 0)
        self.assertEqual(self.written[0x7000], struct.pack('<II', 1, 0))
        self.assertEqual(self.dev.transactions[-1]['source'], 'derived-application-state')

    def test_verified_get_info_reproduces_efault_for_count_above_two(self):
        self.ioctl(USB_OTGCORE_IOCTL_SET_CONFIG, 0x2000, bytes([3]) + b'\x00' * 63)
        self.assertEqual(self.ioctl(USB_OTGCORE_IOCTL_GET_INFO, 0x7000), -14)
        self.assertNotIn(0x7000, self.written)

    def test_verified_get_status_is_explicit_boundary(self):
        with self.assertRaises(UnsupportedUsbOtgCore) as ctx:
            self.ioctl(USB_OTGCORE_IOCTL_GET_STATUS, 0x7000)
        details = ctx.exception.details
        self.assertEqual(details['reason'], 'usb_otgcore_get_status_reply_not_derivable')
        self.assertEqual(details['cmd'], USB_OTGCORE_IOCTL_GET_STATUS)
        self.assertEqual(details['requested_size'], 1)
        self.assertNotIn(0x7000, self.written)

    def test_verified_set_mode_invalid_value_is_einval(self):
        self.assertEqual(self.ioctl(USB_OTGCORE_IOCTL_SET_MODE, 0x8000, b'\x03'), -22)

    def test_verified_set_mode_valid_value_is_explicit_boundary(self):
        with self.assertRaises(UnsupportedUsbOtgCore) as ctx:
            self.ioctl(USB_OTGCORE_IOCTL_SET_MODE, 0x8000, b'\x02')
        details = ctx.exception.details
        self.assertEqual(details['reason'], 'usb_otgcore_set_mode_reply_not_derivable')
        self.assertEqual(details['request_field'], 'mode=2')

    def test_verified_callback_commands_are_boundaries(self):
        for cmd in (USB_OTGCORE_IOCTL_CMD_0XE305, 0xe30e, 0xe308, 0xe309, 0xe30a, 0xe306):
            with self.assertRaises(UnsupportedUsbOtgCore) as ctx:
                self.ioctl(cmd)
            self.assertEqual(ctx.exception.details['reason'],
                             'usb_otgcore_driver_callback_reply_not_derivable', hex(cmd))

    def test_verified_unknown_command_is_enotty(self):
        self.assertEqual(self.ioctl(0xdeadbeef), -25)
        self.assertEqual(self.dev.transactions[-1]['name'], 'UNKNOWN')

    def test_verified_plain_noop_and_lifecycle(self):
        self.assertEqual(self.ioctl(USB_OTGCORE_IOCTL_CMD_0XE312), 0)
        self.assertEqual(self.ioctl(USB_OTGCORE_IOCTL_START), 0)
        self.assertTrue(self.dev.started)
        self.assertEqual(self.ioctl(USB_OTGCORE_IOCTL_STOP), 0)
        self.assertFalse(self.dev.started)

    def test_verified_reset_clears_port_descriptor_for_reregistration(self):
        payload = b'\x11' * 36
        self.assertEqual(self.ioctl(USB_OTGCORE_IOCTL_SET_PORT_DESC, 0x5000, payload), 0)
        self.assertEqual(self.ioctl(USB_OTGCORE_IOCTL_RESET), 0)
        self.assertIsNone(self.dev.port_desc)
        self.assertEqual(self.ioctl(USB_OTGCORE_IOCTL_SET_PORT_DESC, 0x5000, payload), 0)

    def test_verified_address_limits_still_enforced(self):
        with self.assertRaises(UnsupportedUsbOtgCore) as ctx:
            self.dev.ioctl(self.owner['owner_id'], USB_OTGCORE_IOCTL_GET_INFO, 0x60000000,
                           self.mem_read, self.mem_write)
        self.assertEqual(ctx.exception.details['reason'], 'user_pointer_outside_task_limit')

    def test_verified_matches_retained_checkpoint_service_history(self):
        """Replay the 312M checkpoint's exact otgcore history under the policy."""
        payload = (b'\xc0\xb5\x02\x00' + b'\xdd\xb0\xf3\x52' * 6 + b'\x00\x00\x00\x00'
                   + b'\xdd\xb0\xf3\x52')
        self.assertEqual(len(payload), 36)
        self.assertEqual(self.ioctl(USB_OTGCORE_IOCTL_SET_PORT_DESC, 0x5000, payload), 0)
        self.assertEqual(self.ioctl(USB_OTGCORE_IOCTL_SET_PARAM, 0x6000, b'\x00' * 16), 0)
        self.assertEqual(self.ioctl(USB_OTGCORE_IOCTL_START), 0)
        self.assertTrue(self.dev.started)

    def test_legacy_policy_unchanged_zero_stub(self):
        legacy = GuestUsbOtgCore()
        owner = legacy.open(flags=2)
        written = {}

        def write_mem(addr, data):
            written[addr] = data

        self.assertEqual(legacy.ioctl(owner['owner_id'], USB_OTGCORE_IOCTL_GET_STATUS, 0x3000,
                                      lambda a, s: b'', write_mem), 0)
        self.assertEqual(written[0x3000], b'\x00')
        self.assertEqual(legacy.ioctl(owner['owner_id'], USB_OTGCORE_IOCTL_GET_INFO, 0x4000,
                                      lambda a, s: b'', write_mem), 0)
        self.assertEqual(written[0x4000], b'\x00' * 8)


class TestGuestUsbOtgCoreGadgetFunctions(unittest.TestCase):
    """Opt-in descriptor-table policy: function descriptors and selection."""

    @staticmethod
    def msc_config(entry0_byte16=0x11, entry0_word20=0x11111111,
                   entry1_byte16=0x22, entry1_word20=0x22222222,
                   tail_byte=0x33, tail_word2=0x33333333):
        """The app's read_port_desc_from_backup 0xa70c builder signature."""
        raw = bytearray(USB_OTGCORE_CONFIG_SIZE)
        raw[0] = 2
        struct.pack_into('<I', raw, 4, 2)       # entry0 io_type_a
        raw[8] = 0                              # entry0 byte_4
        struct.pack_into('<I', raw, 12, 0)      # entry0 word_8
        struct.pack_into('<I', raw, 16, 4)      # entry0 io_type_b
        raw[20] = entry0_byte16                  # backup value
        struct.pack_into('<I', raw, 24, entry0_word20)
        struct.pack_into('<I', raw, 28, 0)      # entry1 io_type_a
        raw[32] = 0                              # entry1 byte_4
        struct.pack_into('<I', raw, 36, 0)      # entry1 word_8
        struct.pack_into('<I', raw, 40, 4)      # entry1 io_type_b
        raw[44] = entry1_byte16                  # backup value
        struct.pack_into('<I', raw, 48, entry1_word20)
        struct.pack_into('<I', raw, 52, 3)      # fixed tail word
        raw[56] = tail_byte                      # backup value
        struct.pack_into('<I', raw, 60, tail_word2)
        return bytes(raw)

    def setUp(self):
        self.dev = GuestUsbOtgCore(
            reply_policy=USB_OTGCORE_REPLY_POLICY_VERIFIED,
            function_policy=USB_OTGCORE_FUNCTION_POLICY_DESCRIPTOR_TABLE)
        self.owner = self.dev.open(flags=2)
        self.mem = {}
        self.written = {}

    def ioctl(self, cmd, arg=0, payload=None):
        if payload is not None:
            self.mem[arg] = payload
        return self.dev.ioctl(self.owner['owner_id'], cmd, arg,
                              lambda addr, size: self.mem[addr][:size],
                              lambda addr, data: self.written.__setitem__(addr, bytes(data)))

    # ------------------------------------------------------- opt-in gating
    def test_default_policy_is_legacy_and_byte_identical(self):
        default = GuestUsbOtgCore()
        self.assertEqual(default.function_policy, USB_OTGCORE_FUNCTION_POLICY_LEGACY)
        self.assertEqual(default.configured_functions, ('mass-storage',))
        self.assertEqual(default.selected_functions, ())
        owner = default.open(flags=2)
        payload = bytes([1]) + b'\x00' * 63
        self.mem[0x2000] = payload
        self.assertEqual(default.ioctl(
            owner['owner_id'], USB_OTGCORE_IOCTL_SET_CONFIG, 0x2000,
            lambda a, s: self.mem[a][:s], lambda a, d: self.written.__setitem__(a, d)), 0)
        self.assertEqual(default.config, payload)
        # Default is the legacy zero-stub policy: GET_INFO is 8 zero bytes.
        self.assertEqual(default.ioctl(
            owner['owner_id'], USB_OTGCORE_IOCTL_GET_INFO, 0x7000,
            lambda a, s: b'', lambda a, d: self.written.__setitem__(a, d)), 0)
        self.assertEqual(self.written[0x7000], b'\x00' * 8)

        # verified-connect without the descriptor-table opt-in keeps the exact
        # previous MSC SET_CONFIG/GET_INFO behaviour.
        verified = GuestUsbOtgCore(reply_policy=USB_OTGCORE_REPLY_POLICY_VERIFIED)
        vowner = verified.open(flags=2)
        self.assertEqual(verified.ioctl(
            vowner['owner_id'], USB_OTGCORE_IOCTL_SET_CONFIG, 0x2000,
            lambda a, s: self.mem[a][:s], lambda a, d: self.written.__setitem__(a, d)), 0)
        self.assertEqual(verified.config_count, 1)
        self.assertEqual(verified.selected_functions, ())
        self.assertEqual(verified.ioctl(
            vowner['owner_id'], USB_OTGCORE_IOCTL_GET_INFO, 0x7000,
            lambda a, s: b'', lambda a, d: self.written.__setitem__(a, d)), 0)
        self.assertEqual(self.written[0x7000], struct.pack('<II', 1, 0))

    def test_function_policy_validation(self):
        with self.assertRaises(ValueError):
            GuestUsbOtgCore(function_policy='invented')
        with self.assertRaises(ValueError):
            GuestUsbOtgCore(
                function_policy=USB_OTGCORE_FUNCTION_POLICY_DESCRIPTOR_TABLE,
                configured_functions=('ptp', 'not-a-function'))
        with self.assertRaises(ValueError):
            gadget_function('not-a-function')

    # ------------------------------------------------ descriptor table
    def test_mass_storage_entry_is_verified(self):
        entry = gadget_function('mass-storage')
        self.assertEqual(entry.usb_class, 0x08)
        self.assertEqual(entry.usb_subclass, 0x06)
        self.assertEqual(entry.usb_protocol, 0x50)
        self.assertEqual(entry.configuration_count, 1)
        self.assertEqual(len(entry.interfaces), 1)
        interface = entry.interfaces[0]
        self.assertEqual((interface.class_code, interface.subclass, interface.protocol),
                         (0x08, 0x06, 0x50))
        self.assertEqual([endpoint.address for endpoint in interface.endpoints],
                         [0x81, 0x02])
        self.assertEqual([endpoint.transfer_type for endpoint in interface.endpoints],
                         ['bulk', 'bulk'])
        self.assertEqual([endpoint.max_packet_size for endpoint in interface.endpoints],
                         [512, 512])
        template = entry.otgcore_template
        self.assertEqual(template.entry_count, 2)
        self.assertEqual(template.entry_io_type_pairs, ((2, 4), (0, 4)))
        self.assertEqual(template.tail_word, 3)
        self.assertIn('E0084', entry.evidence)
        self.assertIn('read_port_desc_from_backup', template.evidence)

    def test_ptp_interface_descriptor_entry(self):
        entry = gadget_function('ptp')
        self.assertEqual((entry.usb_class, entry.usb_subclass, entry.usb_protocol),
                         (0x06, 0x01, 0x01))
        self.assertEqual(entry.configuration_count, 1)
        self.assertEqual(len(entry.interfaces), 1)
        endpoints = entry.interfaces[0].endpoints
        self.assertEqual([(endpoint.address, endpoint.transfer_type,
                           endpoint.max_packet_size, endpoint.interval)
                          for endpoint in endpoints],
                         [(0x81, 'bulk', 512, 0), (0x02, 'bulk', 512, 0),
                          (0x83, 'interrupt', 32, 7)])
        self.assertIsNone(entry.otgcore_template)
        self.assertTrue(entry.unresolved_fields)
        self.assertIn('E0258', entry.evidence)

    def test_uvc_control_and_streaming_descriptor_entries(self):
        control = gadget_function('uvc-control')
        self.assertEqual((control.usb_class, control.usb_subclass), (0x0E, 0x01))
        self.assertEqual(len(control.interfaces), 1)
        self.assertEqual(control.interfaces[0].endpoints, ())
        streaming = gadget_function('uvc-streaming')
        self.assertEqual((streaming.usb_class, streaming.usb_subclass), (0x0E, 0x02))
        endpoints = streaming.interfaces[0].endpoints
        self.assertEqual([(endpoint.address, endpoint.transfer_type,
                           endpoint.max_packet_size) for endpoint in endpoints],
                         [(0x84, 'bulk', 512)])
        composite = gadget_function('composite-ptp-uvc')
        self.assertEqual((composite.usb_class, composite.usb_subclass,
                          composite.usb_protocol), (0xEF, 0x02, 0x01))
        self.assertEqual(len(composite.interfaces), 3)
        for entry in (control, streaming):
            self.assertIsNone(entry.otgcore_template)
            self.assertTrue(entry.unresolved_fields)

    # ------------------------------------------------- function selection
    def test_mass_storage_function_selection(self):
        payload = self.msc_config()
        self.assertEqual(self.ioctl(USB_OTGCORE_IOCTL_SET_CONFIG, 0x2000, payload), 0)
        self.assertEqual(self.dev.selected_functions, ('mass-storage',))
        self.assertEqual(self.dev.config, payload)
        self.assertEqual(self.dev.config_count, 2)
        self.assertEqual(len(self.dev.config_entries), 2)
        self.assertEqual(self.dev.config_entries[0].io_type_a, 2)
        self.assertEqual(self.dev.config_entries[0].byte_b, 0x11)
        self.assertEqual(self.dev.transactions[-1]['selected_functions'],
                         ['mass-storage'])
        self.assertEqual(self.dev.transactions[-1]['descriptor_resolution'],
                         'mass-storage-template')
        self.assertEqual(self.ioctl(USB_OTGCORE_IOCTL_GET_INFO, 0x7000), 0)
        self.assertEqual(self.written[0x7000], struct.pack('<II', 2, 0))

    def test_no_functions_selection(self):
        dev = GuestUsbOtgCore(
            reply_policy=USB_OTGCORE_REPLY_POLICY_VERIFIED,
            function_policy=USB_OTGCORE_FUNCTION_POLICY_DESCRIPTOR_TABLE,
            configured_functions=())
        owner = dev.open(flags=2)
        payload = bytes(USB_OTGCORE_CONFIG_SIZE)
        self.mem[0x2000] = payload
        self.assertEqual(dev.ioctl(owner['owner_id'], USB_OTGCORE_IOCTL_SET_CONFIG, 0x2000,
                                   lambda a, s: self.mem[a][:s],
                                   lambda a, d: self.written.__setitem__(a, d)), 0)
        self.assertEqual(dev.selected_functions, ())
        self.assertEqual(dev.config_count, 0)
        self.assertEqual(dev.ioctl(owner['owner_id'], USB_OTGCORE_IOCTL_GET_INFO, 0x7000,
                                   lambda a, s: b'',
                                   lambda a, d: self.written.__setitem__(a, d)), 0)
        self.assertEqual(self.written[0x7000], struct.pack('<II', 0, 0))

    def test_ptp_selection_stops_explicitly(self):
        dev = GuestUsbOtgCore(
            reply_policy=USB_OTGCORE_REPLY_POLICY_VERIFIED,
            function_policy=USB_OTGCORE_FUNCTION_POLICY_DESCRIPTOR_TABLE,
            configured_functions=('ptp',))
        owner = dev.open(flags=2)
        payload = self.msc_config()
        self.mem[0x2000] = payload
        with self.assertRaises(UnsupportedUsbOtgCore) as ctx:
            dev.ioctl(owner['owner_id'], USB_OTGCORE_IOCTL_SET_CONFIG, 0x2000,
                      lambda a, s: self.mem[a][:s],
                      lambda a, d: self.written.__setitem__(a, d))
        details = ctx.exception.details
        self.assertEqual(details['reason'],
                         'usb_otgcore_gadget_function_descriptor_unresolved')
        self.assertEqual(details['unresolved_functions'], ['ptp'])
        self.assertTrue(any('otgcore SET_CONFIG entry template' in field
                            for field in details['missing_fields']))
        self.assertEqual(details['entry_count'], 2)
        self.assertIn('entries', details)

    def test_uvc_selection_stops_explicitly(self):
        dev = GuestUsbOtgCore(
            reply_policy=USB_OTGCORE_REPLY_POLICY_VERIFIED,
            function_policy=USB_OTGCORE_FUNCTION_POLICY_DESCRIPTOR_TABLE,
            configured_functions=('uvc-control', 'uvc-streaming'))
        owner = dev.open(flags=2)
        self.mem[0x2000] = self.msc_config()
        with self.assertRaises(UnsupportedUsbOtgCore) as ctx:
            dev.ioctl(owner['owner_id'], USB_OTGCORE_IOCTL_SET_CONFIG, 0x2000,
                      lambda a, s: self.mem[a][:s],
                      lambda a, d: self.written.__setitem__(a, d))
        details = ctx.exception.details
        self.assertEqual(details['reason'],
                         'usb_otgcore_gadget_function_descriptor_unresolved')
        self.assertEqual(set(details['unresolved_functions']),
                         {'uvc-control', 'uvc-streaming'})

    def test_unknown_descriptor_stops(self):
        # count 1 is not the verified baseline signature.
        payload = bytes([1]) + b'\x00' * 63
        with self.assertRaises(UnsupportedUsbOtgCore) as ctx:
            self.ioctl(USB_OTGCORE_IOCTL_SET_CONFIG, 0x2000, payload)
        self.assertEqual(ctx.exception.details['reason'],
                         'usb_otgcore_gadget_function_descriptor_unknown')
        self.assertEqual(ctx.exception.details['entry_count'], 1)
        # invalid io type (> 4) is outside the verified conv domain.
        payload = bytearray(self.msc_config())
        struct.pack_into('<I', payload, 4, 5)
        with self.assertRaises(UnsupportedUsbOtgCore) as ctx:
            self.ioctl(USB_OTGCORE_IOCTL_SET_CONFIG, 0x2000, bytes(payload))
        self.assertEqual(ctx.exception.details['reason'],
                         'usb_otgcore_gadget_io_type_unsupported')
        self.assertEqual(ctx.exception.details['io_type'], 5)
        self.assertEqual(ctx.exception.details['valid_io_types'], [0, 1, 2, 3, 4])
        # count above the verified maximum of two.
        payload = bytearray(self.msc_config())
        payload[0] = 3
        with self.assertRaises(UnsupportedUsbOtgCore) as ctx:
            self.ioctl(USB_OTGCORE_IOCTL_SET_CONFIG, 0x2000, bytes(payload))
        self.assertEqual(ctx.exception.details['reason'],
                         'usb_otgcore_gadget_function_count_unsupported')
        self.assertEqual(ctx.exception.details['max_supported'],
                         USB_OTGCORE_CONFIG_MAX_ENTRIES)

    def test_selection_mismatch_stops(self):
        payload = bytes(USB_OTGCORE_CONFIG_SIZE)
        with self.assertRaises(UnsupportedUsbOtgCore) as ctx:
            self.ioctl(USB_OTGCORE_IOCTL_SET_CONFIG, 0x2000, payload)
        self.assertEqual(ctx.exception.details['reason'],
                         'usb_otgcore_gadget_function_selection_mismatch')

    def test_get_info_counts(self):
        self.assertEqual(self.ioctl(USB_OTGCORE_IOCTL_GET_INFO, 0x7000), 0)
        self.assertEqual(self.written[0x7000], struct.pack('<II', 0, 0))
        self.ioctl(USB_OTGCORE_IOCTL_SET_CONFIG, 0x2000, self.msc_config())
        self.assertEqual(self.ioctl(USB_OTGCORE_IOCTL_GET_INFO, 0x7000), 0)
        self.assertEqual(self.written[0x7000], struct.pack('<II', 2, 0))
        # verified-connect (no descriptor-table policy) still reproduces the
        # authentic -EFAULT for a count above two.
        plain = GuestUsbOtgCore(reply_policy=USB_OTGCORE_REPLY_POLICY_VERIFIED)
        owner = plain.open(flags=2)
        self.mem[0x3000] = bytes([3]) + b'\x00' * 63
        plain.ioctl(owner['owner_id'], USB_OTGCORE_IOCTL_SET_CONFIG, 0x3000,
                    lambda a, s: self.mem[a][:s], lambda a, d: None)
        self.assertEqual(plain.ioctl(owner['owner_id'], USB_OTGCORE_IOCTL_GET_INFO, 0x4000,
                                     lambda a, s: b'', lambda a, d: None), -14)

    def test_parse_otgcore_config_wire_layout(self):
        payload = self.msc_config()
        count, entries, tail = parse_otgcore_config(payload)
        self.assertEqual(count, 2)
        self.assertEqual(entries[0].io_type_a, 2)
        self.assertEqual(entries[0].byte_a, 0)
        self.assertEqual(entries[0].word_a, 0)
        self.assertEqual(entries[0].io_type_b, 4)
        self.assertEqual(entries[0].byte_b, 0x11)
        self.assertEqual(entries[0].word_b, 0x11111111)
        self.assertEqual(entries[1].io_type_a, 0)
        self.assertEqual(entries[1].io_type_b, 4)
        self.assertEqual(tail, {'word': 3, 'byte': 0x33, 'word2': 0x33333333})
        with self.assertRaises(ValueError):
            parse_otgcore_config(b'\x00' * 32)


if __name__ == '__main__':
    unittest.main()
