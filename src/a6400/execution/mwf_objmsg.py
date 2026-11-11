"""MWF::ObjMsg / ObjMsgBody layout for inbound-message construction (E0324).

Decoded from extracted a6400 `libMWF.so` (dynsym present):
- `ObjMsg` object: `+0x00` body pointer, `+0x04` vtable/ref (ctor).
- `ObjMsgBody`: `+0x04` category id, `+0x08` message id, `+0x0C` param container.
- `ObjMsg::GetMessageId` dereferences the body and reads body+8;
  `ObjMsg::SetCateIdMsgId(cat, msgid)` writes body+4 / body+8.
- `UFW::MsgReceiver::RcvMsg` returns `payload[0]` (pointer to the ObjMsg in the
  shared UIPC pool) and `payload[-4]` (OSAL message source id, written by the
  sender helper at msg-4).

Pure structure helpers only: no message construction, no injection, no wakeup
model.  Param entry layout is not decoded, so params are not represented.
"""

OBJMSG_FIELDS = {
    0x00: 'body_pointer',
    0x04: 'vtable_or_ref',
}
OBJMSG_BODY_FIELDS = {
    0x04: 'category_id',
    0x08: 'message_id',
    0x0C: 'param_container',
}
# RcvMsg outputs (UsbControl MsgReceiver).
UIPC_MESSAGE_OBJMSG_POINTER_OFFSET = 0x00
UIPC_MESSAGE_SOURCE_OFFSET = -0x04
# Decoded function addresses (Thumb) in libMWF / libUsbControl.
OBJMSG_GETMESSAGEID_VA = 0x20528
OBJMSG_SETCATEIDMSGID_VA = 0x20494
OBJMSG_CTOR_VA = 0x203AC
OBJMSGBODY_GETMESSAGEID_VA = 0x1F17E
OBJMSGBODY_GETCATEGORYID_VA = 0x1F176
MSG_RCVMSG_VA = 0xA9A8


def decode_objmsg_pointer(value, source=None):
    """Describe an ObjMsg pointer/source pair from an inbound UIPC payload."""
    return {
        'ok': bool(value),
        'objmsg_pointer': value,
        'source': source,
    }


def read_objmsg_fields(objmsg_bytes, body_bytes):
    """Read category/message id from constructed object/body byte buffers."""
    obj = bytes(objmsg_bytes)
    body = bytes(body_bytes)
    if len(obj) < 4 or len(body) < 0x0C:
        raise ValueError('ObjMsg/ObjMsgBody buffer too short')
    return {
        'body_pointer': int.from_bytes(obj[0x00:0x04], 'little'),
        'category_id': int.from_bytes(body[0x04:0x08], 'little'),
        'message_id': int.from_bytes(body[0x08:0x0C], 'little'),
    }


def describe_mwf_objmsg_layout():
    """Return the decoded ObjMsg/RcvMsg layout evidence (no injection)."""
    return {
        'objmsg_fields': dict(OBJMSG_FIELDS),
        'objmsg_body_fields': dict(OBJMSG_BODY_FIELDS),
        'uipc_message_objmsg_pointer_offset':
            UIPC_MESSAGE_OBJMSG_POINTER_OFFSET,
        'uipc_message_source_offset': UIPC_MESSAGE_SOURCE_OFFSET,
        'function_addresses': {
            'ObjMsg::GetMessageId': OBJMSG_GETMESSAGEID_VA,
            'ObjMsg::SetCateIdMsgId': OBJMSG_SETCATEIDMSGID_VA,
            'ObjMsg::ObjMsg': OBJMSG_CTOR_VA,
            'ObjMsgBody::GetMessageId': OBJMSGBODY_GETMESSAGEID_VA,
            'ObjMsgBody::GetCategoryId': OBJMSGBODY_GETCATEGORYID_VA,
            'MsgReceiver::RcvMsg': MSG_RCVMSG_VA,
        },
        'evidence': 'libMWF.so dynsym disassembly (GetMessageId 0x20528 reads '
                    'body+8; SetCateIdMsgId writes body+4/+8; ctor sets '
                    'obj+0 body=0) and libUsbControl RcvMsg (0xA9A8) outputs',
        'boundary': 'param entry layout (ObjMsg/ParamMap) is not decoded; no '
                    'inbound message construction or injection is modelled',
    }


