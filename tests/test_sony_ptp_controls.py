import struct
import unittest

from tools.research.sony_ptp_controls import parse_properties, SonySettings


def blob(value=400, enabled=1):
    return (struct.pack('<IIHHBBIIBH', 1, 0, 0xD21E, 6, 1, enabled,
                        100, value, 2, 3) + struct.pack('<III', 100, 400, 800))


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
