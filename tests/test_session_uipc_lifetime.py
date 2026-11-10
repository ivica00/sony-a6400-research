import struct
import unittest
from types import SimpleNamespace

from src.a6400.execution.guest_uipc import GuestUipc
from tools.research.emulator_session import live_uipc_receiver


class SessionUipcLifetimeTests(unittest.TestCase):
    def test_restore_replaces_receive_backend_without_losing_old_identity(self):
        old = GuestUipc()
        old.enqueue_message(0x1706003, 0x111c)
        probe = SimpleNamespace(uipc=old)
        receive = live_uipc_receiver(probe)
        restored = GuestUipc()
        restored.enqueue_message(0x1706003, 0x222c)
        probe.uipc = restored
        output = {}
        def reader(address, size):
            self.assertEqual((address, size), (0x100, 16))
            return struct.pack('<4I', 0x1706003, 0x500, 0, 0xffffffff)
        def writer(address, value):
            output[address] = value
        self.assertEqual(receive(reader, writer, 0x100), 0)
        self.assertEqual(output, {0x500: struct.pack('<I', 0x222c)})
        self.assertEqual(old.message_queues[0x1706003], [0x111c])
        self.assertEqual(restored.message_queues[0x1706003], [])
