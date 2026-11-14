"""Unit tests for A5kuTcpServer and A5kuUvcTestHandler."""

from __future__ import annotations

import socket
import struct
import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.a6400.execution.a5ku_host_enum import A5kuHostClient, A5kuTransferError
from src.a6400.execution.a5ku_protocol import (
    A5kuDeviceSession,
    A5kuEvent,
    A5kuMessageType,
    A5kuSpeed,
    A5kuStatus,
    A5kuStreamDecoder,
)
from src.a6400.execution.a5ku_server import (
    UVC_GET_CUR,
    UVC_PROBE_COMMIT_LENGTH,
    UVC_SET_CUR,
    UVC_VS_COMMIT_CONTROL,
    UVC_VS_ENDPOINT_ADDR,
    UVC_VS_PROBE_CONTROL,
    A5kuTcpServer,
    A5kuUvcTestHandler,
)
from src.a6400.execution.usb_host_enum import EXPECTED_VIDEO_STREAMING_INTERFACE


def _build_test_device_descriptor() -> bytes:
    return struct.pack(
        "<BBHBBBBHHHBBBB",
        18, 0x01, 0x0200, 0xEF, 0x02, 0x01, 64,
        0x054C, 0x0D9E, 0x0100, 1, 2, 3, 1,
    )


class TestA5kuServerAndUvc(unittest.TestCase):
    def test_uvc_probe_commit_set_interface_and_explicit_frame_in(self) -> None:
        handler = A5kuUvcTestHandler(_build_test_device_descriptor())
        session = A5kuDeviceSession(handler, attached=True, speed=A5kuSpeed.HIGH)

        with A5kuTcpServer(session, host="127.0.0.1", port=0) as server:
            with socket.create_connection(("127.0.0.1", server.bound_port), timeout=5.0) as sock:
                client = A5kuHostClient.from_socket(sock)
                attached, generation, _ = client.hello()
                self.assertTrue(attached)
                self.assertEqual(generation, 1)

                enum_res = client.enumerate_uvc_ptp(address=1)
                self.assertEqual(enum_res.configuration.value, 1)

                # Empty IN queue fails closed with STALL
                with self.assertRaises(A5kuTransferError) as empty_ctx:
                    client.bulk_in(UVC_VS_ENDPOINT_ADDR, 512)
                self.assertEqual(empty_ctx.exception.status, A5kuStatus.STALL)

                # UVC 1.1 26-byte Probe + Commit on VideoStreaming interface 2
                probe_req = bytes(range(UVC_PROBE_COMMIT_LENGTH))
                client.control_out(
                    0x21, UVC_SET_CUR, UVC_VS_PROBE_CONTROL,
                    EXPECTED_VIDEO_STREAMING_INTERFACE, probe_req,
                )
                probe_resp = client.control_in(
                    0xA1, UVC_GET_CUR, UVC_VS_PROBE_CONTROL,
                    EXPECTED_VIDEO_STREAMING_INTERFACE, UVC_PROBE_COMMIT_LENGTH,
                )
                self.assertEqual(probe_resp, probe_req)

                client.control_out(
                    0x21, UVC_SET_CUR, UVC_VS_COMMIT_CONTROL,
                    EXPECTED_VIDEO_STREAMING_INTERFACE, probe_req,
                )
                client.set_interface(EXPECTED_VIDEO_STREAMING_INTERFACE, 1)
                self.assertEqual(handler.video_streaming_alt_setting, 1)

                # Explicit frame queued by caller is delivered verbatim
                sample_frame = b"\x0C\x02" + b"\xFF\xD8\xFF\xD9"
                handler.queue_video_frame(sample_frame)
                got = client.bulk_in(UVC_VS_ENDPOINT_ADDR, 64)
                self.assertEqual(got, sample_frame)

    def test_live_attach_and_detach_push_events(self) -> None:
        handler = A5kuUvcTestHandler(_build_test_device_descriptor())
        session = A5kuDeviceSession(handler, attached=False)

        with A5kuTcpServer(session, host="127.0.0.1", port=0) as server:
            with socket.create_connection(("127.0.0.1", server.bound_port), timeout=5.0) as sock:
                client = A5kuHostClient.from_socket(sock)
                attached, generation, _ = client.hello()
                self.assertFalse(attached)
                self.assertEqual(generation, 0)

                server.attach(A5kuSpeed.HIGH)
                dec = A5kuStreamDecoder()
                ev_attach = dec.feed(sock.recv(4096))[0]
                self.assertEqual(ev_attach.msg_type, A5kuMessageType.EVENT)
                self.assertEqual(ev_attach.arg, A5kuEvent.ATTACHED)

                server.detach()
                ev_detach = dec.feed(sock.recv(4096))[0]
                self.assertEqual(ev_detach.msg_type, A5kuMessageType.EVENT)
                self.assertEqual(ev_detach.arg, A5kuEvent.DETACHED)


if __name__ == "__main__":
    unittest.main()
