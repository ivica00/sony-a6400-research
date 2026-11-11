import unittest

from src.a6400.execution.mwf_objmsg import (
    OBJMSG_FIELDS,
    OBJMSG_BODY_FIELDS,
    OBJMSG_GETMESSAGEID_VA,
    OBJMSG_SETCATEIDMSGID_VA,
    MSG_RCVMSG_VA,
    UIPC_MESSAGE_OBJMSG_POINTER_OFFSET,
    UIPC_MESSAGE_SOURCE_OFFSET,
    decode_objmsg_pointer,
    read_objmsg_fields,
    describe_mwf_objmsg_layout,
    PARAM_FIELDS,
    PARAMMAP_NODE_FIELDS,
    OBJMSG_PARAM_CONTAINER_OFFSET,
    describe_mwf_param_layout,
    PARAM_TYPE_VALUES,
    PARAM_OBJECT_FIELDS,
    OBJMSG_SERIALIZED_HEADER_SIZE,
    describe_mwf_typed_param_layout,
    OBJMSG_WIRE_HEADER_FIELDS,
    build_objmsg_wire,
    describe_mwf_wire_format,
)


class TestMwfObjMsgLayout(unittest.TestCase):
    """E0324: MWF::ObjMsg/ObjMsgBody layout decoded from libMWF."""

    def test_struct_offsets(self):
        self.assertEqual(OBJMSG_FIELDS[0x00], 'body_pointer')
        self.assertEqual(OBJMSG_BODY_FIELDS[0x04], 'category_id')
        self.assertEqual(OBJMSG_BODY_FIELDS[0x08], 'message_id')
        self.assertEqual(OBJMSG_BODY_FIELDS[0x0C], 'param_container')

    def test_read_objmsg_fields(self):
        obj = bytearray(8)
        obj[0:4] = (0x00579CE960).to_bytes(4, 'little')
        body = bytearray(0x10)
        body[0x04:0x08] = (0x6103).to_bytes(4, 'little')
        body[0x08:0x0C] = (0x0A4001).to_bytes(4, 'little')
        parsed = read_objmsg_fields(obj, body)
        self.assertEqual(parsed['body_pointer'], 0x579CE960)
        self.assertEqual(parsed['category_id'], 0x6103)
        self.assertEqual(parsed['message_id'], 0x0A4001)

    def test_short_buffers_rejected(self):
        with self.assertRaises(ValueError):
            read_objmsg_fields(b'\x00' * 3, b'\x00' * 0x10)
        with self.assertRaises(ValueError):
            read_objmsg_fields(b'\x00' * 8, b'\x00' * 0x0B)

    def test_pointer_and_report(self):
        decoded = decode_objmsg_pointer(0x12345678, 0x2E208)
        self.assertTrue(decoded['ok'])
        self.assertEqual(decoded['objmsg_pointer'], 0x12345678)
        self.assertEqual(decoded['source'], 0x2E208)
        self.assertEqual(UIPC_MESSAGE_OBJMSG_POINTER_OFFSET, 0)
        self.assertEqual(UIPC_MESSAGE_SOURCE_OFFSET, -4)
        report = describe_mwf_objmsg_layout()
        self.assertEqual(report['function_addresses']['ObjMsg::GetMessageId'],
                         OBJMSG_GETMESSAGEID_VA)
        self.assertEqual(report['function_addresses']['MsgReceiver::RcvMsg'],
                         MSG_RCVMSG_VA)
        self.assertIn('param', report['boundary'])


class TestMwfParamLayout(unittest.TestCase):
    """E0325: Param/ParamMap layout (structural only)."""

    def test_param_fields(self):
        self.assertEqual(PARAM_FIELDS[0x00], 'param_id')
        self.assertEqual(PARAM_FIELDS[0x04], 'vtable')
        self.assertEqual(PARAMMAP_NODE_FIELDS[0x00], 'param_id')
        self.assertEqual(PARAMMAP_NODE_FIELDS[0x04], 'param_object')
        self.assertEqual(OBJMSG_PARAM_CONTAINER_OFFSET, 0x0C)

    def test_report_and_boundary(self):
        report = describe_mwf_param_layout()
        self.assertEqual(report['function_addresses']['ObjMsg::GetParam'],
                         0x205C0)
        self.assertEqual(report['function_addresses']['ParamMap::Add'],
                         0x22B66)
        self.assertIn('no param', report['boundary'])


class TestMwfTypedParamLayout(unittest.TestCase):
    """E0326: typed Param + serializer header (structural only)."""

    def test_param_types(self):
        self.assertEqual(PARAM_TYPE_VALUES['bool'], 1)
        self.assertEqual(PARAM_TYPE_VALUES['char'], 2)
        self.assertEqual(PARAM_TYPE_VALUES['int32'], 7)
        self.assertEqual(PARAM_TYPE_VALUES['uint32'], 8)
        self.assertEqual(PARAM_TYPE_VALUES['int32_array'], 44)

    def test_param_object_and_header(self):
        self.assertEqual(PARAM_OBJECT_FIELDS[0x00], 'value')
        self.assertEqual(PARAM_OBJECT_FIELDS[0x04], 'vtable')
        self.assertEqual(OBJMSG_SERIALIZED_HEADER_SIZE, 0x0C)
        report = describe_mwf_typed_param_layout()
        self.assertEqual(report['function_addresses']['MessageSerializer::encObjMsg'],
                         0x1F5BA)
        self.assertIn('not decoded', report['boundary'])


class TestMwfWireFormat(unittest.TestCase):
    """E0327: serialized ObjMsg wire header/param encoding."""

    def test_setconfig_wire_bytes(self):
        wire = build_objmsg_wire(0x6103, 0x0A4001,
                                 [(0x1006, 7, 0)])
        self.assertEqual(len(wire), 0x0C + 0x08 + 0x04)
        self.assertEqual(int.from_bytes(wire[0:4], 'little'), 0x6103)
        self.assertEqual(int.from_bytes(wire[4:8], 'little'), 0x0A4001)
        self.assertEqual(int.from_bytes(wire[8:12], 'little'), 1)
        self.assertEqual(int.from_bytes(wire[12:16], 'little'), 0x1006)
        self.assertEqual(int.from_bytes(wire[16:20], 'little'), 7)
        self.assertEqual(int.from_bytes(wire[20:24], 'little'), 0)

    def test_empty_params_and_unsupported_type(self):
        wire = build_objmsg_wire(0x6103, 0x0A4000)
        self.assertEqual(len(wire), 0x0C)
        with self.assertRaises(ValueError):
            build_objmsg_wire(0x6103, 0x0A4001, [(0x1006, 35, 0)])

    def test_report(self):
        self.assertEqual(OBJMSG_WIRE_HEADER_FIELDS[0x04], 'message_id')
        report = describe_mwf_wire_format()
        self.assertEqual(report['function_addresses']
                         ['MessageSerializer::decObjMsg'], 0x1FB8C)
        self.assertEqual(report['param_header_size'], 8)
        self.assertIn('no kernel', report['boundary'])
