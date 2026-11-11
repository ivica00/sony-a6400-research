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
    LIVE_LIBMWF_BASE,
    LIVE_LIBMWF_DATA_BASE,
    OBJMSG_FUNCTABLE_VA,
    PARAMSTD_INT32_FUNCTABLE_VA,
    PARAM_TYPE_INT32,
    FUNCTABLE_FIELDS,
    PARAM_VALUE_OFFSET,
    PARAM_FUNCTABLE_OFFSET,
    PARAMMAP_COUNT_OFFSET,
    PARAMMAP_ARRAY_OFFSET,
    PARAMMAP_ENTRY_SIZE,
    PARAMMAP_ENTRY_ID_OFFSET,
    PARAMMAP_ENTRY_PARAM_OFFSET,
    OBJMSG_PARAM_IMAGE_ARRAY_OFFSET_IN_BODY,
    OBJMSG_PARAM_IMAGE_PARAM_OFFSET_IN_BODY,
    build_setconfig_objmsg_image,
    describe_setconfig_objmsg_param_layout,
    describe_mwf_param_object_binding,
    SETCONFIG_CATEGORY,
    SETCONFIG_MESSAGE_ID,
    SETCONFIG_PARAM_ID,
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


class TestMwfParamObjectBinding(unittest.TestCase):
    """E0336: Param object funcTable binding required by MsgUtil::GetInt32."""

    def test_func_table_constants(self):
        self.assertEqual(LIVE_LIBMWF_BASE, 0x53660000)
        self.assertEqual(LIVE_LIBMWF_DATA_BASE, 0x536A0000)
        self.assertEqual(PARAMSTD_INT32_FUNCTABLE_VA, 0x536A067C)
        self.assertEqual(OBJMSG_FUNCTABLE_VA, 0x536A0598)
        self.assertEqual(PARAM_TYPE_INT32, 7)
        self.assertEqual(FUNCTABLE_FIELDS,
                         {0x00: 'param_type',
                          0x04: 'virtual_Clear',
                          0x08: 'virtual_Clone'})

    def test_vtable_required_finding(self):
        report = describe_mwf_param_object_binding()
        self.assertTrue(report['vtable_required'])
        self.assertEqual(report['param_value_offset'], 0)
        self.assertEqual(report['param_functable_offset'], 4)
        self.assertEqual(report['function_addresses']
                         ['UFW::MsgUtil::GetInt32'], 0xA3F4)
        self.assertEqual(report['function_addresses']
                         ['Param::GetType'], 0x1F140)
        self.assertIn('funcTable+0', report['instruction_evidence'])
        self.assertIn('teardown', report['boundary'])

    def test_layout_offsets(self):
        self.assertEqual(PARAMMAP_COUNT_OFFSET, 0)
        self.assertEqual(PARAMMAP_ARRAY_OFFSET, 8)
        self.assertEqual(PARAMMAP_ENTRY_SIZE, 8)
        self.assertEqual(PARAMMAP_ENTRY_ID_OFFSET, 0)
        self.assertEqual(PARAMMAP_ENTRY_PARAM_OFFSET, 4)
        layout = describe_setconfig_objmsg_param_layout()
        self.assertEqual(layout['parammap_offset'], 0x20 + 0x0C)
        self.assertEqual(layout['array_offset'],
                         0x20 + OBJMSG_PARAM_IMAGE_ARRAY_OFFSET_IN_BODY)
        self.assertEqual(layout['param_offset'],
                         0x20 + OBJMSG_PARAM_IMAGE_PARAM_OFFSET_IN_BODY)
        self.assertEqual(layout['param_id'], SETCONFIG_PARAM_ID)
        self.assertEqual(layout['param_type'], 7)
        self.assertTrue(layout['vtable_required'])
        self.assertEqual(len(layout['evidence']) > 0, True)


