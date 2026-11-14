"""Integration tests for A5kuDwc3BridgeHandler with real live-vmlinux DWC3 EP0."""

from __future__ import annotations

from pathlib import Path
import socket
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.a6400.execution.a5ku_dwc3_bridge import (
    A5kuDwc3BridgeHandler,
    summarize_dwc3_traces,
)
from src.a6400.execution.a5ku_host_enum import A5kuHostClient
from src.a6400.execution.a5ku_protocol import A5kuDeviceSession, A5kuSpeed
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

KERNEL_BIN = ROOT / "artifacts/analysis/e0415-nflasha-boot/live-vmlinux.bin"
BRIDGE_OBJ = ROOT / "artifacts/native/uvc-transport-e0511-inout-prearm/callback-bridge.o"


def _build_test_device_descriptor() -> bytes:
    return struct.pack(
        "<BBHBBBBHHHBBBB",
        18, 0x01, 0x0200, 0xEF, 0x02, 0x01, 64,
        0x054C, 0x0D9E, 0x0100, 1, 2, 3, 1,
    )


@unittest.skipUnless(
    KERNEL_BIN.exists() and BRIDGE_OBJ.exists(),
    "Real live-vmlinux.bin and E0511 callback-bridge.o required",
)
class TestA5kuDwc3Bridge(unittest.TestCase):
    def test_uvc_enum_and_probe_commit_through_dwc3_with_prearm(self) -> None:
        inner = A5kuUvcTestHandler(_build_test_device_descriptor())
        bridge = A5kuDwc3BridgeHandler(inner, use_prearm=True)
        session = A5kuDeviceSession(bridge, attached=True, speed=A5kuSpeed.HIGH)

        with A5kuTcpServer(session, host="127.0.0.1", port=0) as server:
            with socket.create_connection(("127.0.0.1", server.bound_port), timeout=5.0) as sock:
                client = A5kuHostClient.from_socket(sock)
                attached, _, _ = client.hello()
                self.assertTrue(attached)

                enum_res = client.enumerate_uvc_ptp(address=1)
                self.assertEqual(enum_res.configuration.value, 1)
                self.assertEqual(enum_res.configuration.total_length, 173)

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
                    EXPECTED_VIDEO_STREAMING_INTERFACE, probe_resp,
                )
                client.set_interface(EXPECTED_VIDEO_STREAMING_INTERFACE, 1)

                sample_frame = b"\x0C\x02\xFF\xD8\xFF\xD9"
                inner.queue_video_frame(sample_frame)
                self.assertEqual(client.bulk_in(UVC_VS_ENDPOINT_ADDR, 64), sample_frame)

        summary = summarize_dwc3_traces(bridge.ep0_traces)
        self.assertEqual(summary["total_control_transfers"], 9)
        self.assertEqual(summary["three_stage_transfers"], 6)
        self.assertTrue(summary["all_three_stage_prearmed"])
        self.assertTrue(summary["all_completed_to_setup"])

    def test_uvc_probe_without_prearm_hits_nrdy_fallback(self) -> None:
        inner = A5kuUvcTestHandler(_build_test_device_descriptor())
        bridge = A5kuDwc3BridgeHandler(inner, use_prearm=False)
        session = A5kuDeviceSession(bridge, attached=True, speed=A5kuSpeed.HIGH)

        with A5kuTcpServer(session, host="127.0.0.1", port=0) as server:
            with socket.create_connection(("127.0.0.1", server.bound_port), timeout=5.0) as sock:
                client = A5kuHostClient.from_socket(sock)
                client.hello()

                probe_req = bytes(UVC_PROBE_COMMIT_LENGTH)
                client.control_out(
                    0x21, UVC_SET_CUR, UVC_VS_PROBE_CONTROL,
                    EXPECTED_VIDEO_STREAMING_INTERFACE, probe_req,
                )
                probe_resp = client.control_in(
                    0xA1, UVC_GET_CUR, UVC_VS_PROBE_CONTROL,
                    EXPECTED_VIDEO_STREAMING_INTERFACE, UVC_PROBE_COMMIT_LENGTH,
                )
                self.assertEqual(probe_resp, probe_req)

        summary = summarize_dwc3_traces(bridge.ep0_traces)
        self.assertEqual(summary["three_stage_transfers"], 2)
        self.assertFalse(summary["all_three_stage_prearmed"])
        self.assertTrue(summary["all_completed_to_setup"])


if __name__ == "__main__":
    unittest.main()
