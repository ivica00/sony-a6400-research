import unittest

from src.a6400.execution.usb_video_contract import (
    ZVE10_USBG_VIDEO_SHA256,
    ZVE10_USBG_VIDEO_IOCTL_COMMANDS,
    ZVE10_USBG_VIDEO_CONTEXT_FIELDS,
    decode_usb_video_ioctl,
    USBG_VIDEO_USER_CALLBACK_SLOTS,
    USBG_VIDEO_DATA_INFO_FIELDS,
    USBG_VIDEO_WRITE_COMP_LIST_NODE,
    USBG_VIDEO_DMA_COMPLETION_FIELDS,
    USBG_VIDEO_PHYS_BUFFER_FIELDS,
    describe_usbg_video_buffer_contract,
    USB_VIDEO_PROBE_INFO_SIZE,
    USB_VIDEO_REGISTER_COMMAND,
    USB_VIDEO_UNREGISTER_LEGACY_COMMAND,
    USB_CMN_COPY_PROBE_INFO_SHA256,
    USB_CMN_CLEAR_PROBE_INFO_SHA256,
    parse_usb_video_probe_info,
    USB_VIDEO_DRIVER_NAME,
    USB_VIDEO_GADGETCORE_DRIVER_FIELDS,
    USB_VIDEO_CORE_CALLBACKS,
    USB_VIDEO_OPEN_CONTEXT_FIELDS,
    describe_usbg_video_register_contract,
    USB_VIDEO_TRANSFER_IOCTLS,
    USB_VIDEO_CONTEXT_COUNT_OFFSET,
    describe_usbg_video_transfer_contract,
    USB_VIDEO_EP_LIST_CONTEXT_FIELDS,
    USB_VIDEO_THIS_EX_EP_ID_OFFSET,
    describe_usbg_video_endpoint_list_contract,
    USB_VIDEO_PHYS_BUFFER_RPC,
    describe_usbg_video_phys_buffer_rpc,
    USB_VIDEO_CONTEXT_COUNT_WRITER,
    describe_usb_video_count_writer,
    USB_VIDEO_REQUEST_OBJECT,
    parse_usb_video_request_object,
    USB_VIDEO_DMA_INFO_OBJECT,
    parse_usb_video_dma_info_object,
    USB_VIDEO_BUFFER_TABLE_ENTRY_SIZE,
    USB_VIDEO_BUFFER_TABLE_MAX_ENTRIES,
    USB_VIDEO_BLOB_MAX_BYTES,
    USB_VIDEO_FRAME_SOURCE,
    parse_usb_video_buffer_table,
    parse_usb_video_blob,
    validate_usb_video_probe_info,
    build_usb_video_phys_buffer_alloc_message,
    build_usb_video_phys_buffer_free_message,
    parse_usb_video_phys_buffer_reply,
    usb_video_frame_source,
    describe_usbg_video_gap_contract,
)


class TestZve10UsbVideoContract(unittest.TestCase):
    """E0319: decoded ZV-E10 usbg_video ioctl/context constants."""

    def test_expected_commands_are_decoded(self):
        entry = decode_usb_video_ioctl(0x4038E000)
        self.assertTrue(entry['known'])
        self.assertEqual(entry['name'], 'uvc_request_write')
        self.assertEqual((entry['dir'], entry['type'], entry['nr'], entry['size']),
                         (3, 0xE0, 0, 0x38))
        entry = decode_usb_video_ioctl(0x4008F000)
        self.assertTrue(entry['known'])
        self.assertEqual((entry['dir'], entry['type'], entry['nr'], entry['size']),
                         (1, 0xF0, 0, 0x8))
        self.assertTrue(decode_usb_video_ioctl(0x0000E001)['known'])

    def test_unknown_command_is_generic_not_fabricated(self):
        entry = decode_usb_video_ioctl(0x4038E001)
        self.assertFalse(entry['known'])
        self.assertEqual(entry['type'], 0xE0)
        self.assertEqual(entry['nr'], 1)
        self.assertEqual(entry['size'], 0x38)
        self.assertIn('not a decoded', entry['evidence'])

    def test_context_offsets_and_hash(self):
        self.assertEqual(len(ZVE10_USBG_VIDEO_SHA256), 64)
        self.assertEqual(len(ZVE10_USBG_VIDEO_IOCTL_COMMANDS), 3)
        self.assertEqual(ZVE10_USBG_VIDEO_CONTEXT_FIELDS[0x24],
                         'uvc_request_buffer_pointer')
        for offset in (0x38, 0x3C, 0x3D, 0x40, 0x44, 0x48,
                       0x50, 0x54, 0x58, 0x5C, 0x60, 0x64, 0x68, 0x6C):
            self.assertIn(offset, ZVE10_USBG_VIDEO_CONTEXT_FIELDS)


