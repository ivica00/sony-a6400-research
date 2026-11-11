import unittest

from src.a6400.execution.usb_sync_callback import (
    ADJ_PACKET_SIZE,
    ADJ_PACKET_ID,
    ADJ_PACKET_ID_OFFSET,
    ADJ_RESULT_ERROR,
    ADJ_RESULT_ID_MISMATCH,
    ADJ_RESULT_NAMES,
    ADJ_RESULT_OK,
    ADJ_SUBCOMMANDS,
    ADJ_DATA_OFFSET,
    ADJ_FUNCTION_OFFSETS,
    ADJ_PHASES,
    H4109_CALLBACK_OFFSET,
    H4109_CALLBACK_SYMBOL,
    H4109_CALLBACK_VA,
    H4109_HANDLE,
    H4109_PACKET_ID,
    H4109_QUEUE,
    H4109_USER_DATA,
    H4110_CALLBACK_OFFSET,
    H4110_CALLBACK_SYMBOL,
    H4110_CALLBACK_VA,
    H4110_HANDLE,
    H4110_QUEUE,
    H4110_USER_DATA,
    INPUT_GET_MIN_MESSAGE_SIZE,
    KEY_PHYS_TO_LOCAL,
    LIVE_LIBUSBCONTROL_BASE,
    LIVE_LIBUSBCONTROL_DATA_BASE,
    LIVE_LIBUSBCONTROL_SIZE,
    SYNC_CALLBACK_ABI,
    SYNC_CALLBACK_REGISTRATIONS,
    USB_CONTROL_LOCAL_SYNC_QUEUE,
    build_adj_process_start_request,
    build_adj_request,
    decode_adj_request_packet,
    decode_adj_response_packet,
    decode_input_get_request,
    decode_input_get_response,
    describe_downstream_path,
    describe_sync_callback,
    describe_sync_callback_packet_format,
    phys_key_to_local_code,
)


class TestSyncCallbackIdentity(unittest.TestCase):
    """E0333: callback VAs are the live load base plus the dynsym offsets."""

    def test_load_base_and_offsets(self):
        self.assertEqual(LIVE_LIBUSBCONTROL_BASE, 0x56440000)
        self.assertEqual(H4109_CALLBACK_VA - LIVE_LIBUSBCONTROL_BASE,
                         H4109_CALLBACK_OFFSET)
        self.assertEqual(H4110_CALLBACK_VA - LIVE_LIBUSBCONTROL_BASE,
                         H4110_CALLBACK_OFFSET)

    def test_h4109_identity(self):
        self.assertEqual(H4109_HANDLE, 4109)
        self.assertEqual(H4109_QUEUE, 0x00CA0288)
        self.assertEqual(H4109_CALLBACK_OFFSET, 0xB0DF)
        self.assertEqual(H4109_CALLBACK_SYMBOL,
                         '_ZN3UFW7AdjBase14funcOsalSyncCbEPvS1_')
        self.assertEqual(H4109_USER_DATA, 0x5645EA98)

    def test_h4110_identity(self):
        self.assertEqual(H4110_HANDLE, 4110)
        self.assertEqual(H4110_QUEUE, 0x00CA01A4)
        self.assertEqual(H4110_CALLBACK_OFFSET, 0x12A87)
        self.assertEqual(H4110_CALLBACK_SYMBOL,
                         '_ZN10UsbControl14funcInputGetCbEPvS0_')
        self.assertEqual(H4110_USER_DATA, 0x2E1B0)
        # 0x2E1B0 is the heap UsbControl singleton, not a library address.
        self.assertLess(H4110_USER_DATA, LIVE_LIBUSBCONTROL_BASE)

    def test_queue_lane_bit(self):
        # Both decoded queues are kernel/UIPC queues: bit 15 of the low
        # halfword is clear.  The local 0x00CA8192 registration has it set.
        self.assertEqual(H4109_QUEUE & 0x8000, 0)
        self.assertEqual(H4110_QUEUE & 0x8000, 0)
        self.assertEqual(USB_CONTROL_LOCAL_SYNC_QUEUE & 0x8000, 0x8000)

    def test_describe_unknown_handle_is_rejected(self):
        with self.assertRaises(ValueError):
            describe_sync_callback(9999)
        with self.assertRaises(ValueError):
            describe_sync_callback('4109')
        with self.assertRaises(ValueError):
            describe_downstream_path(9999)

    def test_describe_both_handles(self):
        h4109 = describe_sync_callback(4109)
        h4110 = describe_sync_callback(4110)
        self.assertEqual(h4109['queue'], H4109_QUEUE)
        self.assertIn('UsbAdjCmd', h4109['user_data_kind'])
        self.assertIn('funcInputGetCb', h4110['callback_demangled'])
        self.assertIn('UsbControl', h4110['user_data_kind'])
        self.assertIn('kernel', h4109['queue_lane'])
        self.assertEqual(set(SYNC_CALLBACK_REGISTRATIONS), {4109, 4110})
        h4109['queue'] = 0  # returned dicts are copies
        self.assertEqual(SYNC_CALLBACK_REGISTRATIONS[4109]['queue'], H4109_QUEUE)

    def test_abi_and_evidence_constants(self):
        self.assertEqual(SYNC_CALLBACK_ABI['arg0'], 'message_payload')
        self.assertEqual(SYNC_CALLBACK_ABI['arg1'], 'registered_user_data')
        self.assertEqual(SYNC_CALLBACK_ABI['payload_from_message_head'], 0x0C)
        self.assertEqual(LIVE_LIBUSBCONTROL_SIZE, 94176)
        self.assertGreater(LIVE_LIBUSBCONTROL_DATA_BASE,
                           LIVE_LIBUSBCONTROL_BASE)

    def test_function_offsets(self):
        self.assertEqual(ADJ_FUNCTION_OFFSETS['UFW::AdjBase::funcOsalSyncCb'],
                         H4109_CALLBACK_OFFSET)
        self.assertEqual(
            ADJ_FUNCTION_OFFSETS['UsbControl::PreInit'], 0x1045D)