# ---------------------------------------------------------------------------
# Param container layout (E0325): MWF::Param base and ParamMap entries.
# Param ctor (0x21718): [param+0]=0 (param id), [param+4]=vtable.
# ParamMap::Add (0x22B66): node [0]=param id, [key+] : param pointer is
# copied at node+4 (0x1C350 assign); ObjMsgBody+0xC is the ParamMap.
# ObjMsg::GetParam (0x205C0): body=obj[0]; lock; body->GetParam(id,0);
# unlock; return Param* (plain variant).  Derived Param types/data are not
# decoded, so no param value can be constructed yet.
# ---------------------------------------------------------------------------
PARAM_FIELDS = {
    0x00: 'param_id',
    0x04: 'vtable',
}
PARAMMAP_NODE_FIELDS = {
    0x00: 'param_id',
    0x04: 'param_object',
}
OBJMSG_PARAM_CONTAINER_OFFSET = 0x0C
PARAM_CTOR_VA = 0x21718
PARAMMAP_ADD_VA = 0x22B66
PARAMMAP_GET_VA = 0x22BD2
OBJMSG_GETPARAM_VA = 0x205C0


def describe_mwf_param_layout():
    """Return the decoded Param container layout (no value construction)."""
    return {
        'param_fields': dict(PARAM_FIELDS),
        'parammap_node_fields': dict(PARAMMAP_NODE_FIELDS),
        'objmsg_param_container_offset': OBJMSG_PARAM_CONTAINER_OFFSET,
        'function_addresses': {
            'Param::Param': PARAM_CTOR_VA,
            'ParamMap::Add': PARAMMAP_ADD_VA,
            'ParamMap::Get': PARAMMAP_GET_VA,
            'ObjMsg::GetParam': OBJMSG_GETPARAM_VA,
        },
        'evidence': 'libMWF.so disassembly: Param ctor stores [param+0]=0 and '
                    '[param+4]=vtable; ParamMap::Add node +0 id/+4 param; '
                    'ObjMsg::GetParam locks body and returns Param*',
        'boundary': 'Param derived type/data layout and vtable binding are not '
                    'decoded; no param (0x1006=0) can be constructed yet',
    }


# ---------------------------------------------------------------------------
# Typed Param and MessageSerializer header (E0326).
# ParamStd_Template<T>: +0 value, +4 vtable (GetValue 0x233A9 = [obj+0];
# typed ctor 0x23371/0x233CD sets vtable then value).  Param id lives in the
# ParamMap node (E0325), not in the Param object.
# Param::Type values decoded from dynsym mangling.
# MessageSerializer::encObjMsg (0x1F5BA) requires a buffer > 0xB and writes a
# 12-byte header (offsets +0/+4/+8 observed; exact field meaning pending full
# decode of the param loop and decObjMsg).
# ---------------------------------------------------------------------------
PARAM_TYPE_VALUES = {
    'bool': 1,
    'char': 2,
    'int8': 3,
    'uint8': 4,
    'int16': 5,
    'uint16': 6,
    'int32': 7,
    'uint32': 8,
    'pointer': 9,
    'char_array': 35,
    'int8_array': 36,
    'uint32_array': 38,
    'bool_array': 39,
    'int16_array': 42,
    'uint16_array': 43,
    'int32_array': 44,
}
PARAM_OBJECT_FIELDS = {
    0x00: 'value',
    0x04: 'vtable',
}
OBJMSG_SERIALIZED_HEADER_SIZE = 0x0C
OBJMSG_SERIALIZED_HEADER_FIELDS_PENDING = {
    0x00: 'category_or_length_hypothesis',
    0x04: 'message_id_or_length_hypothesis',
    0x08: 'param_count_hypothesis',
}
ENCOBJMSG_VA = 0x1F5BA
PARAMSTD_INT32_CTOR_VA = 0x23370
PARAMSTD_INT32_GETVALUE_VA = 0x233A8


