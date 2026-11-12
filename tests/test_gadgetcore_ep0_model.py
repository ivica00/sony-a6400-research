import struct
import unittest

from src.a6400 import usb_debug_descriptors as descriptors
from src.a6400.debug import gadgetcore_ep0_model as model


def msc_config():
    config = struct.pack('<BBHBBBBB', 9, 2, 32, 1, 1, 0x80, 250, 0)
    interface = struct.pack('<BBBBBBBBB', 9, 4, 0, 0, 2, 8, 6, 0x50, 0)
    ep_in = struct.pack('<BBBBHB', 7, 5, 0x81, 2, 512, 0)
    ep_out = struct.pack('<BBBBHB', 7, 5, 0x02, 2, 512, 0)
    return config + interface + ep_in + ep_out


class DescriptorModelTests(unittest.TestCase):
    def setUp(self):
        self.model = model.DescriptorModel(msc_config(), interface_number=1)

    def test_device_descriptor_carries_bcdusb_0210(self):
        payload = self.model.handle_setup(bytes([0x80, 0x06, 0x00, 0x01, 0, 0, 18, 0]))
        self.assertTrue(payload['handled'])
        self.assertEqual(payload['name'], 'device_descriptor')
        self.assertEqual(len(payload['payload']), 18)
        self.assertEqual(struct.unpack_from('<H', payload['payload'], 2)[0], 0x0210)
        self.assertEqual(struct.unpack_from('<H', payload['payload'], 8)[0], 0x054C)

    def test_config_keeps_msc_interface_and_appends_zero_endpoint_vendor_interface(self):
        payload = self.model.handle_setup(bytes([0x80, 0x06, 0x00, 0x02, 0, 0, 255, 0]))['payload']
        merged = payload  # wLength 255 exceeds the merged config; model truncates
        self.assertEqual(merged[4], 2)
        self.assertEqual(struct.unpack_from('<H', merged, 2)[0], 41)
        descriptors_found = list(descriptors._walk(merged))
        interfaces = [offset for offset, length, kind in descriptors_found
                      if kind == descriptors.DESCRIPTOR_INTERFACE]
        self.assertEqual(len(interfaces), 2)
        vendor_at = interfaces[1]
        self.assertEqual(merged[vendor_at + 2], 1)
        self.assertEqual(merged[vendor_at + 4], 0)  # zero endpoints
        self.assertEqual((merged[vendor_at + 5], merged[vendor_at + 6], merged[vendor_at + 7]),
                         (0xFF, 0xDB, 0x01))

    def test_string_ee_and_msos2_set_are_served(self):
        os_string = self.model.handle_setup(bytes([0x80, 0x06, 0xEE, 0x03, 0, 0, 18, 0]))
        self.assertEqual(os_string['name'], 'ms_os_20_string')
        self.assertEqual(os_string['payload'][2:16].decode('utf-16-le'), 'MSFT20\0')
        vendor = self.model.handle_setup(bytes([0xC0, descriptors.MS_OS_20_VENDOR_CODE,
                                                0, 0, 7, 0, 46, 0]))
        self.assertTrue(vendor['handled'])
        verified = descriptors.validate_winusb_20_composite_binding(
            vendor['payload'], 1, 1)
        self.assertTrue(verified['verified'])
        unknown = self.model.handle_setup(bytes([0x80, 0x06, 0x00, 0x05, 0, 0, 8, 0]))
        self.assertFalse(unknown['handled'])