class TestZve10UsbVideoBufferContract(unittest.TestCase):
    """E0319: observed usbg_video buffer/completion layout (structural only)."""

    def test_user_callback_slots(self):
        self.assertEqual(USBG_VIDEO_USER_CALLBACK_SLOTS,
                         {0: 0x04, 1: 0x08, 2: 0x0C, 3: 0x10,
                          4: 0x14, 5: 0x18, 6: 0x1C, 7: 0x20})

    def test_data_info_and_dma_fields(self):
        self.assertEqual(USBG_VIDEO_DATA_INFO_FIELDS[0x2C],
                         'completion_result_signed')
        self.assertEqual(USBG_VIDEO_DMA_COMPLETION_FIELDS[0x08],
                         'completion_callback_optional')
        self.assertEqual(USBG_VIDEO_WRITE_COMP_LIST_NODE,
                         {0x00: 'data_info_pointer', 0x04: 'link_a',
                          0x08: 'link_b'})

    def test_phys_buffer_offsets_and_report(self):
        for offset in (0x00, 0x02, 0x04, 0x0C, 0x10, 0x14, 0x16):
            self.assertIn(offset, USBG_VIDEO_PHYS_BUFFER_FIELDS)
        report = describe_usbg_video_buffer_contract()
        self.assertEqual(report['user_callback_slots'][7], 0x20)
        self.assertIn('hypothesis', report['evidence'])


class TestZve10UsbVideoProbeInfo(unittest.TestCase):
    """E0319 §8: register-time 56-byte probe-info ABI."""

    def test_parse_probe_info_fields(self):
        data = bytearray(USB_VIDEO_PROBE_INFO_SIZE)
        data[0x24:0x28] = (0x00010002).to_bytes(4, 'little')
        data[0x30:0x34] = (0x00020003).to_bytes(4, 'little')
        data[0x34:0x38] = (0x20).to_bytes(4, 'little')
        parsed = parse_usb_video_probe_info(bytes(data))
        self.assertEqual(parsed['buffer_table_pointer'], 0x00010002)
        self.assertEqual(parsed['blob_pointer'], 0x00020003)
        self.assertEqual(parsed['blob_length'], 0x20)
        self.assertEqual(len(parsed['raw']), 2 * USB_VIDEO_PROBE_INFO_SIZE)

    def test_short_block_rejected(self):
        with self.assertRaises(ValueError):
            parse_usb_video_probe_info(b'\x00' * 0x37)
        with self.assertRaises(ValueError):
            parse_usb_video_probe_info('not bytes')

    def test_commands_and_abi_hashes(self):
        self.assertEqual(USB_VIDEO_REGISTER_COMMAND, 0x4038E000)
        self.assertEqual(USB_VIDEO_UNREGISTER_LEGACY_COMMAND, 0x0000E001)
        self.assertEqual(len(USB_CMN_COPY_PROBE_INFO_SHA256), 64)
        self.assertEqual(len(USB_CMN_CLEAR_PROBE_INFO_SHA256), 64)