def describe_mwf_typed_param_layout():
    """Return the decoded typed-Param/serializer-header evidence."""
    return {
        'param_object_fields': dict(PARAM_OBJECT_FIELDS),
        'param_type_values': dict(PARAM_TYPE_VALUES),
        'serialized_header_size': OBJMSG_SERIALIZED_HEADER_SIZE,
        'serialized_header_fields_pending':
            dict(OBJMSG_SERIALIZED_HEADER_FIELDS_PENDING),
        'function_addresses': {
            'ParamStd<int32>::ctor': PARAMSTD_INT32_CTOR_VA,
            'ParamStd<int32>::GetValue': PARAMSTD_INT32_GETVALUE_VA,
            'MessageSerializer::encObjMsg': ENCOBJMSG_VA,
        },
        'evidence': 'libMWF.so dynsym + disassembly: typed ctor installs vtable '
                    'and value; GetValue reads [obj+0]; encObjMsg requires a '
                    '>0xB buffer and writes a 12-byte header',
        'boundary': 'serializer param-entry encoding and decObjMsg are not '
                    'decoded; wire bytes are not constructed or injected',
    }


# ---------------------------------------------------------------------------
# Serialized ObjMsg wire format (E0327), decoded from libMWF
# MessageSerializer::decObjMsg (0x1FB8C) / encObjMsg (0x1F5BA):
#   header 12 B: +0 category id, +4 message id, +8 param count
#   param entry header 8 B: +0 param id, +4 type (Param::Type)
#   scalar value: 4 B (all scalar types occupy 4 bytes; u16 read as ldrh)
#   array value: 4 B element count + count bytes of data padded to 4
# ---------------------------------------------------------------------------
OBJMSG_WIRE_HEADER_FIELDS = {
    0x00: 'category_id',
    0x04: 'message_id',
    0x08: 'param_count',
}
OBJMSG_WIRE_PARAM_HEADER_FIELDS = {
    0x00: 'param_id',
    0x04: 'type',
}
OBJMSG_WIRE_PARAM_HEADER_SIZE = 0x08
OBJMSG_WIRE_SCALAR_SIZE = 0x04
DECDECOBJMSG_VA = 0x1FB8C
MSGUTIL_OBJMSG_HEADER_NOTE = (
    'UsbControl::RcvMsg returns payload[0] as an ObjMsg pointer (shared-pool '
    'object), so this serialized form documents the serializer side; the '
    'kernel/shared-pool ObjMsg construction path is not modelled')


def build_objmsg_wire(category_id, message_id, params=()):
    """Build the decoded serialized ObjMsg form (scalars only).

    ``params`` is an iterable of ``(param_id, param_type, int_value)``.
    Raises ValueError for unknown/non-scalar types; no implicit success on
    unsupported input.
    """
    scalar_types = {1, 2, 3, 4, 5, 6, 7, 8, 9}
    import struct as _struct
    out = bytearray(OBJMSG_WIRE_HEADER_FIELDS.__len__() * 4)
    _struct.pack_into('<III', out, 0, category_id, message_id, len(list(params)))
    for param_id, param_type, value in params:
        if param_type not in scalar_types:
            raise ValueError('unsupported non-scalar Param::Type %r' % (param_type,))
        entry = bytearray(OBJMSG_WIRE_PARAM_HEADER_SIZE + OBJMSG_WIRE_SCALAR_SIZE)
        _struct.pack_into('<IIi', entry, 0, param_id, param_type, int(value))
        out += entry
    return bytes(out)


