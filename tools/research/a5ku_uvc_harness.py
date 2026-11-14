r"""CLI harness for UVC mode development and A5KU TCP host enumeration testing.

Usage:
    .\venv\Scripts\python.exe -m tools.research.a5ku_uvc_harness --self-test
    .\venv\Scripts\python.exe -m tools.research.a5ku_uvc_harness --serve --port 7643
"""

from __future__ import annotations

import argparse
import json
import socket
import struct
import time

from src.a6400.execution.a5ku_host_enum import A5kuHostClient
from src.a6400.execution.a5ku_protocol import (
    A5KU_DEFAULT_HOST,
    A5KU_DEFAULT_PORT,
    A5kuDeviceSession,
    A5kuSpeed,
)
from src.a6400.execution.a5ku_server import (
    UVC_GET_CUR,
    UVC_PROBE_COMMIT_LENGTH,
    UVC_SET_CUR,
    UVC_VS_COMMIT_CONTROL,
    UVC_VS_PROBE_CONTROL,
    A5kuTcpServer,
    A5kuUvcTestHandler,
)
from src.a6400.execution.usb_host_enum import EXPECTED_VIDEO_STREAMING_INTERFACE


def _build_uvc_ptp_device_descriptor(vid: int, pid: int) -> bytes:
    """Build a standard 18-byte USB 2.0 composite (IAD) Device Descriptor."""
    return struct.pack(
        "<BBHBBBBHHHBBBB",
        18, 0x01, 0x0200, 0xEF, 0x02, 0x01, 64,
        vid, pid, 0x0100, 1, 2, 3, 1,
    )


def run_self_test(vid: int = 0x054C, pid: int = 0x0D9E) -> dict:
    """Run an end-to-end TCP A5KU UVC+PTP enumeration + Probe/Commit self-test."""
    handler = A5kuUvcTestHandler(_build_uvc_ptp_device_descriptor(vid, pid))
    session = A5kuDeviceSession(handler, attached=True, speed=A5kuSpeed.HIGH)

    with A5kuTcpServer(session, host="127.0.0.1", port=0) as server:
        with socket.create_connection(("127.0.0.1", server.bound_port), timeout=5.0) as sock:
            client = A5kuHostClient.from_socket(sock)
            attached, generation, speed = client.hello()
            enum_res = client.enumerate_uvc_ptp(address=1)

            probe_payload = bytes(UVC_PROBE_COMMIT_LENGTH)
            client.control_out(
                0x21, UVC_SET_CUR, UVC_VS_PROBE_CONTROL,
                EXPECTED_VIDEO_STREAMING_INTERFACE, probe_payload,
            )
            probe_readback = client.control_in(
                0xA1, UVC_GET_CUR, UVC_VS_PROBE_CONTROL,
                EXPECTED_VIDEO_STREAMING_INTERFACE, UVC_PROBE_COMMIT_LENGTH,
            )
            client.control_out(
                0x21, UVC_SET_CUR, UVC_VS_COMMIT_CONTROL,
                EXPECTED_VIDEO_STREAMING_INTERFACE, probe_readback,
            )
            client.set_interface(EXPECTED_VIDEO_STREAMING_INTERFACE, 1)

    return {
        "attached": attached,
        "generation": generation,
        "speed": speed.name,
        "idVendor": f"0x{enum_res.device_descriptor.id_vendor:04X}",
        "idProduct": f"0x{enum_res.device_descriptor.id_product:04X}",
        "configuration_value": enum_res.configuration.value,
        "total_length": enum_res.configuration.total_length,
        "usbcontrol_setconfig_msgid": f"0x{enum_res.set_config_plan['event']['message_id']:06X}",
        "usbcontrol_fsm_event": f"0x{enum_res.set_config_plan['event']['fsm_event']:02X}",
        "video_streaming_alt_setting": handler.video_streaming_alt_setting,
        "probe_commit_verified": probe_readback == probe_payload,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="A5KU UVC mode development harness")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true", help="Run loopback UVC+PTP verification")
    mode.add_argument("--serve", action="store_true", help="Run interactive A5KU TCP server")
    parser.add_argument("--host", default=A5KU_DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=A5KU_DEFAULT_PORT)
    parser.add_argument("--vid", type=lambda x: int(x, 0), default=0x054C)
    parser.add_argument("--pid", type=lambda x: int(x, 0), default=0x0D9E)
    args = parser.parse_args(argv)

    if args.self_test:
        result = run_self_test(vid=args.vid, pid=args.pid)
        print(json.dumps(result, indent=2))
        return 0

    handler = A5kuUvcTestHandler(_build_uvc_ptp_device_descriptor(args.vid, args.pid))
    session = A5kuDeviceSession(handler, attached=True, speed=A5kuSpeed.HIGH)
    with A5kuTcpServer(session, host=args.host, port=args.port) as server:
        print(f"A5KU UVC test server listening on {args.host}:{server.bound_port}")
        try:
            while True:
                time.sleep(0.5)
        except KeyboardInterrupt:
            print("Shutting down A5KU UVC test server.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
