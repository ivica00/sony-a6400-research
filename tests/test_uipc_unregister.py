"""Constructed checks for the observed UIPC unregister-callback ioctl (E0306)."""
import struct
import unittest

from src.a6400.execution.guest_uipc import (
    UIPC_CMD_REG_MSG_QUEUE_CB,
    UIPC_CMD_UNREG_MSG_QUEUE_CB,
    GuestUipc,
    UnsupportedUipc,
)


class FakeMemory:
    def __init__(self):
        self.words = {}

    def reader(self, address, size):
        data = self.words[address]
        self.asserted_size = size
        assert len(data) >= size, (address, size, len(data))
        return data[:size]

    def writer(self, address, data):
        self.words[address] = bytes(data)


def register(device, memory, queue=0x004b024e, callback=0x2bd71bb7, flags=1):
    memory.words[0x100] = struct.pack('<II', queue, 0x200)
    memory.words[0x200] = struct.pack('<4I', 0x300, callback, 0, flags)
    assert device.handle_ioctl(memory.reader, memory.writer, UIPC_CMD_REG_MSG_QUEUE_CB, 0x100) == 0
    handle, = struct.unpack('<I', memory.words[0x300])
    return handle


class UipcUnregisterTests(unittest.TestCase):
    def make_device(self):
        device = GuestUipc()
        device.pool_options_policy = 'kernel-e0301'
        return device, FakeMemory()

    def test_registered_callback_is_removed_by_queue_and_handle(self):
        device, memory = self.make_device()
        handle = register(device, memory)
        self.assertIn(handle, device.callbacks)
        memory.words[0x400] = struct.pack('<II', 0x004b024e, handle)
        self.assertEqual(
            device.handle_ioctl(memory.reader, memory.writer, UIPC_CMD_UNREG_MSG_QUEUE_CB, 0x400), 0)
        self.assertNotIn(handle, device.callbacks)
        self.assertEqual(device.transactions[-1], {'type': 'unreg_cb',
                                                   'queue': 0x004b024e, 'handle': handle})

    def test_stale_or_mismatched_identity_is_a_boundary(self):
        device, memory = self.make_device()
        handle = register(device, memory)
        memory.words[0x400] = struct.pack('<II', 0x004b024e, handle + 1)
        with self.assertRaises(UnsupportedUipc):
            device.handle_ioctl(memory.reader, memory.writer, UIPC_CMD_UNREG_MSG_QUEUE_CB, 0x400)
        memory.words[0x400] = struct.pack('<II', 0x004b024f, handle)
        with self.assertRaises(UnsupportedUipc):
            device.handle_ioctl(memory.reader, memory.writer, UIPC_CMD_UNREG_MSG_QUEUE_CB, 0x400)
        self.assertIn(handle, device.callbacks)
        # A second unregister of the same handle is stale, not silent success.
        memory.words[0x400] = struct.pack('<II', 0x004b024e, handle)
        self.assertEqual(
            device.handle_ioctl(memory.reader, memory.writer, UIPC_CMD_UNREG_MSG_QUEUE_CB, 0x400), 0)
        with self.assertRaises(UnsupportedUipc):
            device.handle_ioctl(memory.reader, memory.writer, UIPC_CMD_UNREG_MSG_QUEUE_CB, 0x400)

    def test_default_policy_keeps_the_unregister_boundary(self):
        device, memory = self.make_device()
        handle = register(device, memory)
        memory.words[0x400] = struct.pack('<II', 0x004b024e, handle)
        device.pool_options_policy = 'legacy-empty'
        with self.assertRaises(UnsupportedUipc):
            device.handle_ioctl(memory.reader, memory.writer, UIPC_CMD_UNREG_MSG_QUEUE_CB, 0x400)
        self.assertIn(handle, device.callbacks)


if __name__ == '__main__':
    unittest.main()