def describe_mwf_wire_format():
    """Return the decoded serialized-ObjMsg wire format evidence."""
    return {
        'header_fields': dict(OBJMSG_WIRE_HEADER_FIELDS),
        'param_header_fields': dict(OBJMSG_WIRE_PARAM_HEADER_FIELDS),
        'param_header_size': OBJMSG_WIRE_PARAM_HEADER_SIZE,
        'scalar_size': OBJMSG_WIRE_SCALAR_SIZE,
        'function_addresses': {
            'MessageSerializer::decObjMsg': DECDECOBJMSG_VA,
            'MessageSerializer::encObjMsg': ENCOBJMSG_VA,
        },
        'receiver_note': MSGUTIL_OBJMSG_HEADER_NOTE,
        'evidence': 'decObjMsg/encObjMsg disassembly: header writes/reads at '
                    '+0 category, +4 messageId, +8 count; entry header '
                    '{id,type}; scalar 4 B; array {count,padded data}',
        'boundary': 'no kernel/shared-pool ObjMsg construction and no UIPC '
                    'message injection is modelled here',
    }


# ---------------------------------------------------------------------------
# Emulated inbound SETCONFIG ObjMsg image (E0328) - LABELLED EXPERIMENT.
# Builds the obj/body object layout from E0324/E0323 evidence so the emulator
# can deliver a kernel-style notification through the real UIPC queue path.
# E0336 adds the decoded MWF::Param container for Param 0x1006 = int32 0 so the
# FSM event-0x13 action's UFW::MsgUtil::GetInt32 no longer asserts.
# ---------------------------------------------------------------------------
import struct

SETCONFIG_CATEGORY = 0x6103
SETCONFIG_MESSAGE_ID = 0x0A4001
SETCONFIG_PARAM_ID = 0x1006

# ---------------------------------------------------------------------------
# E0336: MWF::Param object binding needed by UFW::MsgUtil::GetInt32.
#
# Live libUsbControl.so `_ZN3UFW7MsgUtil8GetInt32EPN3MWF6ObjMsgEj` (0xA3F4,
# 56 B) is:
#   0xA3F6 movs r2,#7                    ; Param::Type::int32
#   0xA3FA blx ObjMsg::GetParam(id, Param::Type)
#   0xA3FE cbnz r0,#0xA418               ; null -> assert
#   0xA400..0xA414 __assert_fail("ufw/MsgUtil/MsgUtil.cpp", 0x40 = line 64)
#   0xA418..0xA41C tail -> ParamStd<int,7>::GetValue (0x233A9: ldr r0,[r0])
# So `GetInt32` needs the *typed* GetParam to return non-null; only then does it
# read the value word.  The typed GetParam is:
#   ObjMsgBody::GetParam(id,type) (0x20303): ParamMap::Get(id) -> param*; if
#     type != 0 -> Param::GetType() and compare, null on mismatch.
#   Param::GetType (0x1F140): ldr r3,[param,#4]; ldr r0,[r3]
#     => param+4 is the MWF funcTable pointer and funcTable+0 is Param::Type.
#   ParamMap::Get(0x22BD3) -> ParamMap::GetParam(0x22BB7) also calls
#     Param::GetType for its type==10 unwrap check.
# Therefore a value-only Param is NOT sufficient: a real funcTable pointer with
# +0 == 7 is required.  Param is not a C++ RTTI class: each specialization has
# a 12-byte `funcTable` {+0 Param::Type, +4 virtual_Clear, +8 virtual_Clone}
# in libMWF .data.rel.ro (no _ZTV/_ZTI symbols for ParamStd<>).
#
# Live libMWF.so base in the e0673/e0684/e0686 checkpoints is 0x53660000
# (mapping table; ASLR disabled assumption).  Verified runtime bytes there:
#   0x536A067C ParamStd<int,7>::funcTable: 07 00 00 00 | 4F 2D 68 53 |
#                                          05 34 68 53   (type 7, +0x22D4F,
#                                          +0x23405)
#   0x536A0598 ObjMsg::funcTable:          29 00 00 00 | 71 03 68 53 |
#                                          45 04 68 53
# ObjMsg derives from Param: ObjMsg::ObjMsg() (0x203AD) calls Param ctor then
# stores &ObjMsg::funcTable at obj+4; obj+0 stays the body pointer.
# ---------------------------------------------------------------------------
LIVE_LIBMWF_BASE = 0x53660000
LIVE_LIBMWF_DATA_BASE = 0x536A0000  # e0686/e0684 mapping (base + 0x40000)
PARAM_TYPE_INT32 = 7

