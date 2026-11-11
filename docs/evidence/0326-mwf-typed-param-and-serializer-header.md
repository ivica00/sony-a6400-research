# E0326 — Typed Param layout and MessageSerializer header (wire format start)

Date: 2026-11-11. Input: extracted a6400 `libMWF.so`. Offline only; no camera
access, no wire bytes constructed/injected, no execution change.

## 1. Result

- **Typed `Param`** (`ParamStd_Template<T, Param::Type>`): `+0x00 value`,
  `+0x04 vtable`; `GetValue` reads `[obj+0]` (e.g. `ParamStd<int32>::GetValue`
  0x233A8); typed ctors (0x23371 int32, 0x233CD uint32) install the vtable and
  value. **Param id is not inside the Param object** — it lives in the
  `ParamMap` node (`+0 id`, `+4 param*`, E0325).
- **`Param::Type` values** decoded from dynsym mangling: bool 1, char 2,
  int8 3, uint8 4, int16 5, uint16 6, **int32 7**, uint32 8, pointer 9;
  arrays: char 35, int8 36, uint32 38, bool 39, int16 42, uint16 43,
  int32 44.
- **`MessageSerializer::encObjMsg`** (0x1F5BA) requires a buffer > 0xB and
  writes a **12-byte header**; offsets `+0/+4/+8` are written before the param
  loop. Their exact meaning (category / message id / count ordering) is still
  pending full decode, so they are labelled hypotheses.

## 2. Boundary

The serializer **param-entry encoding** and `MessageSerializer::decObjMsg` are
not decoded, and the vtable binding for a constructed `Param` is a runtime
`libMWF` address. Therefore no ObjMsg/wire bytes are constructed and nothing is
injected; the inbound SETCONFIG contract (E0323/E0324/E0325) remains
fail-closed.

## 3. Code/tests

`src/a6400/execution/mwf_objmsg.py` additions: `PARAM_TYPE_VALUES`,
`PARAM_OBJECT_FIELDS`, `OBJMSG_SERIALIZED_HEADER_SIZE=0x0C`,
`OBJMSG_SERIALIZED_HEADER_FIELDS_PENDING`, `ENCOBJMSG_VA`,
`PARAMSTD_INT32_CTOR_VA`, `PARAMSTD_INT32_GETVALUE_VA`,
`describe_mwf_typed_param_layout`. Tests in `tests/test_mwf_objmsg.py`. Full
suite: **947 tests OK**.

## 4. Next

Decode the `encObjMsg` param loop and `decObjMsg` (param id/type/length
encoding), then the contract can build wire bytes from decoded semantics
instead of guessed memory.