class TestAdjRequestPacket(unittest.TestCase):
    """E0333: 0x140-byte UsbAdjCmd OsalRequestPacket layout."""

    def test_constants(self):
        self.assertEqual(ADJ_PACKET_SIZE, 0x140)
        self.assertEqual(ADJ_PACKET_ID, 0x0701)
        self.assertEqual(ADJ_PACKET_ID_OFFSET, 0x18)
        self.assertEqual(sorted(ADJ_PHASES), [0x01, 0x04, 0x10])
        self.assertEqual(sorted(ADJ_SUBCOMMANDS), list(range(1, 8)))
        self.assertEqual(ADJ_SUBCOMMANDS[3]['name'],
                         'usb_get_port_process_start')
        self.assertEqual(ADJ_SUBCOMMANDS[7]['name'],
                         'usb_buspower_supply_control_process_start')

    def test_build_and_decode_process_start(self):
        packet = build_adj_process_start_request(3, argument=0)
        self.assertEqual(len(packet), ADJ_PACKET_SIZE)
        self.assertEqual(packet[0], 0x01)
        decoded = decode_adj_request_packet(packet)
        self.assertEqual(decoded['phase_name'], 'process_start')
        self.assertEqual(decoded['packet_id'], 0x0701)
        self.assertTrue(decoded['id_matches'])
        self.assertEqual(decoded['subcommand'], 3)
        self.assertEqual(decoded['handler']['name'],
                         'usb_get_port_process_start')
        self.assertEqual(decoded['response_type'], 0x08)
        self.assertEqual(decoded['response_value_offset'], 0x0C)
        self.assertEqual(decoded['response_payload_offset'], 0x10)

    def test_build_carries_payload_at_decoded_offset(self):
        packet = build_adj_process_start_request(6, argument=0,
                                                 payload=b'\x11' * 0x41)
        self.assertEqual(packet[ADJ_DATA_OFFSET:ADJ_DATA_OFFSET + 0x41],
                         b'\x11' * 0x41)
        decoded = decode_adj_request_packet(packet)
        self.assertEqual(decoded['subcommand_argument'], 0)
        self.assertEqual(decoded['handler']['name'],
                         'write_customer_hash256_process_start')

    def test_build_refuses_bad_input(self):
        with self.assertRaises(ValueError):
            build_adj_process_start_request(0)  # subcommands start at 1
        with self.assertRaises(ValueError):
            build_adj_process_start_request(8)
        with self.assertRaises(ValueError):
            build_adj_process_start_request(1, argument=0x100)
        with self.assertRaises(ValueError):
            build_adj_request(0x02)  # unknown phase
        with self.assertRaises(ValueError):
            build_adj_request(0x04, subcommand=1)  # no dispatch on phase 4
        with self.assertRaises(ValueError):
            build_adj_process_start_request(1, payload=b'\x00' * 0x200)
        with self.assertRaises(ValueError):
            build_adj_process_start_request(1, payload=b'\x00',
                                            payload_offset=ADJ_PACKET_SIZE)

    def test_decode_refuses_short_packet(self):
        with self.assertRaises(ValueError):
            decode_adj_request_packet(bytes(ADJ_PACKET_SIZE - 1))

    def test_decode_refuses_unknown_phase(self):
        packet = bytearray(ADJ_PACKET_SIZE)
        packet[0] = 0x02
        with self.assertRaises(ValueError):
            decode_adj_request_packet(packet)

    def test_decode_refuses_unknown_subcommand(self):
        packet = bytearray(build_adj_request(0x01, subcommand=1))
        packet[0x1A] = 0x09
        packet[0x1B] = 0x00
        with self.assertRaises(ValueError):
            decode_adj_request_packet(packet)

    def test_mismatched_packet_id_is_reported(self):
        packet = bytearray(build_adj_process_start_request(1))
        packet[0x18] = 0x00
        packet[0x19] = 0x00
        decoded = decode_adj_request_packet(packet)
        self.assertFalse(decoded['id_matches'])
        self.assertEqual(decoded['expected_packet_id'], 0x0701)

    def test_phase4_and_phase0x10_have_no_handler(self):
        for phase, response_type in ((0x04, 0x08), (0x10, 0x20)):
            packet = build_adj_request(phase)
            decoded = decode_adj_request_packet(packet)
            self.assertIsNone(decoded['handler'])
            self.assertIsNone(decoded['subcommand'])
            self.assertEqual(decoded['response_type'], response_type)

    def test_decode_response(self):
        packet = bytearray(build_adj_process_start_request(3))
        packet[0] = 0x08
        packet[1] = ADJ_RESULT_OK
        decoded = decode_adj_response_packet(packet)
        self.assertEqual(decoded['result_name'], 'ok')
        self.assertEqual(decoded['response_type'], 0x08)
        self.assertEqual(len(decoded['response_payload']), 0x130)

        packet[1] = ADJ_RESULT_ID_MISMATCH
        self.assertEqual(decode_adj_response_packet(packet)['result_name'],
                         'rejected')
        packet[1] = ADJ_RESULT_ERROR
        self.assertEqual(decode_adj_response_packet(packet)['result_name'],
                         'error')

    def test_decode_response_refusals(self):
        with self.assertRaises(ValueError):
            decode_adj_response_packet(bytes(ADJ_PACKET_SIZE - 1))
        packet = bytearray(ADJ_PACKET_SIZE)
        packet[1] = 0x7F
        with self.assertRaises(ValueError):
            decode_adj_response_packet(packet)
        packet = bytearray(ADJ_PACKET_SIZE)
        packet[0] = 0x99
        with self.assertRaises(ValueError):
            decode_adj_response_packet(packet)

    def test_result_names_cover_decoded_codes(self):
        self.assertEqual(set(ADJ_RESULT_NAMES),
                         {0x80, 0x01, 0x81, 0x82})


