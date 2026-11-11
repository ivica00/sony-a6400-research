"""UsbControl inbound message-id -> FSM event-id map (E0323).

Decoded from libUsbControl.so `UsbControl::MsgId2EventId` (Thumb 0x104AC,
328 B) by resolving its pc-relative literal pool; default/unknown message ids
return event id 0.  Pure constants/helpers only: no wakeup or execution model.
"""

# Verified entries from the MsgId2EventId compare tree (E0323).
USB_CONTROL_MSGID_TO_EVENTID = {
    0xA2000: 0x00,
    0xA2002: 0x10,
    0xA4000: 0x02,
    0xA4001: 0x13,   # inbound SETCONFIG (E0303/E0310) -> FSM event 0x13
    0xA4006: 0x0F,
    0xA400A: 0x11,
    0xA400B: 0x12,
    0xA400C: 0x14,
    0xA400D: 0x15,
    0xA6000: 0x01,
    0xA6002: 0x06,
    0xA6003: 0x09,
    0xA6004: 0x07,
    0xA6005: 0x08,
    0xA7000: 0x17,
    0xA7001: 0x18,
    0x83001: 0x0C,
    0x83002: 0x0D,
    0x83003: 0x0B,
    0x83004: 0x0E,
    0x85002: 0x03,
    0x85003: 0x04,
}
USB_CONTROL_MSGID_UNKNOWN_EVENTID = 0
# Inbound SETCONFIG message id observed/decoded for the USB lane (E0303/E0310).
USB_CONTROL_INBOUND_SETCONFIG_MSGID = 0xA4001
USB_CONTROL_SETCONFIG_PARAM_ID = 0x1006


def msgid_to_eventid(message_id):
    """Mirror UsbControl::MsgId2EventId (unknown -> event id 0)."""
    return USB_CONTROL_MSGID_TO_EVENTID.get(
        message_id, USB_CONTROL_MSGID_UNKNOWN_EVENTID)


def describe_usbcontrol_inbound_map():
    """Return the decoded inbound message-map evidence (no delivery modelled)."""
    return {
        'function': 'UsbControl::MsgId2EventId',
        'thumb_va': 0x104AC,
        'map': dict(USB_CONTROL_MSGID_TO_EVENTID),
        'default_event_id': USB_CONTROL_MSGID_UNKNOWN_EVENTID,
        'inbound_setconfig_msgid': USB_CONTROL_INBOUND_SETCONFIG_MSGID,
        'inbound_setconfig_eventid': msgid_to_eventid(
            USB_CONTROL_INBOUND_SETCONFIG_MSGID),
        'setconfig_param_id': USB_CONTROL_SETCONFIG_PARAM_ID,
        'dispatch_chain': (
            'UFW::MsgReceiver::RcvMsg -> UsbControl::DispatchEvent -> '
            'MWF::ObjMsg::GetMessageId -> UsbControl::MsgId2EventId -> '
            'UFW::Fsm::DispatchEvent(this+0xF4, eventId, msg)'),
        'evidence': 'libUsbControl.so MsgId2EventId compare tree + literal '
                    'pool (0x105C8..0x105EC); PLT-resolved dispatch chain',
        'boundary': 'MWF::ObjMsg layout (MessageId/GetParam offsets) still '
                    'needed before an inbound message can be constructed; no '
                    'injection is modelled here',
    }