class TestZve10UsbVideoRegisterContract(unittest.TestCase):
    """E0319 §9: gadgetcore driver struct + open() buffer layout."""

    def test_driver_fields_and_name(self):
        self.assertEqual(USB_VIDEO_DRIVER_NAME, 'USB Gadget Video Device')
        self.assertEqual(USB_VIDEO_GADGETCORE_DRIVER_FIELDS[0x38],
                         'driver_name_pointer')
        self.assertEqual(USB_VIDEO_GADGETCORE_DRIVER_FIELDS[0x44],
                         'driver_entry_count')

    def test_core_callback_table(self):
        names = [row['name'] for row in USB_VIDEO_CORE_CALLBACKS.values()]
        self.assertEqual(names, ['core_cb_start', 'core_cb_stop',
                                 'core_cb_set_halt', 'core_cb_clear_halt',
                                 'core_cb_nop', 'core_cb_nop', 'core_cb_nop',
                                 'core_cb_class'])
        self.assertEqual(USB_VIDEO_CORE_CALLBACKS[0x50]['address'], 0x10F0)
        self.assertEqual(USB_VIDEO_CORE_CALLBACKS[0x6C]['size'], 708)

    def test_open_context_fields_and_report(self):
        for offset in (0x00, 0x04, 0x08, 0x0C, 0xA0, 0xA4, 0xAC, 0xB0):
            self.assertIn(offset, USB_VIDEO_OPEN_CONTEXT_FIELDS)
        report = describe_usbg_video_register_contract()
        self.assertEqual(report['driver_name'], 'USB Gadget Video Device')
        self.assertEqual(report['probe_info_size'], 0x38)
        self.assertIn('hypothesis', report['evidence'])


class TestZve10UsbVideoTransferContract(unittest.TestCase):
    """E0319 §10: 0xF0 transfer ioctl family."""

    def test_transfer_commands(self):
        self.assertEqual(sorted(USB_VIDEO_TRANSFER_IOCTLS),
                         [0xF001, 0xF002, 0xF006, 0x4008F000, 0x4008F003])
        self.assertEqual(USB_VIDEO_TRANSFER_IOCTLS[0x4008F000]['size'], 8)
        self.assertIn('context+0x14', USB_VIDEO_TRANSFER_IOCTLS[0x4008F000]['effect'])
        self.assertIn('context+0xCC',
                      USB_VIDEO_TRANSFER_IOCTLS[0x0000F006]['effect'])

    def test_count_offset_is_explicit_boundary(self):
        self.assertEqual(USB_VIDEO_CONTEXT_COUNT_OFFSET, 0x2D)
        report = describe_usbg_video_transfer_contract()
        self.assertEqual(report['count_writer'], 'unresolved')
        self.assertEqual(report['context_count_offset'], 0x2D)


class TestZve10UsbVideoEndpointListContract(unittest.TestCase):
    """E0319 §11: core_cb_start / usbg_cmn_make_ep_list layout."""

    def test_context_fields(self):
        self.assertEqual(USB_VIDEO_EP_LIST_CONTEXT_FIELDS[0xB2], 'ep_id_byte')
        self.assertEqual(USB_VIDEO_EP_LIST_CONTEXT_FIELDS[0xB4],
                         'ep_list_pointer')
        self.assertEqual(USB_VIDEO_EP_LIST_CONTEXT_FIELDS[0xB8],
                         'ep_count_byte')
        self.assertEqual(USB_VIDEO_THIS_EX_EP_ID_OFFSET, 0x9C)

    def test_report_and_boundary(self):
        report = describe_usbg_video_endpoint_list_contract()
        self.assertEqual(report['callback_va'], 0x10F0)
        self.assertEqual(report['make_ep_list_va'], 0x2BC)
        self.assertIn('unresolved', report['count_writer'])
        self.assertEqual(report['context_count_offset'], 0x2D)