_OBJMSG_FUNCTABLE_OFFSET = 0x40598
_PARAMSTD_INT32_FUNCTABLE_OFFSET = 0x4067C
OBJMSG_FUNCTABLE_VA = LIVE_LIBMWF_BASE + _OBJMSG_FUNCTABLE_OFFSET
PARAMSTD_INT32_FUNCTABLE_VA = LIVE_LIBMWF_BASE + _PARAMSTD_INT32_FUNCTABLE_OFFSET
#: MWF funcTable object layout (12 bytes; no C++ RTTI vtable/typeinfo).
FUNCTABLE_FIELDS = {
    0x00: 'param_type',
    0x04: 'virtual_Clear',
    0x08: 'virtual_Clone',
}
#: MWF::Param object fields (E0325/E0326): value at +0, funcTable at +4.
PARAM_VALUE_OFFSET = 0x00
PARAM_FUNCTABLE_OFFSET = 0x04
#: MWF::ObjMsgBody fields (E0336 ctor 0x2027F): refcount/category/messageId/
#: ParamMap(16 B)/ObjLock; ObjMsg holds body at obj+0 and funcTable at obj+4.
OBJMSG_BODY_REFCOUNT_OFFSET = 0x00
OBJMSG_BODY_LOCK_OFFSET = 0x1C
#: MWF::ParamMap = MWF::ParamList (16 bytes): count, capacity, entry array*,
#: ParamListItem* chain.  Entry array entries are 8 B {u32 id, Param*}.
PARAMMAP_COUNT_OFFSET = 0x00
PARAMMAP_CAPACITY_OFFSET = 0x04
PARAMMAP_ARRAY_OFFSET = 0x08
PARAMMAP_ITEM_CHAIN_OFFSET = 0x0C
PARAMMAP_ENTRY_SIZE = 0x08
PARAMMAP_ENTRY_ID_OFFSET = 0x00
PARAMMAP_ENTRY_PARAM_OFFSET = 0x04
#: Image-relative placement used by the builder.  The array/Param are kept
#: beyond the zeroed ObjLock object (vptr + pthread_mutex_t, at body+0x1C, up
#: to ~0x40 bytes) so body lock/unlock cannot clobber them; the map itself sits
#: at ObjMsgBody+0xC (E0325).
OBJMSG_PARAM_IMAGE_ARRAY_OFFSET_IN_BODY = 0x48
OBJMSG_PARAM_IMAGE_PARAM_OFFSET_IN_BODY = 0x50
OBJMSG_PARAM_IMAGE_REQUIRED_BODY_SIZE = 0x58


def describe_mwf_param_object_binding():
    """Return the E0336 evidence for the Param object/vtable binding.

    ``vtable_required`` is True: the typed lookup dereferences param+4 and
    reads the MWF funcTable type word; a value-only Param fails the type gate.
    """
    return {
        'funcTable_fields': dict(FUNCTABLE_FIELDS),
        'param_value_offset': PARAM_VALUE_OFFSET,
        'param_functable_offset': PARAM_FUNCTABLE_OFFSET,
        'parammap_offsets': {
            'count': PARAMMAP_COUNT_OFFSET,
            'capacity': PARAMMAP_CAPACITY_OFFSET,
            'array': PARAMMAP_ARRAY_OFFSET,
            'item_chain': PARAMMAP_ITEM_CHAIN_OFFSET,
            'entry_size': PARAMMAP_ENTRY_SIZE,
            'entry_id': PARAMMAP_ENTRY_ID_OFFSET,
            'entry_param': PARAMMAP_ENTRY_PARAM_OFFSET,
        },
        'live_libmwf_base': LIVE_LIBMWF_BASE,
        'objmsg_func_table_va': OBJMSG_FUNCTABLE_VA,
        'paramstd_int32_func_table_va': PARAMSTD_INT32_FUNCTABLE_VA,
        'vtable_required': True,
        'function_addresses': {
            'UFW::MsgUtil::GetInt32': 0xA3F4,
            'ObjMsg::GetParam(id,type)': 0x205EB,
            'ObjMsgBody::GetParam(id,type)': 0x20303,
            'ParamMap::Get': 0x22BD3,
            'ParamMap::GetParam(Param*)': 0x22BB7,
            'Param::GetType': 0x1F140,
            'ParamStd<int,7>::GetValue': 0x233A9,
            'ObjMsg::ObjMsg()': 0x203AD,
            'ObjMsgBody::ObjMsgBody()': 0x2027F,
        },
        'instruction_evidence': (
            'Param::GetType 0x1F140: ldr r3,[param+4]; ldr r0,[r3] -> '
            'funcTable+0 is Param::Type; ObjMsgBody::GetParam 0x20303 calls '
            'it when type!=0; GetInt32 0xA3F6 passes r2=7 (int32) and asserts '
            'at MsgUtil.cpp:64 (0x40) when GetParam returns null'),
        'boundary': (
            'param=0x1006 int32 value 0 is constructible with the live libMWF '
            'funcTable VA; the ObjMsg/ParamMap teardown after ProcessMsg '
            '(free of the fabricated in-image array, operator delete of the '
            'pool ObjMsg) is still unmodelled'),
    }


