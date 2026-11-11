import struct
import unittest

from tools.research.sony_ptp_controls import (
    PROPERTY_SPECS, SonySettings, decode_properties, decode_property_value,
    encode_property_value, parse_properties, property_spec, validate_property_value,
    validate_setting_value,
)
from tools.research.ptp_liveview_client import (
    LiveviewLifecycle, LiveviewRecoveryPolicy, decode_response_code,
    is_wpd_shutdown_error, plan_liveview_teardown,
)


def blob(value=400, enabled=1):
    return (struct.pack('<IIHHBBIIBH', 1, 0, 0xD21E, 6, 1, enabled,
                        100, value, 2, 3) + struct.pack('<III', 100, 400, 800))


DTYPE_FMT = {2: 'B', 3: 'h', 4: 'H', 6: 'I'}


def descriptor(code, dtype, default, current, form=0, values=None,
               limits=None, access=0, enabled=1):
    fmt = DTYPE_FMT[dtype]
    data = struct.pack('<HHBB', code, dtype, access, enabled)
    data += struct.pack('<' + fmt, default) + struct.pack('<' + fmt, current)
    data += struct.pack('<B', form)
    if form == 1:
        data += b''.join(struct.pack('<' + fmt, value) for value in limits)
    elif form == 2:
        data += struct.pack('<H', len(values))
        data += b''.join(struct.pack('<' + fmt, value) for value in values)
    return data


def properties_blob(descriptors):
    return struct.pack('<II', len(descriptors), 0) + b''.join(descriptors)


def extended_blob():
    return properties_blob([
        descriptor(0x5001, 2, 100, 87),
        descriptor(0x5005, 4, 2, 2, form=2, values=[2, 4, 6, 0x8010]),
        descriptor(0x5007, 4, 280, 320, form=1, limits=[0, 65535, 1]),
        descriptor(0x9999, 6, 0, 123),
    ])


class ExtendedDriver:
    """Offline 0x9209 fixture with extra PTP properties and an unknown code."""

    def __init__(self, data=None):
        self.data = data or extended_blob()
        self.writes = []

    def sendReadCommand(self, code, args):
        assert (code, args) == (0x9209, [])
        return 0x2001, self.data

    def sendWriteCommand(self, code, args, payload):
        self.writes.append((code, args, payload))
        return 0x2001


class Driver:
    def __init__(self, confirm=True, enabled=1, rc=0x2001):
        self.value, self.confirm, self.enabled, self.rc = 400, confirm, enabled, rc
        self.writes = []

    def sendReadCommand(self, code, args):
        assert (code, args) == (0x9209, [])
        return 0x2001, blob(self.value, self.enabled)

    def sendWriteCommand(self, code, args, data):
        self.writes.append((code, args, data))
        if self.confirm:
            self.value = struct.unpack('<I', data)[0]
        return self.rc


