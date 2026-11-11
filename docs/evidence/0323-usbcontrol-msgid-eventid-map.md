# E0323 — UsbControl inbound dispatch and MsgId2EventId map (host-enumeration entry)

Date: 2026-11-11. Inputs: extracted a6400 8.2.5.7 `libUsbControl.so`
(94,220 B). Offline disassembly only; no camera access, no injection, no
execution change. Read-only camera state also recorded (§4) under the standing
authorization.

## 1. Result

The UsbControl FSM entry for a host-configuration notification is now decoded
to the exact message-id → event-id mapping:

- `UsbControl::DispatchEvent` (Thumb 0x10678): `MWF::ObjMsg::GetMessageId(msg)`
  -> `UsbControl::MsgId2EventId(msgId)` -> `UFW::Fsm::DispatchEvent(this+0xF4,
  eventId, msg)`. PLT stubs resolved through `.rel.plt`/`.got.plt`.
- `UFW::MsgReceiver::RcvMsg` (0xA9A8) is the OSAL receive loop; `getMsgSrc`
  uses `MWF::ObjMsg::GetParam(0x112C)`.
- `UFW::MsgUtil::GetCmdMsg(msg)` = `[msg]`; `GetRetMsg(msg)` = `[msg+4]`.

`UsbControl::MsgId2EventId` (Thumb 0x104AC, 328 B) is a binary search; its
literal pool (`0x105C8..0x105EC`) gives this verified map:

| MessageId | FSM event | | MessageId | FSM event |
| --- | --- | --- | --- | --- |
| 0x0A2000 | 0x00 | | 0x0A6004 | 0x07 |
| 0x0A2002 | 0x10 | | 0x0A6005 | 0x08 |
| 0x0A4000 | 0x02 | | 0x0A6003 | 0x09 |
| **0x0A4001** | **0x13** | | 0x0A6002 | 0x06 |
| 0x0A4006 | 0x0F | | 0x0A7000 | 0x17 |
| 0x0A400A | 0x11 | | 0x0A7001 | 0x18 |
| 0x0A400B | 0x12 | | 0x83001 | 0x0C |
| 0x0A400C | 0x14 | | 0x83002 | 0x0D |
| 0x0A400D | 0x15 | | 0x83003 | 0x0B |
| 0x0A6000 | 0x01 | | 0x83004 | 0x0E |
| 0x85002 | 0x03 | | 0x85003 | 0x04 |

Unknown ids return event 0.  **Inbound SETCONFIG `{CategoryId 0x6103,
MessageId 0x0A4001, paramId 0x1006}` therefore dispatches FSM event 0x13** —
the exact transition the host-enumeration contract needs.

## 2. Code/tests

`src/a6400/execution/usbcontrol_msgmap.py`:
`USB_CONTROL_MSGID_TO_EVENTID`, `msgid_to_eventid`,
`describe_usbcontrol_inbound_map` (`thumb_va=0x104AC`,
`inbound_setconfig_eventid=0x13`, `setconfig_param_id=0x1006`, dispatch chain
and boundary). Tests `tests/test_usbcontrol_msgmap.py`. Full suite: **939 tests
OK**.

## 3. Boundary

The mapping alone does not deliver anything: an inbound message still needs the
**`MWF::ObjMsg` layout** (`GetMessageId`/`GetParam` field offsets) before an
opt-in kernel/enumeration event can be constructed and queued. No injection is
modelled here, no fabricated message bytes, no wakeup claimed.

## 4. Read-only camera state (standing authorization; no writes)

`/proc/uptime` 24,833 -> 24,846 s (responsive). Loaded USB modules:
`usbg_stillimage`, `usbg_storage`, `usbg_buspower`, `usbg_sen`, `devno`,
`osal_uipc` — **no `usbg_video`/`usbg_audio`**. UDC `dwc3.0`: state
**configured**, `current_speed` **high-speed**, `maximum_speed` **super-speed**;
configfs absent; `/dev/usb` nodes present per the E0320 table. Physical
enablement remains off the table (user constraint: debugger read-only only).