def _validate_word(name, value):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError('%s must be an integer, got %r' % (name, value))
    if not 0 <= value <= 0xFFFFFFFF:
        raise ValueError('%s out of 32-bit range: %r' % (name, value))
    return value


def build_setconfig_objmsg_image(obj_address, allocation_size=0x80,
                                 body_offset=0x20, include_param=True,
                                 param_id=SETCONFIG_PARAM_ID, param_value=0,
                                 param_type=PARAM_TYPE_INT32,
                                 libmwf_base=LIVE_LIBMWF_BASE,
                                 objmsg_func_table_va=None):
    """Return the labelled emulated SETCONFIG ObjMsg image bytes.

    ``obj_address`` is the guest address where the image will be written; the
    object's first word points at the body at ``obj_address+body_offset``.
    With ``include_param`` (default) the body carries a valid MWF ParamMap with
    one ``ParamStd<int,7>`` entry (E0336): value at param+0 and the live
    ``ParamStd<int,7>::funcTable`` VA at param+4, so
    ``UFW::MsgUtil::GetInt32(msg, 0x1006)`` passes the typed lookup.  The
    ObjMsg funcTable is stored at obj+4 (ObjMsg derives from Param, E0336).

    Raises ValueError when the layout does not fit, the offsets are unaligned,
    the requested param type is not the decoded int32 type (7), the value is
    out of int32 range, or ``libmwf_base``/funcTable addresses are invalid.
    """
    obj_address = _validate_word('obj_address', obj_address)
    allocation_size = _validate_word('allocation_size', allocation_size)
    body_offset = _validate_word('body_offset', body_offset)
    if body_offset % 4:
        raise ValueError('body offset must be word aligned')
    required = body_offset + (OBJMSG_PARAM_IMAGE_REQUIRED_BODY_SIZE
                              if include_param else 0x10)
    if allocation_size < required:
        raise ValueError(
            'allocation too small: need 0x%x bytes, got 0x%x'
            % (required, allocation_size))
    if include_param:
        if param_type != PARAM_TYPE_INT32:
            raise ValueError(
                'only the decoded Param::Type int32 (7) is modelled, got %r'
                % (param_type,))
        param_id = _validate_word('param_id', param_id)
        if isinstance(param_value, bool) or not isinstance(param_value, int):
            raise ValueError('param_value must be an integer')
        if not -0x80000000 <= param_value <= 0x7FFFFFFF:
            raise ValueError('param_value is not int32: %r' % (param_value,))
        libmwf_base = _validate_word('libmwf_base', libmwf_base)
        if libmwf_base == 0:
            raise ValueError('libmwf_base is required for the Param funcTable VA')
        if libmwf_base % 4:
            raise ValueError('libmwf_base must be word aligned')
        func_table_va = _validate_word(
            'param funcTable VA', libmwf_base + _PARAMSTD_INT32_FUNCTABLE_OFFSET)
        if objmsg_func_table_va is None:
            objmsg_func_table_va = libmwf_base + _OBJMSG_FUNCTABLE_OFFSET
    elif objmsg_func_table_va is None:
        objmsg_func_table_va = 0
    objmsg_func_table_va = _validate_word('objmsg_func_table_va',
                                          objmsg_func_table_va)

    image = bytearray(allocation_size)
    body = body_offset
    struct.pack_into('<I', image, 0, obj_address + body)
    struct.pack_into('<I', image, 4, objmsg_func_table_va)
    struct.pack_into('<I', image, body + 0x04, SETCONFIG_CATEGORY)
    struct.pack_into('<I', image, body + 0x08, SETCONFIG_MESSAGE_ID)
    if include_param:
        parammap = body + OBJMSG_PARAM_CONTAINER_OFFSET
        array = body + OBJMSG_PARAM_IMAGE_ARRAY_OFFSET_IN_BODY
        param = body + OBJMSG_PARAM_IMAGE_PARAM_OFFSET_IN_BODY
        # ParamMap/ParamList: one entry; array/id/Param addresses are absolute.
        struct.pack_into('<I', image, parammap + PARAMMAP_COUNT_OFFSET, 1)
        struct.pack_into('<I', image, parammap + PARAMMAP_CAPACITY_OFFSET, 1)
        struct.pack_into('<I', image, parammap + PARAMMAP_ARRAY_OFFSET,
                         obj_address + array)
        struct.pack_into('<I', image, parammap + PARAMMAP_ITEM_CHAIN_OFFSET, 0)
        # Entry {param id, Param*}.
        struct.pack_into('<I', image, array + PARAMMAP_ENTRY_ID_OFFSET,
                         param_id)
        struct.pack_into('<I', image, array + PARAMMAP_ENTRY_PARAM_OFFSET,
                         obj_address + param)
        # ParamStd<int,7>: value and the live libMWF funcTable pointer.
        struct.pack_into('<i', image, param + PARAM_VALUE_OFFSET, param_value)
        struct.pack_into('<I', image, param + PARAM_FUNCTABLE_OFFSET,
                         func_table_va)
    return bytes(image)