class TestZve10UsbVideoPhysBufferRpc(unittest.TestCase):
    """E0319 §12: usb_sync_alloc/free_phys_buffer OSAL RPC ABI."""

    def test_rpc_constants(self):
        self.assertEqual(USB_VIDEO_PHYS_BUFFER_RPC['message_size'], 0x18)
        self.assertEqual(USB_VIDEO_PHYS_BUFFER_RPC['alloc_opcode'], 1)
        self.assertEqual(USB_VIDEO_PHYS_BUFFER_RPC['free_opcode'], 4)
        self.assertEqual(USB_VIDEO_PHYS_BUFFER_RPC['reply_status_offset'], 2)
        self.assertEqual(USB_VIDEO_PHYS_BUFFER_RPC['reply_physical_offset'], 0x10)
        self.assertEqual(USB_VIDEO_PHYS_BUFFER_RPC['dynamic_id_release'], 0x4A)

    def test_alloc_and_free_message_fields(self):
        alloc = USB_VIDEO_PHYS_BUFFER_RPC['alloc_message_fields']
        free = USB_VIDEO_PHYS_BUFFER_RPC['free_message_fields']
        self.assertIn(0x04, alloc)
        self.assertIn(0x0C, alloc)
        self.assertIn(0x02, free)
        self.assertEqual(free[0x16], 'flags_u16 (=2)')

    def test_report(self):
        report = describe_usbg_video_phys_buffer_rpc()
        self.assertEqual(report['functions']['usb_sync_alloc_phys_buffer']['va'],
                         0x2988)
        self.assertIn('0x2DA', report['open_usage'])
        self.assertIn('instruction-level', report['evidence'])