class TestSetconfigObjMsgImageWithParam(unittest.TestCase):
    """E0336: SETCONFIG ObjMsg image carrying Param 0x1006 = int32 0."""

    def _read_u32(self, image, offset):
        return int.from_bytes(image[offset:offset + 4], 'little')

    def test_image_contains_decoded_param(self):
        obj = 0x579CE000
        image = build_setconfig_objmsg_image(obj)
        self.assertEqual(len(image), 0x80)
        body = 0x20
        parammap = body + OBJMSG_PARAM_CONTAINER_OFFSET
        array = body + OBJMSG_PARAM_IMAGE_ARRAY_OFFSET_IN_BODY
        param = body + OBJMSG_PARAM_IMAGE_PARAM_OFFSET_IN_BODY
        # ObjMsg: body pointer at +0, real ObjMsg funcTable at +4.
        self.assertEqual(self._read_u32(image, 0), obj + body)
        self.assertEqual(self._read_u32(image, 4), OBJMSG_FUNCTABLE_VA)
        # body category/message id unchanged.
        self.assertEqual(self._read_u32(image, body + 4), SETCONFIG_CATEGORY)
        self.assertEqual(self._read_u32(image, body + 8),
                         SETCONFIG_MESSAGE_ID)
        # ParamMap: one decoded entry with absolute array/Param addresses.
        self.assertEqual(self._read_u32(image, parammap + 0), 1)
        self.assertEqual(self._read_u32(image, parammap + 8), obj + array)
        self.assertEqual(self._read_u32(image, array), SETCONFIG_PARAM_ID)
        self.assertEqual(self._read_u32(image, array + 4), obj + param)
        # ParamStd<int,7>: value 0 and the live libMWF funcTable VA.
        self.assertEqual(self._read_u32(image, param), 0)
        self.assertEqual(self._read_u32(image, param + 4),
                         PARAMSTD_INT32_FUNCTABLE_VA)

    def test_param_entry_values(self):
        obj = 0x579CE000
        image = build_setconfig_objmsg_image(obj, param_value=0)
        layout = describe_setconfig_objmsg_param_layout(obj)
        param = layout['param_offset']
        self.assertEqual(self._read_u32(image, param + PARAM_VALUE_OFFSET), 0)
        self.assertEqual(self._read_u32(image, param + PARAM_FUNCTABLE_OFFSET),
                         PARAMSTD_INT32_FUNCTABLE_VA)

    def test_include_param_false_keeps_zeroed_map(self):
        obj = 0x579CE000
        image = build_setconfig_objmsg_image(obj, include_param=False)
        body = 0x20
        parammap = body + OBJMSG_PARAM_CONTAINER_OFFSET
        self.assertEqual(self._read_u32(image, parammap), 0)
        self.assertEqual(self._read_u32(image, 4), 0)

    def test_custom_libmwf_base(self):
        base = 0x60000000
        image = build_setconfig_objmsg_image(0x579CE000, libmwf_base=base)
        layout = describe_setconfig_objmsg_param_layout(0x579CE000,
                                                        libmwf_base=base)
        self.assertEqual(self._read_u32(image, layout['param_offset'] + 4),
                         base + PARAMSTD_INT32_FUNCTABLE_VA - LIVE_LIBMWF_BASE)
        self.assertEqual(self._read_u32(image, 4),
                         base + OBJMSG_FUNCTABLE_VA - LIVE_LIBMWF_BASE)

    def test_unknown_param_type_refused(self):
        with self.assertRaises(ValueError):
            build_setconfig_objmsg_image(0x579CE000, param_type=8)
        with self.assertRaises(ValueError):
            build_setconfig_objmsg_image(0x579CE000, param_type='int32')

    def test_layout_refusals(self):
        with self.assertRaises(ValueError):
            build_setconfig_objmsg_image(0x579CE000, allocation_size=0x6F)
        with self.assertRaises(ValueError):
            build_setconfig_objmsg_image(0x579CE000, body_offset=0x11)
        with self.assertRaises(ValueError):
            build_setconfig_objmsg_image(0x579CE000, body_offset=0x30,
                                         allocation_size=0x7F)
        with self.assertRaises(ValueError):
            build_setconfig_objmsg_image(0x579CE000, libmwf_base=0)
        with self.assertRaises(ValueError):
            build_setconfig_objmsg_image(0x579CE000, libmwf_base=-4)
        with self.assertRaises(ValueError):
            build_setconfig_objmsg_image(0x579CE000, param_type=7,
                                         param_value=1 << 31)
        with self.assertRaises(ValueError):
            build_setconfig_objmsg_image(0x579CE000, param_id=-1)

    def test_backward_compatible_layout(self):
        obj = 0x579CE000
        image = build_setconfig_objmsg_image(obj)
        self.assertEqual(len(image), 0x80)
        self.assertEqual(int.from_bytes(image[0:4], 'little'), obj + 0x20)
        self.assertEqual(SETCONFIG_CATEGORY, 0x6103)
        self.assertEqual(SETCONFIG_MESSAGE_ID, 0x0A4001)
        self.assertEqual(SETCONFIG_PARAM_ID, 0x1006)


if __name__ == '__main__':
    unittest.main()