class SonySettingsTests(unittest.TestCase):
    def test_range_shutter_and_aperture_and_ev_use_confirmed_notches(self):
        cases = [('shutter', 0xD20D, 6, 'I', [65636, 65661], None),
                 ('aperture', 0x5007, 4, 'H', [280, 320], None),
                 ('ev', 0x5010, 3, 'h', [0, 300], [300, 0])]
        for name, code, dtype, fmt, values, enum in cases:
            class NotchDriver:
                position = 0
                def sendReadCommand(self, op, args):
                    data = struct.pack('<IIHHBB', 1, 0, code, dtype, 0, 1)
                    data += struct.pack('<' + fmt * 2, values[0], values[self.position])
                    if enum:
                        data += struct.pack('<BH', 2, len(enum)) + struct.pack('<' + fmt * len(enum), *enum)
                    else:
                        data += struct.pack('<B', 1) + struct.pack('<' + fmt * 3, 0, (1 << (struct.calcsize(fmt)*8))-1, 1)
                    return 0x2001, data
                def sendWriteCommand(self, op, args, data):
                    if op != 0x9207 or args != [code]:
                        raise AssertionError('Expected relative property command')
                    self.position += struct.unpack('<b', data)[0]
                    return 0x2001
            with self.subTest(name=name):
                settings = SonySettings(NotchDriver())
                self.assertEqual(settings.apply(name, values[1])[name]['value'], values[1])
                self.assertEqual(settings.apply(name, values[0])[name]['value'], values[0])

    def test_legacy_iso_steps_follow_enum_not_numeric_order(self):
        class LegacyDriver:
            def __init__(self):
                self.values = [0xFFFFFF, 100, 400, 800]
                self.position = 0
                self.writes = []

            def sendReadCommand(self, code, args):
                data = struct.pack('<IIHHBBIIBH', 1, 0, 0xD21E, 6, 0, 1,
                                   100, self.values[self.position], 2, 4)
                return 0x2001, data + struct.pack('<4I', *self.values)

            def sendWriteCommand(self, code, args, data):
                self.writes.append((code, data))
                self.position += struct.unpack('<b', data)[0]
                return 0x2001
        driver = LegacyDriver()
        settings = SonySettings(driver)
        self.assertEqual(settings.apply('iso', 800)['iso']['value'], 800)
        self.assertEqual(settings.apply('iso', 0xFFFFFF)['iso']['value'], 0xFFFFFF)
        self.assertEqual(driver.writes, [(0x9207, b'\x01')] * 3 + [(0x9207, b'\xff')] * 3)

    def test_truncations_never_publish_partial_descriptors(self):
        data = blob()
        for length in range(len(data)):
            with self.subTest(length=length), self.assertRaises(ValueError):
                parse_properties(data[:length])

    def test_write_uses_camera_datatype_and_readback(self):
        driver = Driver()
        settings = SonySettings(driver)
        result = settings.apply('iso', 800)
        self.assertEqual(driver.writes, [(0x9205, [0xD21E], struct.pack('<I', 800))])
        self.assertEqual(result['iso']['value'], 800)

    def test_ack_without_readback_is_not_confirmation(self):
        settings = SonySettings(Driver(confirm=False))
        with self.assertRaisesRegex(RuntimeError, 'did not confirm'):
            settings.apply('iso', 800, timeout=0)
        self.assertEqual(settings.snapshot()['iso']['value'], 400)

    def test_rejected_response_does_not_succeed(self):
        with self.assertRaisesRegex(RuntimeError, 'rejected'):
            SonySettings(Driver(confirm=False, rc=0x2019)).apply('iso', 800)

    def test_restrictions_and_unadvertised_values_never_write(self):
        for enabled, name, value in [(0, 'iso', 800), (1, 'iso', 1600),
                                     (1, 'recording', 1), (1, 'iso', True)]:
            driver = Driver(enabled=enabled)
            with self.assertRaises(ValueError):
                SonySettings(driver).apply(name, value)
            self.assertEqual(driver.writes, [])

    def test_body_change_is_reflected_on_next_refresh(self):
        driver = Driver()
        settings = SonySettings(driver)
        settings.refresh()
        driver.value = 800
        self.assertEqual(settings.refresh()['iso']['label'], '800')