def describe_setconfig_objmsg_param_layout(obj_address=0x579CE000,
                                           allocation_size=0x80,
                                           body_offset=0x20,
                                           libmwf_base=LIVE_LIBMWF_BASE):
    """Return the decoded offsets/addresses of the E0336 SETCONFIG Param image."""
    layout = {
        'allocation_size': allocation_size,
        'body_offset': body_offset,
        'objmsg': obj_address,
        'body': obj_address + body_offset,
        'objmsg_func_table_va': libmwf_base + _OBJMSG_FUNCTABLE_OFFSET,
        'param_functable_va': libmwf_base + _PARAMSTD_INT32_FUNCTABLE_OFFSET,
        'category': SETCONFIG_CATEGORY,
        'message_id': SETCONFIG_MESSAGE_ID,
        'param_id': SETCONFIG_PARAM_ID,
        'param_type': PARAM_TYPE_INT32,
        'param_value': 0,
        'parammap_offset': body_offset + OBJMSG_PARAM_CONTAINER_OFFSET,
        'array_offset': body_offset + OBJMSG_PARAM_IMAGE_ARRAY_OFFSET_IN_BODY,
        'param_offset': body_offset + OBJMSG_PARAM_IMAGE_PARAM_OFFSET_IN_BODY,
        'image_size_required': (body_offset +
                                OBJMSG_PARAM_IMAGE_REQUIRED_BODY_SIZE),
        'vtable_required': True,
        'evidence': 'E0336 (Param::GetType reads funcTable+0; funcTable VA '
                    'verified in live libMWF data at base+0x4067C)',
    }
    layout['array_address'] = obj_address + layout['array_offset']
    layout['param_address'] = obj_address + layout['param_offset']
    return layout
