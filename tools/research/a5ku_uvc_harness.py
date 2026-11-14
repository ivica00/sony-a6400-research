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
    UVC_VS_ENDPOINT_ADDR,
    UVC_VS_PROBE_CONTROL,
    A5kuTcpServer,
    A5kuUvcTestHandler,
    UvcVideoProbeControl,
    build_uvc_payload_packet,
)
from src.a6400.execution.usb_host_enum import EXPECTED_VIDEO_STREAMING_INTERFACE


def _build_uvc_ptp_device_descriptor(vid: int, pid: int) -> bytes:
    """Build a standard 18-byte USB 2.0 composite (IAD) Device Descriptor."""
    return struct.pack(
        "<BBHBBBBHHHBBBB",
        18, 0x01, 0x0200, 0xEF, 0x02, 0x01, 64,
        vid, pid, 0x0100, 1, 2, 3, 1,
    )


def run_self_test(
    vid: int = 0x054C, pid: int = 0x0D9E, use_dwc3: bool = False
) -> dict:
    """Run an end-to-end TCP A5KU UVC+PTP enumeration + Probe/Commit self-test."""
    uvc_handler = A5kuUvcTestHandler(_build_uvc_ptp_device_descriptor(vid, pid))
    if use_dwc3:
        from src.a6400.execution.a5ku_dwc3_bridge import (
            A5kuDwc3BridgeHandler,
            summarize_dwc3_traces,
        )

        handler = A5kuDwc3BridgeHandler(uvc_handler, use_prearm=True)
    else:
        handler = uvc_handler
    session = A5kuDeviceSession(handler, attached=True, speed=A5kuSpeed.HIGH)

    with A5kuTcpServer(session, host="127.0.0.1", port=0) as server:
        with socket.create_connection(("127.0.0.1", server.bound_port), timeout=5.0) as sock:
            client = A5kuHostClient.from_socket(sock)
            attached, generation, speed = client.hello()
            enum_res = client.enumerate_uvc_ptp(address=1)

            probe_req = UvcVideoProbeControl()
            probe_payload = probe_req.encode()
            client.control_out(
                0x21, UVC_SET_CUR, UVC_VS_PROBE_CONTROL,
                EXPECTED_VIDEO_STREAMING_INTERFACE, probe_payload,
            )
            probe_readback = client.control_in(
                0xA1, UVC_GET_CUR, UVC_VS_PROBE_CONTROL,
                EXPECTED_VIDEO_STREAMING_INTERFACE, UVC_PROBE_COMMIT_LENGTH,
            )
            decoded_probe = UvcVideoProbeControl.decode(probe_readback)
            client.control_out(
                0x21, UVC_SET_CUR, UVC_VS_COMMIT_CONTROL,
                EXPECTED_VIDEO_STREAMING_INTERFACE, probe_readback,
            )
            client.set_interface(EXPECTED_VIDEO_STREAMING_INTERFACE, 1)

            sample_packet = build_uvc_payload_packet(b"\xFF\xD8\xFF\xD9", frame_id=1)
            uvc_handler.queue_video_frame(sample_packet)
            frame_readback = client.bulk_in(UVC_VS_ENDPOINT_ADDR, 512)

    result = {
        "attached": attached,
        "generation": generation,
        "speed": speed.name,
        "idVendor": f"0x{enum_res.device_descriptor.id_vendor:04X}",
        "idProduct": f"0x{enum_res.device_descriptor.id_product:04X}",
        "configuration_value": enum_res.configuration.value,
        "total_length": enum_res.configuration.total_length,
        "usbcontrol_setconfig_msgid": f"0x{enum_res.set_config_plan['event']['message_id']:06X}",
        "usbcontrol_fsm_event": f"0x{enum_res.set_config_plan['event']['fsm_event']:02X}",
        "video_streaming_alt_setting": uvc_handler.video_streaming_alt_setting,
        "probe_commit_verified": probe_readback == probe_payload,
        "probe_format_frame": [decoded_probe.b_format_index, decoded_probe.b_frame_index],
        "frame_in_verified": frame_readback == sample_packet,
    }
    if use_dwc3:
        result["dwc3_summary"] = summarize_dwc3_traces(handler.ep0_traces)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="A5KU UVC mode development harness")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true", help="Run loopback UVC+PTP verification")
    mode.add_argument("--serve", action="store_true", help="Run interactive A5KU TCP server")
    parser.add_argument("--host", default=A5KU_DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=A5KU_DEFAULT_PORT)
    parser.add_argument("--vid", type=lambda x: int(x, 0), default=0x054C)
    parser.add_argument("--pid", type=lambda x: int(x, 0), default=0x0D9E)
    parser.add_argument("--dwc3", action="store_true", help="Route EP0 control transfers through Unicorn DWC3")
    args = parser.parse_args(argv)

    if args.self_test:
        result = run_self_test(vid=args.vid, pid=args.pid, use_dwc3=args.dwc3)
        print(json.dumps(result, indent=2))
        return 0

    uvc_handler = A5kuUvcTestHandler(_build_uvc_ptp_device_descriptor(args.vid, args.pid))
    if args.dwc3:
        from src.a6400.execution.a5ku_dwc3_bridge import A5kuDwc3BridgeHandler

        handler = A5kuDwc3BridgeHandler(uvc_handler, use_prearm=True)
    else:
        handler = uvc_handler
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