class ChunkTransportTests(unittest.TestCase):
    def test_request_chunks_reassemble_one_frame(self):
        frame = bytes(range(256)) * 16
        transport = model.ChunkTransport()
        completed = []
        for index in range(64):
            completed.append(transport.out_chunk(index, frame[index * 64:(index + 1) * 64]))
        self.assertIsNone(completed[-2])
        self.assertEqual(completed[-1], frame)

    def test_out_of_order_and_oversized_chunks_are_rejected(self):
        transport = model.ChunkTransport()
        with self.assertRaises(model.ModelError):
            transport.out_chunk(1, b'x' * 64)
        with self.assertRaises(model.ModelError):
            transport.out_chunk(0, b'')
        with self.assertRaises(model.ModelError):
            transport.out_chunk(0, b'x' * 65)

    def test_response_chunks_are_64_bytes_with_a_short_tail(self):
        transport = model.ChunkTransport()
        response = bytes(range(256)) * 16
        transport.load_response(response)
        chunks = []
        while True:
            chunk = transport.in_chunk()
            if not chunk:
                break
            chunks.append(chunk)
        self.assertEqual(len(chunks), 64)
        self.assertTrue(all(len(chunk) == 64 for chunk in chunks))
        self.assertEqual(b''.join(chunks), response)


class SaveRestoreGuardTests(unittest.TestCase):
    def setUp(self):
        self.memory = bytearray(0x1000)
        self.memory[0x100:0x112] = b'MSFT100' + b'\0' * 12
        self.memory[0x200] = 0
        self.memory[0x202:0x204] = struct.pack('<H', 0x0200)
        self.guard = model.SaveRestoreGuard(self.memory)

    def test_guard_restores_every_patch_and_gates_reconfiguration(self):
        self.guard.save('os_string', 0x100, 18, b'MSFT20' + b'\0' * 12)
        self.guard.save('mode', 0x200, 1, b'\x01')
        self.guard.save('bcdusb', 0x202, 2, struct.pack('<H', 0x0210))
        for name in ('os_string', 'mode', 'bcdusb'):
            self.guard.patch(name)
        self.assertFalse(self.guard.reconfiguration_allowed())
        self.assertEqual(self.guard.memory[0x200], 1)
        receipt = self.guard.restore_all()
        self.assertTrue(receipt['verified'])
        self.assertEqual(receipt['restored'], 3)
        self.assertTrue(self.guard.reconfiguration_allowed())
        self.assertEqual(self.guard.memory[0x200], 0)
        self.assertEqual(struct.unpack_from('<H', self.guard.memory, 0x202)[0], 0x0200)

    def test_wrong_length_patch_is_rejected(self):
        with self.assertRaises(model.ModelError):
            self.guard.save('short', 0x200, 1, b'\x01\x02')

    def test_reconfiguration_gate_clears_only_after_full_restore(self):
        self.guard.save('mode', 0x200, 1, b'\x01')
        self.guard.save('bcdusb', 0x202, 2, struct.pack('<H', 0x0210))
        self.guard.patch('mode')
        self.guard.patch('bcdusb')
        self.assertFalse(self.guard.reconfiguration_allowed())
        self.guard.restore('mode')
        self.assertFalse(self.guard.reconfiguration_allowed())
        self.guard.restore('bcdusb')
        self.assertTrue(self.guard.reconfiguration_allowed())


class UnicornChunkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.engine = model.UcChunkEngine()
        except Exception as exc:  # pragma: no cover - environment guard
            raise unittest.SkipTest(f'unicorn unavailable: {exc}')

    def test_arm_extract_and_insert_match_python_framing(self):
        frame = bytes((index * 7 + 3) & 0xFF for index in range(model.FRAME_SIZE))
        for index in (0, 1, 63):
            expected = frame[index * 64:min(len(frame), (index + 1) * 64)]
            self.assertEqual(self.engine.extract(frame, index), expected)
        rebuilt = bytearray(model.FRAME_SIZE)
        for index in range(64):
            chunk = frame[index * 64:(index + 1) * 64]
            self.assertEqual(self.engine.insert(rebuilt, index, chunk), len(chunk))
        self.assertEqual(bytes(rebuilt), frame)

    def test_arm_insert_rejects_overflow(self):
        frame = bytearray(model.FRAME_SIZE)
        with self.assertRaises(model.ModelError):
            self.engine.insert(frame, 64, b'x' * 64)


if __name__ == '__main__':
    unittest.main()