class PropertyDecodingTests(unittest.TestCase):
    def test_known_control_values_decode_with_units(self):
        cases = [
            (0xD20D, (1 << 16) | 100, '1/100'),
            (0x5007, 280, 'f/2.8'),
            (0xD21E, 0xFFFFFF, 'Auto'),
            (0x5010, 300, '+0.3 EV'),
            (0x5001, 87, '87%'),
            (0x5005, 2, 'Auto'),
            (0x500A, 2, 'AF-S'),
            (0x500E, 3, 'A'),
        ]
        for code, value, label in cases:
            with self.subTest(code=hex(code)):
                decoded = decode_property_value(code, value)
                self.assertTrue(decoded.known_code)
                self.assertTrue(decoded.known_value)
                self.assertEqual(decoded.label, label)
                self.assertEqual(decoded.spec_name, PROPERTY_SPECS[code].name)

    def test_unknown_property_and_unlisted_values_are_not_success(self):
        unknown = decode_property_value(0x1234, 1)
        self.assertFalse(unknown.known_code)
        self.assertFalse(unknown.known_value)
        self.assertIsNone(unknown.label)
        self.assertEqual(unknown.reason, 'unknown_property_code')

        for code, value in [(0x5005, 0x7777), (0x500A, 0x7777), (0x500E, 0x7777)]:
            with self.subTest(code=hex(code)):
                decoded = decode_property_value(code, value)
                self.assertTrue(decoded.known_code)
                self.assertFalse(decoded.known_value)
                self.assertIsNone(decoded.label)
                self.assertEqual(decoded.reason, 'unlisted_enum_value')

        # A known code with undecoded value semantics keeps the value but no label.
        priority = decode_property_value(0xD25A, 1)
        self.assertTrue(priority.known_code)
        self.assertTrue(priority.known_value)
        self.assertIsNone(priority.label)
        self.assertEqual(priority.reason, 'label_not_mapped')

    def test_unavailable_and_out_of_range_values_are_explicit(self):
        for code, value in [(0x5007, 0), (0x5007, 0xFFFF),
                            (0xD20D, 0), (0xD20D, 0xFFFFFFFF)]:
            with self.subTest(code=hex(code), value=hex(value)):
                decoded = decode_property_value(code, value)
                self.assertFalse(decoded.known_value)
                self.assertIsNone(decoded.label)
                self.assertEqual(decoded.reason, 'unavailable_in_current_state')

        self.assertEqual(decode_property_value(0x5001, 101).reason,
                         'outside_reference_range')
        self.assertEqual(decode_property_value(0xD21E, 0).reason,
                         'invalid_iso_value')
        bulb = decode_property_value(0xD20D, 1 << 16)
        self.assertTrue(bulb.known_value)
        self.assertEqual(bulb.label, 'Bulb')
        self.assertEqual(bulb.reason, 'bulb_encoding')
        invalid = decode_property_value(0xD20D, 0x00000064)
        self.assertFalse(invalid.known_value)
        self.assertEqual(invalid.reason, 'invalid_shutter_encoding')

        ev = decode_property_value(0x5010, 4000)
        self.assertTrue(ev.known_value)
        self.assertEqual(ev.label, '+4.0 EV')
        self.assertEqual(ev.reason, 'outside_reference_range')

        for code, value in [(0x5005, 'Auto'), (0xD21E, True), (0x5001, None)]:
            with self.subTest(code=hex(code), value=value):
                decoded = decode_property_value(code, value)
                self.assertTrue(decoded.known_code)
                self.assertFalse(decoded.known_value)
                self.assertEqual(decoded.reason, 'unsupported_value_type')

    def test_decode_properties_includes_unknown_codes(self):
        properties = parse_properties(extended_blob())
        self.assertIn(0x9999, properties)
        decoded = decode_properties(properties)
        self.assertEqual(decoded[0x5001].label, '87%')
        self.assertEqual(decoded[0x5007].label, 'f/3.2')
        self.assertEqual(decoded[0x5005].label, 'Auto')
        self.assertFalse(decoded[0x9999].known_code)
        self.assertFalse(decoded[0x9999].known_value)

    def test_validation_and_encoding_never_coerce_unknowns(self):
        self.assertEqual(validate_property_value(0xD21E, 800), 800)
        self.assertEqual(validate_property_value(0xD21E, 0xFFFFFF), 0xFFFFFF)
        self.assertEqual(validate_property_value(0x5007, 280), 280)
        self.assertEqual(validate_property_value(0xD20D, (1 << 16) | 100),
                         (1 << 16) | 100)
        for code, value in [(0x9999, 1), (0x5001, 101), (0x5007, 0),
                            (0x5007, 3000), (0x5010, 4000), (0xD21E, 0),
                            (0xD20D, 0), (0x5005, 0x7777), (0x5007, True),
                            (0x5007, '280')]:
            with self.subTest(code=hex(code), value=value):
                with self.assertRaises(ValueError):
                    validate_property_value(code, value)

        self.assertEqual(encode_property_value(0xD21E, 800), struct.pack('<I', 800))
        self.assertEqual(encode_property_value(0x5007, 280), struct.pack('<H', 280))
        self.assertEqual(encode_property_value(0x5001, 87), struct.pack('<B', 87))
        with self.assertRaises(ValueError):
            encode_property_value(0x9999, 1)

        self.assertEqual(validate_setting_value('iso', 800), 800)
        for name, value in [('recording', 1), ('iso', '800'), ('iso', True)]:
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    validate_setting_value(name, value)

    def test_specs_expose_codes_types_and_reference_ranges(self):
        self.assertEqual(property_spec(0xD20D).datatype_name(), 'UINT32')
        self.assertEqual(property_spec(0x5007).datatype_name(), 'UINT16')
        self.assertEqual(property_spec(0x5010).datatype_name(), 'INT16')
        self.assertEqual(property_spec(0x5001).reference_range, (0, 100))
        self.assertEqual(property_spec(0x5010).reference_range, (-3000, 3000))
        self.assertIsNone(property_spec(0x1234))


