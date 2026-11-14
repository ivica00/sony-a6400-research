"""Tests for A5KU host enumeration over TCP with the verified UVC+PTP descriptor."""

from __future__ import annotations

import socket
import struct
import sys
import threading
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.a6400.execution.a5ku_host_enum import (
    A5kuHostClient,
    A5kuTransferError,
    A5kuVerifiedDescriptorHandler,
)
from src.a6400.execution.a5ku_protocol import (
    A5kuDeviceSession,
    A5kuSpeed,
    A5kuStatus,
    A5kuStreamDecoder,
)
from src.a6400.execution.usb_host_enum import (
    EXPECTED_DESCRIPTOR_LENGTH,
    SET_CONFIG_FSM_EVENT,
    SET_CONFIG_MESSAGE_ID,
)


def _build_test_device_descriptor(vid: int = 0x054C, pid: int = 0x0D9E) -> bytes:
    # Standard 18-byte USB 2.0 Device Descriptor (explicit test fixture).
    return struct.pack(
        "<BBHBBBBHHHBBBB",
        18,         # bLength
        0x01,       # bDescriptorType (DEVICE)
        0x0200,     # bcdUSB
        0xEF,       # bDeviceClass (Misc / IAD)
        0x02,       # bDeviceSubClass
        0x01,       # bDeviceProtocol
        64,         # bMaxPacketSize0
        vid,        # idVendor
        pid,        # idProduct
        0x0100,     # bcdDevice
        1,          # iManufacturer
        2,          # iProduct
        3,          # iSerialNumber
        1,          # bNumConfigurations
    )


class TestA5kuHostEnum(unittest.TestCase):
    def test_tcp_enumeration_with_verified_uvc_ptp_descriptor(self) -> None:
        handler = A5kuVerifiedDescriptorHandler(_build_test_device_descriptor())
        session = A5kuDeviceSession(handler, attached=True, speed=A5kuSpeed.HIGH)

        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]

        def _serve() -> None:
            conn, _ = server.accept()
            dec = A5kuStreamDecoder()
            with conn:
                while True:
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    for frame in dec.feed(chunk):
                        for reply in session.handle_frame(frame):
                            conn.sendall(reply.encode())

        thread = threading.Thread(target=_serve, daemon=True)
        thread.start()
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=5.0) as sock:
                client = A5kuHostClient.from_socket(sock)
                attached, generation, speed = client.hello()
                self.assertTrue(attached)
                self.assertEqual(generation, 1)
                self.assertEqual(speed, A5kuSpeed.HIGH)

                result = client.enumerate_uvc_ptp(address=1)
                self.assertEqual(result.speed, A5kuSpeed.HIGH)
                self.assertEqual(result.address, 1)
                self.assertEqual(result.device_descriptor.id_vendor, 0x054C)
                self.assertEqual(result.device_descriptor.id_product, 0x0D9E)
                self.assertEqual(
                    result.configuration.total_length, EXPECTED_DESCRIPTOR_LENGTH
                )
                self.assertEqual(
                    result.set_config_plan["event"]["message_id"], SET_CONFIG_MESSAGE_ID
                )
                self.assertEqual(
                    result.set_config_plan["event"]["fsm_event"], SET_CONFIG_FSM_EVENT
                )
                self.assertEqual(handler.reset_count, 1)
                self.assertEqual(handler.device_address, 1)
                self.assertEqual(handler.selected_configuration, 1)
        finally:
            server.close()
            thread.join(timeout=2.0)

    def test_detached_device_fails_closed_on_enumerate(self) -> None:
        handler = A5kuVerifiedDescriptorHandler(_build_test_device_descriptor())
        session = A5kuDeviceSession(handler, attached=False)
        client = A5kuHostClient(session.handle_frame)
        attached, generation, _ = client.hello()
        self.assertFalse(attached)
        self.assertEqual(generation, 0)
        with self.assertRaises(A5kuTransferError) as ctx:
            client.enumerate_uvc_ptp()
        self.assertEqual(ctx.exception.status, A5kuStatus.NODEV)


if __name__ == "__main__":
    unittest.main()
