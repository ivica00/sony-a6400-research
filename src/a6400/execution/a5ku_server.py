"""Threaded A5KU TCP server and fail-closed UVC development gadget handler.

Provides ``A5kuTcpServer`` (one client at a time on ``127.0.0.1:7643`` by
default, matching ``Oein/a5000-emulator`` ``docs/RE_USB_HOST_PATH.md`` §5.1)
and ``A5kuUvcTestHandler``, which extends ``A5kuVerifiedDescriptorHandler``
with explicit UVC 1.1 VideoStreaming Probe/Commit (26-byte ``SET_CUR`` /
``GET_CUR`` on interface 2), ``SET_INTERFACE`` tracking, and an explicit
caller-supplied frame queue for endpoint ``0x82``.

No video frames, probe defaults, or descriptors are fabricated: empty queues
and unsupported requests fail closed with ``A5kuStatus.STALL``.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import socket
import struct
import threading

from src.a6400.execution.a5ku_host_enum import A5kuVerifiedDescriptorHandler
from src.a6400.execution.a5ku_protocol import (
    A5KU_DEFAULT_HOST,
    A5KU_DEFAULT_PORT,
    A5kuDeviceSession,
    A5kuFrame,
    A5kuSpeed,
    A5kuStatus,
    A5kuStreamDecoder,
    UsbSetupPacket,
)
from src.a6400.execution.usb_host_enum import (
    EXPECTED_VIDEO_STREAMING_ENDPOINT,
    EXPECTED_VIDEO_STREAMING_INTERFACE,
)

# UVC 1.1 Class-Specific VideoStreaming control selectors & requests.
UVC_SET_CUR = 0x01
UVC_GET_CUR = 0x81
UVC_VS_PROBE_CONTROL = 0x0100
UVC_VS_COMMIT_CONTROL = 0x0200
UVC_PROBE_COMMIT_LENGTH = 26
UVC_VS_ENDPOINT_ADDR = int(EXPECTED_VIDEO_STREAMING_ENDPOINT, 16)  # 0x82
UVC_PAYLOAD_HEADER_LENGTH = 12
_UVC_PROBE_STRUCT = struct.Struct("<HBBIHHHHHII")


@dataclass(frozen=True)
class UvcVideoProbeControl:
    """UVC 1.1 26-byte VS_PROBE_CONTROL / VS_COMMIT_CONTROL structure."""

    bm_hint: int = 0x0001
    b_format_index: int = 1
    b_frame_index: int = 1
    dw_frame_interval: int = 333333  # 30 fps in 100 ns units
    w_key_frame_rate: int = 0
    w_p_frame_rate: int = 0
    w_comp_quality: int = 0
    w_comp_window_size: int = 0
    w_delay: int = 0
    dw_max_video_frame_size: int = 1280 * 720 * 2
    dw_max_payload_transfer_size: int = 131060

    def encode(self) -> bytes:
        """Pack into 26 little-endian bytes."""
        return _UVC_PROBE_STRUCT.pack(
            self.bm_hint,
            self.b_format_index,
            self.b_frame_index,
            self.dw_frame_interval,
            self.w_key_frame_rate,
            self.w_p_frame_rate,
            self.w_comp_quality,
            self.w_comp_window_size,
            self.w_delay,
            self.dw_max_video_frame_size,
            self.dw_max_payload_transfer_size,
        )

    @classmethod
    def decode(cls, raw: bytes) -> "UvcVideoProbeControl":
        """Unpack a 26-byte VS_PROBE_CONTROL / VS_COMMIT_CONTROL payload."""
        if len(raw) != UVC_PROBE_COMMIT_LENGTH:
            raise ValueError(f"Expected {UVC_PROBE_COMMIT_LENGTH} bytes, got {len(raw)}")
        return cls(*_UVC_PROBE_STRUCT.unpack(raw))


def build_uvc_payload_packet(
    payload: bytes,
    *,
    frame_id: int = 0,
    end_of_frame: bool = True,
) -> bytes:
    """Wrap a video frame slice in a standard 12-byte UVC 1.1 payload header."""
    bm_header_info = 0x80 | (frame_id & 0x01) | (0x02 if end_of_frame else 0x00)
    header = struct.pack("<BBIIH", UVC_PAYLOAD_HEADER_LENGTH, bm_header_info, 0, 0, 0)
    return header + bytes(payload)


class A5kuUvcTestHandler(A5kuVerifiedDescriptorHandler):
    """Fail-closed UVC+PTP gadget handler for host-side UVC development tests."""

    def __init__(
        self,
        device_descriptor: bytes,
        config_descriptor: bytes | None = None,
    ) -> None:
        super().__init__(device_descriptor, config_descriptor)
        self.probe_state: bytes | None = None
        self.commit_state: bytes | None = None
        self.video_streaming_alt_setting: int = 0
        self._in_frames: deque[bytes] = deque()

    def queue_video_frame(self, payload: bytes) -> None:
        """Queue an explicit caller-supplied payload for endpoint 0x82 IN."""
        self._in_frames.append(bytes(payload))

    def handle_reset(self) -> tuple[A5kuStatus, int]:
        self.probe_state = None
        self.commit_state = None
        self.video_streaming_alt_setting = 0
        self._in_frames.clear()
        return super().handle_reset()

    def handle_control(
        self, setup: UsbSetupPacket, out_data: bytes
    ) -> tuple[A5kuStatus, bytes]:
        # Standard Interface SET_INTERFACE (0x01 / 0x0B) on VideoStreaming iface 2
        if (
            setup.bm_request_type == 0x01
            and setup.b_request == 0x0B
            and setup.w_index == EXPECTED_VIDEO_STREAMING_INTERFACE
            and setup.w_value in (0, 1)
            and not out_data
        ):
            self.video_streaming_alt_setting = setup.w_value
            return A5kuStatus.OK, b""

        # UVC Class Interface Probe/Commit (0x21 SET_CUR / 0xA1 GET_CUR) on iface 2
        target_iface = setup.w_index & 0xFF
        if target_iface == EXPECTED_VIDEO_STREAMING_INTERFACE:
            if (
                setup.bm_request_type == 0x21
                and setup.b_request == UVC_SET_CUR
                and len(out_data) == UVC_PROBE_COMMIT_LENGTH
            ):
                if setup.w_value == UVC_VS_PROBE_CONTROL:
                    self.probe_state = bytes(out_data)
                    return A5kuStatus.OK, b""
                if setup.w_value == UVC_VS_COMMIT_CONTROL:
                    self.commit_state = bytes(out_data)
                    return A5kuStatus.OK, b""

            if (
                setup.bm_request_type == 0xA1
                and setup.b_request == UVC_GET_CUR
                and setup.w_length == UVC_PROBE_COMMIT_LENGTH
            ):
                if setup.w_value == UVC_VS_PROBE_CONTROL and self.probe_state is not None:
                    return A5kuStatus.OK, self.probe_state
                if setup.w_value == UVC_VS_COMMIT_CONTROL and self.commit_state is not None:
                    return A5kuStatus.OK, self.commit_state
                return A5kuStatus.STALL, b""

        return super().handle_control(setup, out_data)

    def handle_in(self, ep: int, max_length: int) -> tuple[A5kuStatus, bytes]:
        if ep == UVC_VS_ENDPOINT_ADDR and self._in_frames:
            frame = self._in_frames[0]
            if len(frame) > max_length:
                return A5kuStatus.OVERFLOW, b""
            self._in_frames.popleft()
            return A5kuStatus.OK, frame
        return A5kuStatus.STALL, b""


class A5kuTcpServer:
    """Single-client TCP server hosting an ``A5kuDeviceSession``."""

    def __init__(
        self,
        session: A5kuDeviceSession,
        host: str = A5KU_DEFAULT_HOST,
        port: int = A5KU_DEFAULT_PORT,
    ) -> None:
        self.session = session
        self.host = host
        self.port = port
        self._sock: socket.socket | None = None
        self._client: socket.socket | None = None
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def bound_port(self) -> int:
        if self._sock is None:
            return self.port
        return int(self._sock.getsockname()[1])

    def start(self) -> int:
        """Bind, listen, and start the accept/serve background thread."""
        if self._sock is not None:
            return self.bound_port
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self.host, self.port))
        sock.listen(1)
        sock.settimeout(0.2)
        self._sock = sock
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._serve_loop, daemon=True)
        self._thread.start()
        return self.bound_port

    def stop(self) -> None:
        """Stop the server thread and close open sockets."""
        self._stop_event.set()
        with self._lock:
            if self._client is not None:
                try:
                    self._client.close()
                except OSError:
                    pass
                self._client = None
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def __enter__(self) -> "A5kuTcpServer":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.stop()

    def attach(self, speed: int = A5kuSpeed.HIGH) -> None:
        """Attach the device and push ``EVENT(ATTACHED)`` to any active client."""
        with self._lock:
            events = self.session.attach(speed)
            self._send_frames_locked(events)

    def detach(self) -> None:
        """Detach the device and push ``EVENT(DETACHED)`` to any active client."""
        with self._lock:
            events = self.session.detach()
            self._send_frames_locked(events)

    def _send_frames_locked(self, frames: list[A5kuFrame]) -> None:
        if self._client is None or not frames:
            return
        for frame in frames:
            try:
                self._client.sendall(frame.encode())
            except OSError:
                break

    def _serve_loop(self) -> None:
        assert self._sock is not None
        while not self._stop_event.is_set():
            try:
                conn, _ = self._sock.accept()
            except TimeoutError:
                continue
            except OSError:
                break

            conn.settimeout(0.2)
            with self._lock:
                self._client = conn
            decoder = A5kuStreamDecoder()
            try:
                while not self._stop_event.is_set():
                    try:
                        chunk = conn.recv(4096)
                    except TimeoutError:
                        continue
                    except OSError:
                        break
                    if not chunk:
                        break
                    for frame in decoder.feed(chunk):
                        with self._lock:
                            replies = self.session.handle_frame(frame)
                            self._send_frames_locked(replies)
            finally:
                with self._lock:
                    if self._client is conn:
                        self._client = None
                try:
                    conn.close()
                except OSError:
                    pass
