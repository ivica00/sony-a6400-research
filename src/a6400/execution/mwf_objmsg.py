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
# The param map container is left zeroed (E0325 boundary); the ObjMsg vtable
# field is not dereferenced by GetMessageId.
# ---------------------------------------------------------------------------
import struct

SETCONFIG_CATEGORY = 0x6103
SETCONFIG_MESSAGE_ID = 0x0A4001
SETCONFIG_PARAM_ID = 0x1006


def build_setconfig_objmsg_image(obj_address, allocation_size=0x80,
                                 body_offset=0x20):
    """Return the labelled emulated ObjMsg image bytes for SETCONFIG.

    ``obj_address`` is the guest address where the image will be written;
    the object's first word points at the body at ``obj_address+body_offset``.
    Raises ValueError when the body does not fit or is unaligned.
    """
    if body_offset % 4:
        raise ValueError('body offset must be word aligned')
    if allocation_size < body_offset + 0x10:
        raise ValueError('allocation too small for ObjMsg body')
    image = bytearray(allocation_size)
    struct.pack_into('<I', image, 0, obj_address + body_offset)
    struct.pack_into('<I', image, body_offset + 4, SETCONFIG_CATEGORY)
    struct.pack_into('<I', image, body_offset + 8, SETCONFIG_MESSAGE_ID)
    return bytes(image)
