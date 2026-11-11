import unittest

from src.a6400.execution.usbcontrol_msgmap import (
    USB_CONTROL_MSGID_TO_EVENTID,
    USB_CONTROL_MSGID_UNKNOWN_EVENTID,
    USB_CONTROL_INBOUND_SETCONFIG_MSGID,
    USB_CONTROL_SETCONFIG_PARAM_ID,
    msgid_to_eventid,
    describe_usbcontrol_inbound_map,
)


class TestUsbControlInboundMap(unittest.TestCase):
    """E0323: UsbControl::MsgId2EventId decoded mapping."""

    def test_setconfig_maps_to_event_0x13(self):
        self.assertEqual(USB_CONTROL_INBOUND_SETCONFIG_MSGID, 0xA4001)
        self.assertEqual(msgid_to_eventid(0xA4001), 0x13)
        self.assertEqual(msgid_to_eventid(0xA4000), 0x02)

    def test_verified_entries(self):
        self.assertEqual(msgid_to_eventid(0xA6000), 0x01)
        self.assertEqual(msgid_to_eventid(0xA4006), 0x0F)
        self.assertEqual(msgid_to_eventid(0xA400A), 0x11)
        self.assertEqual(msgid_to_eventid(0xA7001), 0x18)
        self.assertEqual(msgid_to_eventid(0x83004), 0x0E)
        self.assertGreaterEqual(len(USB_CONTROL_MSGID_TO_EVENTID), 20)

    def test_unknown_defaults_to_zero(self):
        self.assertEqual(msgid_to_eventid(0x12345),
                         USB_CONTROL_MSGID_UNKNOWN_EVENTID)
        self.assertEqual(msgid_to_eventid(0xA4005), 0)

    def test_report(self):
        report = describe_usbcontrol_inbound_map()
        self.assertEqual(report['thumb_va'], 0x104AC)
        self.assertEqual(report['inbound_setconfig_eventid'], 0x13)
        self.assertEqual(report['setconfig_param_id'], 0x1006)
        self.assertIn('Fsm::DispatchEvent', report['dispatch_chain'])
        self.assertIn('ObjMsg layout', report['boundary'])