class TestInputGetPacket(unittest.TestCase):
    """E0333: UsbControl::funcInputGetCb input-get sync message."""

    def test_constants(self):
        self.assertEqual(INPUT_GET_MIN_MESSAGE_SIZE, 0x14)
        self.assertEqual(KEY_PHYS_TO_LOCAL,
                         {0x07000001: 1, 0x07000002: 2,
                          0x07000003: 3, 0x07000004: 4})

    def test_phys_key_mapping(self):
        self.assertEqual(phys_key_to_local_code(0x07000002), 2)
        self.assertEqual(phys_key_to_local_code(0x07000004), 4)
        with self.assertRaises(ValueError):
            phys_key_to_local_code(0x07000005)
        with self.assertRaises(ValueError):
            phys_key_to_local_code(0x1234)

    def test_decode_accepted_request(self):
        message = bytearray(INPUT_GET_MIN_MESSAGE_SIZE)
        message[0x04:0x08] = (0x07000003).to_bytes(4, 'little')
        decoded = decode_input_get_request(message)
        self.assertTrue(decoded['accepted'])
        self.assertEqual(decoded['local_code'], 3)
        self.assertEqual(decoded['jack_status_offset'], 0xD4)
        self.assertIsNone(decoded['rejection'])

    def test_decode_word0_rejection(self):
        message = bytearray(INPUT_GET_MIN_MESSAGE_SIZE)
        message[0x00:0x04] = (1).to_bytes(4, 'little')
        message[0x04:0x08] = (0x07000001).to_bytes(4, 'little')
        decoded = decode_input_get_request(message)
        self.assertFalse(decoded['accepted'])
        self.assertEqual(decoded['rejection'], 'word0_not_zero')

    def test_decode_unmapped_phys_code_rejection(self):
        message = bytearray(INPUT_GET_MIN_MESSAGE_SIZE)
        message[0x04:0x08] = (0x07000009).to_bytes(4, 'little')
        decoded = decode_input_get_request(message)
        self.assertFalse(decoded['accepted'])
        self.assertEqual(decoded['rejection'], 'phys_code_not_mapped')

    def test_decode_refuses_short_message(self):
        with self.assertRaises(ValueError):
            decode_input_get_request(bytes(INPUT_GET_MIN_MESSAGE_SIZE - 1))
        with self.assertRaises(ValueError):
            decode_input_get_response(bytes(INPUT_GET_MIN_MESSAGE_SIZE - 1))

    def test_decode_response_status(self):
        message = bytearray(INPUT_GET_MIN_MESSAGE_SIZE)
        message[0x0C:0x10] = (2).to_bytes(4, 'little')
        self.assertEqual(decode_input_get_response(message)['status'], 2)


