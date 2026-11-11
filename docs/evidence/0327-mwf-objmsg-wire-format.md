# E0327 — Serialized ObjMsg wire format decoded (header + param entries)

Date: 2026-11-11. Input: extracted a6400 `libMWF.so`. Offline disassembly only;
no camera access, no UIPC injection, no execution change.

## 1. Result

`MessageSerializer::decObjMsg` (0x1FB8C, 1454 B) and `encObjMsg` (0x1F5BA,
908 B) give the exact serialized message format:

| Region | Size | Fields |
| --- | --- | --- |
| header | 12 B | `+0` category id (u32), `+4` message id (u32), `+8` param count (u32) |
| param entry header | 8 B | `+0` param id (u32), `+4` Param::Type (u32) |
| scalar value | 4 B | value (all scalar types occupy 4 B; u16 read with `ldrh`) |
| array value | 4 B + padded data | element count (u32), then `count` bytes padded to 4 |

Evidence:

- decObjMsg requires buffer > 0xB and non-null; `body=ensure_body(obj)`; lock;
  `[buf+0]` -> body category (0x1A398); `[buf+4]` -> body message id (0x1B700);
  `[buf+8]` -> local param count; advances 12 B into the param loop.
- param loop requires remaining > 7; reads `[buf+0]`=param id (`sb`),
  `[buf+4]`=type (0-based switch on `type-1`, max 0x28), advances 8 B, then
  decodes the value with the type-specific `decStdInt`/`decBool`/
  `decStdIntArray` helper and calls `ObjMsgBody::AddParam(body, id, paramObj)`.
- scalar helpers (`decStdInt<int>` 0x1FA6B, `encStdInt<int>` 0x1F449, u16
  0x1FA49, u32 0x1FA8D) consume/produce 4 B.
- array helpers (`decStdIntArray<char>` 0x1FAD1, `encStdIntArray<char>`
  0x1F4B0): `size = count + 3 & ~3 + 4`.

## 2. SETCONFIG instance

Inbound SETCONFIG `{CategoryId 0x6103, MessageId 0x0A4001, param 0x1006 = 0}`:
`12 + 8 + 4 = 24` bytes:
`6103 0000 | 0140 0A00 | 0100 0000 | 0610 0000 | 0700 0000 | 0000 0000`
(little-endian u32 words: 0x6103, 0x0A4001, 1, 0x1006, 7, 0).

## 3. Boundary

`UsbControl::MsgReceiver::RcvMsg` returns `payload[0]` as an **ObjMsg pointer**
from the shared pool (E0324), i.e. the inbound USB lane appears to carry a
kernel/shared-pool ObjMsg, not a serialized buffer. This wire form documents the
serializer/decoder side only: **no kernel/shared-pool ObjMsg construction and no
UIPC message injection are modelled**, and no FSM transition is claimed.

## 4. Code/tests

`src/a6400/execution/mwf_objmsg.py`: `OBJMSG_WIRE_HEADER_FIELDS`,
`OBJMSG_WIRE_PARAM_HEADER_FIELDS`, `OBJMSG_WIRE_PARAM_HEADER_SIZE`,
`OBJMSG_WIRE_SCALAR_SIZE`, `DECDECOBJMSG_VA`, `build_objmsg_wire`
(scalars only, raises on unsupported types), `describe_mwf_wire_format`.
Tests: SETCONFIG 24-byte layout, empty params, unsupported type, report.
Full suite: **950 tests OK**.
