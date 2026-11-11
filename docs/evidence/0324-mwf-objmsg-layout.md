# E0324 — MWF::ObjMsg layout and UsbControl RcvMsg payload ABI (inbound entry)

Date: 2026-11-11. Inputs: extracted a6400 8.2.5.7 `libMWF.so` (238,152 B,
dynsym intact) and `libUsbControl.so`. Offline disassembly only; no camera
access, no message construction/injection, no execution change.

## 1. Result

The inbound-message object layout needed by the host-enumeration contract is
decoded:

- `MWF::ObjMsg` object: `+0x00` = **body pointer**, `+0x04` = vtable/ref.
  `ObjMsg::ObjMsg()` (Thumb 0x203AC) zeroes `+0` and installs the vtable.
- `MWF::ObjMsgBody`: `+0x04` = **category id**, `+0x08` = **message id**,
  `+0x0C` = param container.
  - `ObjMsgBody::GetMessageId` (0x1F17E) = `ldr r0,[r0,#8]`;
  - `ObjMsgBody::GetCategoryId` (0x1F176) = `ldr r0,[r0,#4]`;
  - `ObjMsg::GetMessageId` (0x20528) dereferences `obj[0]` (body) and returns
    body+8; `ObjMsg::SetCateIdMsgId` (0x20494) writes body+4 and body+8.

`UFW::MsgReceiver::RcvMsg` (UsbControl, Thumb 0xA9A8) receives a **serialized
UIPC message**: it returns
  - `*out1 = payload[0]` = **pointer to the ObjMsg** (allocated in the shared
    UIPC pool), and
  - `*out2 = payload[-4]` = OSAL message **source id** (helper at 0xA800/
    0xA80A stores/loads the word at msg-4),
then frees the UIPC envelope. A mismatching source triggers a relay/forward
path (0x28-byte envelope with `0x70`/`0xCA` header fields).

## 2. Why this matters

Combined with E0323 (`MsgId2EventId`: inbound SETCONFIG `0x0A4001` -> FSM
event `0x13`), the remaining pieces for an **opt-in emulator host-enumeration
contract** are now known except the param entry layout:

1. build `{obj, body}` in guest/shared memory: `obj[0]=body`,
   `body[4]=0x6103`, `body[8]=0x0A4001` (SETCONFIG), params later;
2. enqueue a UIPC message whose payload word0 points at that ObjMsg;
3. UsbControl `RcvMsg` -> `DispatchEvent` -> `MsgId2EventId` -> FSM event 0x13.

## 3. Boundary

**Param entry layout is not decoded** (`ObjMsg`/`ParamMap`; `Param` objects are
pointers added via `ObjMsg::AddParam` 0x20570). The inbound SETCONFIG carries
param id `0x1006 = 0`, so the param container must be modelled before a message
is constructed. No message is constructed or injected here, and no wakeup or
FSM transition is claimed.

## 4. Code/tests

`src/a6400/execution/mwf_objmsg.py`:
`OBJMSG_FIELDS`, `OBJMSG_BODY_FIELDS`,
`UIPC_MESSAGE_OBJMSG_POINTER_OFFSET=0`, `UIPC_MESSAGE_SOURCE_OFFSET=-4`,
function addresses, `read_objmsg_fields`, `decode_objmsg_pointer`,
`describe_mwf_objmsg_layout`. Tests `tests/test_mwf_objmsg.py`. Full suite:
**943 tests OK**.