class TestDownstreamAndReport(unittest.TestCase):
    """E0333: decoded downstream path evidence (no ObjMsg construction)."""

    def test_h4109_downstream_has_no_objmsg_post(self):
        path = describe_downstream_path(4109)
        downstream = path['downstream']
        self.assertTrue(downstream['no_objmsg'])
        self.assertTrue(downstream['no_msgsender'])
        self.assertIn('synchronous in-place response', downstream['post'])
        self.assertEqual(path['registration']['queue'], H4109_QUEUE)

    def test_h4110_downstream_writes_status(self):
        downstream = describe_downstream_path(4110)['downstream']
        self.assertIn('message+0xC', downstream['post'])
        self.assertTrue(downstream['no_objmsg'])

    def test_local_queue_registration_forwards_to_preprocess(self):
        all_paths = describe_downstream_path()
        local = all_paths['usb_control_local_0x00CA8192']
        self.assertFalse(local['no_objmsg'])
        self.assertIn('preProcess', local['post'])

    def test_report_is_complete(self):
        report = describe_sync_callback_packet_format()
        self.assertEqual(report['live_libusbcontrol_size'], 94176)
        self.assertEqual(set(report['registrations']), {'4109', '4110'})
        self.assertEqual(report['adj_packet']['packet_id'], 0x0701)
        self.assertEqual(report['adj_packet']['size'], 0x140)
        self.assertEqual(report['input_get_packet']['min_size'], 0x14)
        self.assertIn('sync_callback_packet_format', report['boundary'])


if __name__ == '__main__':
    unittest.main()