class ExtendedSettingsTests(unittest.TestCase):
    def test_extended_properties_decode_without_gaining_control_authority(self):
        settings = SonySettings(ExtendedDriver())
        settings.refresh()
        controls = settings.snapshot()
        self.assertNotIn('battery', controls)
        self.assertNotIn('white_balance', controls)
        decoded = settings.decoded_properties()
        self.assertEqual(decoded[0x5001].label, '87%')
        self.assertEqual(decoded[0x5005].label, 'Auto')
        self.assertEqual(decoded[0x5007].label, 'f/3.2')
        self.assertFalse(decoded[0x9999].known_code)

    def test_describe_control_exposes_datatype_and_decode_reason(self):
        settings = SonySettings(Driver())
        settings.refresh()
        control = settings.describe_control('iso')
        self.assertEqual(control['datatype'], 6)
        self.assertEqual(control['datatype_name'], 'UINT32')
        self.assertTrue(control['known_value'])
        self.assertIsNone(control['decode_reason'])
        with self.assertRaises(ValueError):
            settings.describe_control('recording')


class LiveviewHelperTests(unittest.TestCase):
    def test_response_codes_and_unknowns_are_not_success(self):
        ok = decode_response_code(0x2001)
        self.assertEqual((ok.name, ok.success, ok.category), ('OK', True, 'success'))
        busy = decode_response_code(0x2019)
        self.assertFalse(busy.success)
        self.assertTrue(busy.retryable)
        self.assertEqual(busy.category, 'busy')
        session = decode_response_code(0x2003)
        self.assertEqual(session.category, 'session')
        self.assertFalse(session.success)
        unknown = decode_response_code(0x2FFF)
        self.assertIsNone(unknown.name)
        self.assertFalse(unknown.success)
        self.assertFalse(unknown.retryable)
        self.assertEqual(unknown.category, 'unknown')

    def test_recovery_policy_handles_reconnect_retry_and_exhaustion(self):
        policy = LiveviewRecoveryPolicy(max_attempts=3)
        shutdown = RuntimeError('Shutdown was already called on this object')
        reconnect = policy.for_exception(shutdown, 0, driver_present=True)
        self.assertEqual(reconnect.action, 'close_and_reconnect')
        self.assertTrue(is_wpd_shutdown_error(shutdown))
        self.assertEqual(policy.for_exception(shutdown, 0,
                                              driver_present=False).action,
                         'reconnect')
        retry = policy.for_exception(RuntimeError('no response'), 0)
        self.assertEqual(retry.action, 'retry')
        self.assertGreater(retry.delay, 0)
        self.assertEqual(policy.for_exception(RuntimeError('x'), 3).action,
                         'stop')
        self.assertEqual(policy.for_empty_frame(2).action, 'retry')
        self.assertEqual(policy.for_empty_frame(3).action, 'stop')

    def test_recovery_policy_response_actions(self):
        policy = LiveviewRecoveryPolicy(max_attempts=4)
        self.assertEqual(policy.for_response(0x2001, 0).action, 'continue')
        self.assertEqual(policy.for_response(0x2019, 0).action, 'retry')
        self.assertEqual(policy.for_response(0x2003, 0).action, 'reconnect')
        self.assertEqual(policy.for_response(0x2005, 0).action, 'stop')
        self.assertEqual(policy.for_response(0x2FFF, 0).action, 'stop')

    def test_lifecycle_transitions_and_invalid_actions(self):
        lifecycle = LiveviewLifecycle()
        with self.assertRaises(ValueError):
            lifecycle.frame_ok()
        lifecycle.connected()
        lifecycle.frame_ok()
        self.assertEqual((lifecycle.state, lifecycle.frames), ('streaming', 1))
        lifecycle.frame_failed('timeout')
        self.assertEqual((lifecycle.state, lifecycle.failures), ('degraded', 1))
        lifecycle.begin_reconnect('shutdown')
        self.assertEqual(lifecycle.state, 'reconnecting')
        lifecycle.connected()
        self.assertEqual((lifecycle.state, lifecycle.reconnects),
                         ('streaming', 1))
        lifecycle.request_close()
        self.assertEqual(lifecycle.state, 'closing')
        lifecycle.mark_closed()
        self.assertEqual(lifecycle.state, 'closed')
        with self.assertRaises(ValueError):
            lifecycle.connected()

    def test_teardown_plan_orders_and_skips_absent_components(self):
        full = plan_liveview_teardown(server_present=True, settings_present=True,
                                      driver_present=True)
        self.assertEqual([step.target for step in full],
                         ['http', 'settings', 'driver', 'lifecycle'])
        self.assertEqual([step.order for step in full], [1, 2, 3, 4])
        self.assertFalse(full[-1].required)
        partial = plan_liveview_teardown(server_present=False,
                                        settings_present=False,
                                        driver_present=False)
        self.assertEqual([(step.target, step.action) for step in partial],
                         [('lifecycle', 'mark_closed')])
