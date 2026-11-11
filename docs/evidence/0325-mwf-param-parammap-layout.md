# E0325 — MWF::Param / ParamMap container layout (inbound message params)

Date: 2026-11-11. Input: extracted a6400 `libMWF.so` (dynsym intact). Offline
disassembly only; no camera access, no message construction, no injection.

## 1. Result

The ObjMsg param container is now structurally decoded:

- `MWF::Param` base: `+0x00` param id, `+0x04` vtable.
  `Param::Param()` (0x21718) zeroes `[param+0]` and installs the vtable;
  `Param::Clear` (0x21744) calls `[vtable+4]`.
- `ParamMap` entry/node: `+0x00` param id, `+0x04` param object pointer.
  `ParamMap::Add(id, param)` (0x22B66) finds/creates a node, stores the id at
  node+0, then assigns the param object (0x1C350) into node+4.
- `ObjMsgBody+0x0C` is the ParamMap (`ObjMsgBody::AddParam` 0x202E7 adds 0xC
  and calls 0x1AEC4).
- `ObjMsg::GetParam(paramId)` (0x205C0): `body = obj[0]`; if null -> null;
  lock body; `body->GetParam(paramId, 0)` (0x1C924); unlock; return Param*.

## 2. Why this matters

The inbound SETCONFIG message is `{CategoryId 0x6103, MessageId 0x0A4001,
param 0x1006 = 0}` (E0303/E0310) and the FSM mapping is `0x0A4001 -> event
0x13` (E0323). With ObjMsg/ObjMsgBody (E0324) and this param container, the
memory layout of a message is now known except the derived Param type/data and
vtable binding.

## 3. Boundary

`MWF::Param` is polymorphic: construction needs the derived integer-param
vtable (runtime address in `libMWF` `.data.rel.ro` after load) and the
serializer/decoder semantics (`MessageSerializer::encObjMsg` 0x1F5BA is 908 B
and not yet decoded). Constructing an ObjMsg/Param in the emulator without
those would fabricate vtable/data, so **no inbound message is constructed or
injected**; no wakeup/FSM transition is claimed.

## 4. Code/tests

`src/a6400/execution/mwf_objmsg.py` additions: `PARAM_FIELDS`,
`PARAMMAP_NODE_FIELDS`, `OBJMSG_PARAM_CONTAINER_OFFSET=0x0C`,
`PARAM_CTOR_VA`, `PARAMMAP_ADD_VA`, `PARAMMAP_GET_VA`, `OBJMSG_GETPARAM_VA`,
`describe_mwf_param_layout`. Tests `tests/test_mwf_objmsg.py` (Param/ParamMap
structure + boundary). Full suite: **945 tests OK**.