class TestZve10UsbVideoGapDecoders(unittest.TestCase):
    """E0319 gaps: count writer, 0xD0/0x24 objects, buffer table/blob."""

    def test_context_count_writer_is_explicit_boundary(self):
        self.assertEqual(USB_VIDEO_CONTEXT_COUNT_WRITER['context_offset'], 0x2D)
        self.assertEqual(USB_VIDEO_CONTEXT_COUNT_WRITER['writer'],
                         'unresolved_external')
        self.assertEqual(USB_VIDEO_CONTEXT_COUNT_WRITER['stores_in_module_text'], 0)
        report = describe_usb_video_count_writer()
        self.assertEqual(report['context_zeroed_bytes'], 0xC0)
        self.assertIn('usbg_cmn_copy_probe_info', report['note'])

    def test_request_object_parser_labels_every_word_unresolved(self):
        self.assertEqual(USB_VIDEO_REQUEST_OBJECT['context_offset'], 0xAC)
        self.assertEqual(USB_VIDEO_REQUEST_OBJECT['size'], 0xD0)
        parsed = parse_usb_video_request_object(b'\x00' * 0xD0)
        self.assertEqual(parsed['size'], 0xD0)
        self.assertEqual(parsed['known_fields'], {})
        self.assertEqual(len(parsed['words']), 0xD0 // 4)
        self.assertEqual(set(parsed['labels'].values()),
                         {'unresolved_word'})
        self.assertEqual(parsed['semantics'], 'unresolved')

    def test_request_object_rejects_short_or_non_bytes(self):
        with self.assertRaises(ValueError):
            parse_usb_video_request_object(b'\x00' * 0xCF)
        with self.assertRaises(ValueError):
            parse_usb_video_request_object([0] * 0xD0)

    def test_dma_info_object_fields(self):
        raw = bytearray(0x24)
        raw[0x00:0x04] = (1).to_bytes(4, 'little')
        raw[0x04:0x08] = (1).to_bytes(4, 'little')
        raw[0x08:0x0C] = (0x12345678).to_bytes(4, 'little')
        raw[0x0C:0x10] = (0xAABBCCDD).to_bytes(4, 'little')
        parsed = parse_usb_video_dma_info_object(bytes(raw))
        self.assertEqual(parsed['context_offset'], 0xB0)
        self.assertEqual(parsed['fields'][0x00]['label'], 'constant_1_observed')
        self.assertEqual(parsed['fields'][0x00]['value'], 1)
        self.assertEqual(parsed['fields'][0x08]['label'],
                         'adjusted_physical_address')
        self.assertEqual(parsed['fields'][0x08]['value'], 0x12345678)
        self.assertEqual(parsed['fields'][0x0C]['label'],
                         'unresolved_literal_word')
        with self.assertRaises(ValueError):
            parse_usb_video_dma_info_object(b'\x00' * 0x20)

    def test_buffer_table_parser_is_bounded_and_labelled(self):
        self.assertEqual(USB_VIDEO_BUFFER_TABLE_ENTRY_SIZE, 2)
        table = (0x1001).to_bytes(2, 'little') + (0x1002).to_bytes(2, 'little')
        parsed = parse_usb_video_buffer_table(table, expected_count=2)
        self.assertEqual(parsed['entries'], [0x1001, 0x1002])
        self.assertEqual(parsed['count_source'],
                         'context+0x2D (external writer unresolved)')
        self.assertIn('unresolved', parsed['entry_semantics'])
        empty = parse_usb_video_buffer_table(b'', expected_count=0)
        self.assertEqual(empty['entries'], [])

    def test_buffer_table_rejects_mismatch_and_oversize(self):
        with self.assertRaises(ValueError):
            parse_usb_video_buffer_table(b'\x00' * 3, expected_count=2)
        with self.assertRaises(ValueError):
            parse_usb_video_buffer_table(b'\x00' * 2, expected_count=-1)
        with self.assertRaises(ValueError):
            parse_usb_video_buffer_table(
                b'\x00' * (USB_VIDEO_BUFFER_TABLE_MAX_ENTRIES * 2 + 2),
                expected_count=USB_VIDEO_BUFFER_TABLE_MAX_ENTRIES + 1)

    def test_blob_parser_bounds(self):
        parsed = parse_usb_video_blob(b'\x01\x02\x03\x04')
        self.assertEqual(parsed['length'], 4)
        self.assertEqual(parsed['data_hex'], '01020304')
        self.assertIn('unresolved', parsed['semantics'])
        with self.assertRaises(ValueError):
            parse_usb_video_blob(b'\x00' * (USB_VIDEO_BLOB_MAX_BYTES + 1))
        with self.assertRaises(ValueError):
            parse_usb_video_blob('nope')

    def test_probe_info_validation_cross_checks(self):
        data = bytearray(USB_VIDEO_PROBE_INFO_SIZE)
        data[0x24:0x28] = (0x00010002).to_bytes(4, 'little')
        data[0x30:0x34] = (0).to_bytes(4, 'little')
        data[0x34:0x38] = (0).to_bytes(4, 'little')
        report = validate_usb_video_probe_info(bytes(data), buffer_count=3)
        self.assertEqual(report['expected_buffer_table_bytes'], 6)
        self.assertFalse(report['blob_present'])
        self.assertTrue(report['flags']['buffer_table_size_checked'])
        self.assertIn('external writer unresolved',
                      report['flags']['count_source'])
        self.assertIn('no register/commit success', report['semantics'])

    def test_probe_info_validation_refusals(self):
        data = bytearray(USB_VIDEO_PROBE_INFO_SIZE)
        data[0x34:0x38] = (1).to_bytes(4, 'little')
        with self.assertRaises(ValueError):
            validate_usb_video_probe_info(bytes(data))
        data[0x30:0x34] = (0x1000).to_bytes(4, 'little')
        data[0x34:0x38] = (USB_VIDEO_BLOB_MAX_BYTES + 1).to_bytes(4, 'little')
        with self.assertRaises(ValueError):
            validate_usb_video_probe_info(bytes(data))
        data[0x34:0x38] = (4).to_bytes(4, 'little')
        with self.assertRaises(ValueError):
            validate_usb_video_probe_info(
                bytes(data), buffer_count=USB_VIDEO_BUFFER_TABLE_MAX_ENTRIES + 1)


class TestZve10UsbVideoPhysBufferBuilders(unittest.TestCase):
    """E0319 §12: fail-closed alloc/free message builders and reply parser."""

    def test_alloc_message_layout(self):
        message = build_usb_video_phys_buffer_alloc_message(0x50E)
        self.assertEqual(len(message), 0x18)
        self.assertEqual(int.from_bytes(message[0x00:0x02], 'little'), 1)
        self.assertEqual(int.from_bytes(message[0x02:0x04], 'little'), 0)
        self.assertEqual(int.from_bytes(message[0x04:0x08], 'little'), 0x50E)
        self.assertEqual(int.from_bytes(message[0x0C:0x10], 'little'),
                         0xFFFFFFFF)
        self.assertEqual(int.from_bytes(message[0x16:0x18], 'little'), 1)

    def test_alloc_message_refusals(self):
        for size in (-1, 0x100000000, 'big', None):
            with self.assertRaises(ValueError):
                build_usb_video_phys_buffer_alloc_message(size)

    def test_free_message_layout_and_refusals(self):
        message = build_usb_video_phys_buffer_free_message(0x2DA)
        self.assertEqual(len(message), 0x18)
        self.assertEqual(int.from_bytes(message[0x00:0x02], 'little'), 4)
        self.assertEqual(int.from_bytes(message[0x02:0x04], 'little'), 0x2DA)
        self.assertEqual(int.from_bytes(message[0x16:0x18], 'little'), 2)
        for handle in (-1, 0x10000, 'x'):
            with self.assertRaises(ValueError):
                build_usb_video_phys_buffer_free_message(handle)

    def test_reply_parser(self):
        reply = bytearray(0x18)
        reply[0x02:0x04] = (0x1234).to_bytes(2, 'little')
        reply[0x04:0x06] = (0x50E).to_bytes(2, 'little')
        reply[0x10:0x14] = (0x20098000).to_bytes(4, 'little')
        reply[0x14:0x18] = (0x13E60000).to_bytes(4, 'little')
        parsed = parse_usb_video_phys_buffer_reply(bytes(reply))
        self.assertEqual(parsed['status_u16'], 0x1234)
        self.assertEqual(parsed['length_u16'], 0x50E)
        self.assertEqual(parsed['physical'], 0x20098000)
        self.assertEqual(parsed['virtual'], 0x13E60000)
        with self.assertRaises(ValueError):
            parse_usb_video_phys_buffer_reply(b'\x00' * 0x17)


class TestZve10UsbVideoFrameSourceAndGaps(unittest.TestCase):
    """E0319 gaps: JPEG/DMM frame source stays unresolved and fail-closed."""

    def test_frame_source_is_unresolved(self):
        self.assertEqual(USB_VIDEO_FRAME_SOURCE['status'], 'unresolved')
        for kind in ('jpeg', 'dmm'):
            info = usb_video_frame_source(kind)
            self.assertFalse(info['modelled'])
            self.assertEqual(info['status'], 'unresolved')
            self.assertIn('hypothesis', info['note'])

    def test_frame_source_unknown_raises(self):
        with self.assertRaises(ValueError):
            usb_video_frame_source('raw')

    def test_gap_report_lists_all_remaining_boundaries(self):
        report = describe_usbg_video_gap_contract()
        self.assertEqual(report['context_count_writer']['context_offset'], 0x2D)
        self.assertEqual(report['request_object']['size'], 0xD0)
        self.assertEqual(report['dma_info_object']['size'], 0x24)
        self.assertEqual(report['buffer_table']['entry_size'], 2)
        self.assertEqual(report['frame_source']['status'], 'unresolved')
        self.assertIn('unresolved', report['buffer_table']['semantics'])
        self.assertIn('fail closed', report['evidence'])
