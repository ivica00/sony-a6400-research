"""Clean-room A5KU ("USB over TCP") wire codec and device-side session.

Implements the 16-byte little-endian framing protocol designed by Oein
(``Oein/a5000-emulator``, ``docs/RE_USB_HOST_PATH.md`` §5) so host tools
such as ``pmca-console -d socket`` or local host-enumeration harnesses can
communicate with an emulated Sony BIONZ X USB device over TCP without kernel
USB/IP drivers.

Protocol invariants:
- Header layout: ``<HBBIII`` (16 bytes): ``magic=0x5541`` ("AU"), ``type``,
  ``ep``, ``id``, ``length``, ``arg``.
- Detached or generation-mismatched device requests fail closed with
  ``A5kuStatus.NODEV``.
- No USB descriptors, transfers, or acknowledgements are fabricated by default;
  callers must supply an explicit ``A5kuGadgetHandler``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
import socket
import struct
from typing import Protocol


A5KU_MAGIC = 0x5541  # "AU" in little-endian
A5KU_PROTOCOL_VERSION = 1
A5KU_DEFAULT_HOST = "127.0.0.1"
A5KU_DEFAULT_PORT = 7643
A5KU_HEADER_STRUCT = struct.Struct("<HBBIII")
A5KU_HEADER_SIZE = A5KU_HEADER_STRUCT.size  # 16 bytes

_U32_STRUCT = struct.Struct("<I")
_TWO_U32_STRUCT = struct.Struct("<II")
_HELLO_ACK_STRUCT = struct.Struct("<IIII")
_USB_SETUP_STRUCT = struct.Struct("<BBHHH")


class A5kuProtocolError(ValueError):
    """Raised when an A5KU frame or payload violates the wire specification."""


class A5kuMessageType(IntEnum):
    """A5KU wire message types (client -> device and device -> client)."""

    # Client -> device
    HELLO = 0x01
    RESET = 0x02
    CONTROL = 0x03
    OUT = 0x04
    IN = 0x05
    CANCEL = 0x06

    # Device -> client
    HELLO_ACK = 0x81
    RESET_DONE = 0x82
    CONTROL_DONE = 0x83
    OUT_DONE = 0x84
    IN_DONE = 0x85
    EVENT = 0x90


class A5kuStatus(IntEnum):
    """Completion status codes carried in the ``arg`` header field."""

    OK = 0
    STALL = 1
    NODEV = 2
    CANCELLED = 3
    OVERFLOW = 4
    PROTO = 5


class A5kuSpeed(IntEnum):
    """USB bus speed values reported by HELLO_ACK, RESET_DONE, and EVENT."""

    UNKNOWN = 0
    FULL = 2
    HIGH = 3


class A5kuEvent(IntEnum):
    """Asynchronous device attachment events pushed via ``EVENT``."""

    ATTACHED = 1
    DETACHED = 2


class A5kuOutFlag(IntEnum):
    """Bitflags carried in ``OUT.arg``."""

    APPEND_ZLP_ON_FULL = 0x01
    SEND_ZLP_ON_EMPTY = 0x02


@dataclass(frozen=True)
class A5kuFrame:
    """Decoded A5KU wire frame (16-byte header + payload)."""

    msg_type: int
    ep: int = 0
    req_id: int = 0
    arg: int = 0
    payload: bytes = b""

    def encode(self) -> bytes:
        """Serialize this frame to little-endian wire bytes."""
        header = A5KU_HEADER_STRUCT.pack(
            A5KU_MAGIC,
            self.msg_type & 0xFF,
            self.ep & 0xFF,
            self.req_id & 0xFFFFFFFF,
            len(self.payload) & 0xFFFFFFFF,
            self.arg & 0xFFFFFFFF,
        )
        return header + self.payload


@dataclass(frozen=True)
class UsbSetupPacket:
    """Decoded 8-byte USB standard/class/vendor SETUP packet."""

    bm_request_type: int
    b_request: int
    w_value: int
    w_index: int
    w_length: int

    @property
    def is_in(self) -> bool:
        """True if direction bit7 is device-to-host (IN)."""
        return bool(self.bm_request_type & 0x80)

    def encode(self) -> bytes:
        """Pack back into an 8-byte little-endian SETUP packet."""
        return _USB_SETUP_STRUCT.pack(
            self.bm_request_type,
            self.b_request,
            self.w_value,
            self.w_index,
            self.w_length,
        )


def decode_frame(raw: bytes) -> tuple[A5kuFrame, int]:
    """Decode one A5KU frame from ``raw``.

    Returns ``(frame, consumed_bytes)``. Raises ``A5kuProtocolError`` if
    ``raw`` is incomplete, has a bad magic, or has an invalid header.
    """
    if len(raw) < A5KU_HEADER_SIZE:
        raise A5kuProtocolError(
            f"Incomplete A5KU header: got {len(raw)} bytes, need {A5KU_HEADER_SIZE}"
        )
    magic, msg_type, ep, req_id, length, arg = A5KU_HEADER_STRUCT.unpack_from(raw, 0)
    if magic != A5KU_MAGIC:
        raise A5kuProtocolError(
            f"Invalid A5KU magic 0x{magic:04X} (expected 0x{A5KU_MAGIC:04X})"
        )
    total = A5KU_HEADER_SIZE + length
    if len(raw) < total:
        raise A5kuProtocolError(
            f"Incomplete A5KU payload: got {len(raw) - A5KU_HEADER_SIZE} bytes, need {length}"
        )
    return A5kuFrame(
        msg_type=msg_type,
        ep=ep,
        req_id=req_id,
        arg=arg,
        payload=bytes(raw[A5KU_HEADER_SIZE:total]),
    ), total


class A5kuStreamDecoder:
    """Incremental decoder for A5KU frames arriving over a byte stream."""

    def __init__(self, max_payload_bytes: int = 16 * 1024 * 1024) -> None:
        self._buf = bytearray()
        self._max_payload_bytes = max_payload_bytes

    def feed(self, chunk: bytes) -> list[A5kuFrame]:
        """Append ``chunk`` and return all complete frames decoded so far."""
        if chunk:
            self._buf.extend(chunk)
        frames: list[A5kuFrame] = []
        while len(self._buf) >= A5KU_HEADER_SIZE:
            magic, msg_type, ep, req_id, length, arg = A5KU_HEADER_STRUCT.unpack_from(
                self._buf, 0
            )
            if magic != A5KU_MAGIC:
                raise A5kuProtocolError(
                    f"Invalid A5KU magic 0x{magic:04X} (expected 0x{A5KU_MAGIC:04X})"
                )
            if length > self._max_payload_bytes:
                raise A5kuProtocolError(
                    f"A5KU payload length {length} exceeds limit {self._max_payload_bytes}"
                )
            total = A5KU_HEADER_SIZE + length
            if len(self._buf) < total:
                break
            payload = bytes(self._buf[A5KU_HEADER_SIZE:total])
            del self._buf[:total]
            frames.append(
                A5kuFrame(
                    msg_type=msg_type,
                    ep=ep,
                    req_id=req_id,
                    arg=arg,
                    payload=payload,
                )
            )
        return frames


def make_hello_frame(req_id: int = 1, version: int = A5KU_PROTOCOL_VERSION) -> A5kuFrame:
    """Build a client ``HELLO`` frame."""
    return A5kuFrame(
        msg_type=A5kuMessageType.HELLO,
        req_id=req_id,
        payload=_U32_STRUCT.pack(version),
    )


def make_hello_ack_frame(
    req_id: int,
    attached: bool,
    generation: int,
    speed: int = A5kuSpeed.HIGH,
    version: int = A5KU_PROTOCOL_VERSION,
) -> A5kuFrame:
    """Build a device ``HELLO_ACK`` frame."""
    return A5kuFrame(
        msg_type=A5kuMessageType.HELLO_ACK,
        req_id=req_id,
        arg=A5kuStatus.OK,
        payload=_HELLO_ACK_STRUCT.pack(
            version,
            1 if attached else 0,
            generation,
            speed,
        ),
    )


def make_event_frame(
    event: A5kuEvent,
    generation: int,
    speed: int = A5kuSpeed.HIGH,
) -> A5kuFrame:
    """Build a device ``EVENT`` frame (``id=0``)."""
    return A5kuFrame(
        msg_type=A5kuMessageType.EVENT,
        req_id=0,
        arg=int(event),
        payload=_TWO_U32_STRUCT.pack(generation, speed),
    )


def parse_control_payload(payload: bytes) -> tuple[UsbSetupPacket, bytes]:
    """Parse a ``CONTROL`` frame payload into ``(setup, out_data)``."""
    if len(payload) < _USB_SETUP_STRUCT.size:
        raise A5kuProtocolError(
            f"CONTROL payload too short: {len(payload)} bytes (need >= 8)"
        )
    bm_req, b_req, w_val, w_idx, w_len = _USB_SETUP_STRUCT.unpack_from(payload, 0)
    setup = UsbSetupPacket(
        bm_request_type=bm_req,
        b_request=b_req,
        w_value=w_val,
        w_index=w_idx,
        w_length=w_len,
    )
    extra = payload[_USB_SETUP_STRUCT.size :]
    if setup.is_in:
        if extra:
            raise A5kuProtocolError(
                f"CONTROL IN request must not carry OUT data (got {len(extra)} bytes)"
            )
    elif len(extra) != setup.w_length:
        raise A5kuProtocolError(
            f"CONTROL OUT length mismatch: header wLength={setup.w_length}, payload={len(extra)}"
        )
    return setup, extra


class A5kuGadgetHandler(Protocol):
    """Pluggable USB gadget backend invoked by ``A5kuDeviceSession``."""

    def handle_reset(self) -> tuple[A5kuStatus, int]:
        """Handle USB bus reset, returning ``(status, speed)``."""

    def handle_control(
        self, setup: UsbSetupPacket, out_data: bytes
    ) -> tuple[A5kuStatus, bytes]:
        """Handle EP0 SETUP + optional OUT data, returning ``(status, in_data)``."""

    def handle_out(
        self, ep: int, data: bytes, flags: int
    ) -> tuple[A5kuStatus, int]:
        """Handle bulk/interrupt OUT transfer, returning ``(status, accepted_bytes)``."""

    def handle_in(self, ep: int, max_length: int) -> tuple[A5kuStatus, bytes]:
        """Handle bulk/interrupt IN transfer, returning ``(status, data)``."""


class FailClosedGadgetHandler:
    """Default fail-closed handler that stalls all transfers."""

    def handle_reset(self) -> tuple[A5kuStatus, int]:
        return A5kuStatus.STALL, A5kuSpeed.UNKNOWN

    def handle_control(
        self, setup: UsbSetupPacket, out_data: bytes
    ) -> tuple[A5kuStatus, bytes]:
        return A5kuStatus.STALL, b""

    def handle_out(
        self, ep: int, data: bytes, flags: int
    ) -> tuple[A5kuStatus, int]:
        return A5kuStatus.STALL, 0

    def handle_in(self, ep: int, max_length: int) -> tuple[A5kuStatus, bytes]:
        return A5kuStatus.STALL, b""


class A5kuDeviceSession:
    """Stateful A5KU device-side protocol session.

    Tracks attachment state, monotonic ``generation`` counter, and ``HELLO``
    handshake state, and routes USB requests to ``handler`` only while
    attached.
    """

    def __init__(
        self,
        handler: A5kuGadgetHandler | None = None,
        *,
        attached: bool = False,
        speed: int = A5kuSpeed.HIGH,
    ) -> None:
        self._handler: A5kuGadgetHandler = handler or FailClosedGadgetHandler()
        self._attached = attached
        self._generation = 1 if attached else 0
        self._speed = speed if attached else A5kuSpeed.UNKNOWN
        self._hello_done = False

    @property
    def attached(self) -> bool:
        return self._attached

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def speed(self) -> int:
        return self._speed

    def attach(self, speed: int = A5kuSpeed.HIGH) -> list[A5kuFrame]:
        """Transition to attached state, increment generation, and emit EVENT."""
        self._attached = True
        self._generation += 1
        self._speed = speed
        if not self._hello_done:
            return []
        return [make_event_frame(A5kuEvent.ATTACHED, self._generation, self._speed)]

    def detach(self) -> list[A5kuFrame]:
        """Transition to detached state and emit EVENT if previously attached."""
        was_attached = self._attached
        self._attached = False
        self._speed = A5kuSpeed.UNKNOWN
        if not was_attached or not self._hello_done:
            return []
        return [make_event_frame(A5kuEvent.DETACHED, self._generation, A5kuSpeed.UNKNOWN)]

    def handle_frame(self, frame: A5kuFrame) -> list[A5kuFrame]:
        """Process one incoming client frame and return reply frames."""
        mtype = frame.msg_type

        if mtype == A5kuMessageType.HELLO:
            if len(frame.payload) != 4:
                return [
                    A5kuFrame(
                        msg_type=A5kuMessageType.HELLO_ACK,
                        req_id=frame.req_id,
                        arg=A5kuStatus.PROTO,
                    )
                ]
            (version,) = _U32_STRUCT.unpack(frame.payload)
            if version != A5KU_PROTOCOL_VERSION:
                return [
                    A5kuFrame(
                        msg_type=A5kuMessageType.HELLO_ACK,
                        req_id=frame.req_id,
                        arg=A5kuStatus.PROTO,
                    )
                ]
            self._hello_done = True
            return [
                make_hello_ack_frame(
                    req_id=frame.req_id,
                    attached=self._attached,
                    generation=self._generation,
                    speed=self._speed,
                )
            ]

        if mtype == A5kuMessageType.CANCEL:
            # Synchronous handler has no queued async requests; CANCEL has no own reply.
            return []

        reply_type_map = {
            A5kuMessageType.RESET: A5kuMessageType.RESET_DONE,
            A5kuMessageType.CONTROL: A5kuMessageType.CONTROL_DONE,
            A5kuMessageType.OUT: A5kuMessageType.OUT_DONE,
            A5kuMessageType.IN: A5kuMessageType.IN_DONE,
        }
        reply_type = reply_type_map.get(mtype)
        if reply_type is None:
            raise A5kuProtocolError(f"Unsupported client A5KU message type 0x{mtype:02X}")

        if not self._attached:
            return [
                A5kuFrame(
                    msg_type=reply_type,
                    ep=frame.ep,
                    req_id=frame.req_id,
                    arg=A5kuStatus.NODEV,
                )
            ]

        if mtype == A5kuMessageType.RESET:
            status, speed = self._handler.handle_reset()
            if status == A5kuStatus.OK:
                self._speed = speed
            return [
                A5kuFrame(
                    msg_type=A5kuMessageType.RESET_DONE,
                    req_id=frame.req_id,
                    arg=int(status),
                    payload=_U32_STRUCT.pack(speed) if status == A5kuStatus.OK else b"",
                )
            ]

        if mtype == A5kuMessageType.CONTROL:
            try:
                setup, out_data = parse_control_payload(frame.payload)
            except A5kuProtocolError:
                return [
                    A5kuFrame(
                        msg_type=A5kuMessageType.CONTROL_DONE,
                        req_id=frame.req_id,
                        arg=A5kuStatus.PROTO,
                    )
                ]
            status, in_data = self._handler.handle_control(setup, out_data)
            if status == A5kuStatus.OK and setup.is_in and len(in_data) > setup.w_length:
                return [
                    A5kuFrame(
                        msg_type=A5kuMessageType.CONTROL_DONE,
                        req_id=frame.req_id,
                        arg=A5kuStatus.OVERFLOW,
                    )
                ]
            return [
                A5kuFrame(
                    msg_type=A5kuMessageType.CONTROL_DONE,
                    req_id=frame.req_id,
                    arg=int(status),
                    payload=in_data if (status == A5kuStatus.OK and setup.is_in) else b"",
                )
            ]

        if mtype == A5kuMessageType.OUT:
            status, accepted = self._handler.handle_out(frame.ep, frame.payload, frame.arg)
            return [
                A5kuFrame(
                    msg_type=A5kuMessageType.OUT_DONE,
                    ep=frame.ep,
                    req_id=frame.req_id,
                    arg=int(status),
                    payload=_U32_STRUCT.pack(accepted) if status == A5kuStatus.OK else b"",
                )
            ]

        # A5kuMessageType.IN
        status, data = self._handler.handle_in(frame.ep, frame.arg)
        if status == A5kuStatus.OK and len(data) > frame.arg:
            return [
                A5kuFrame(
                    msg_type=A5kuMessageType.IN_DONE,
                    ep=frame.ep,
                    req_id=frame.req_id,
                    arg=A5kuStatus.OVERFLOW,
                )
            ]
        return [
            A5kuFrame(
                msg_type=A5kuMessageType.IN_DONE,
                ep=frame.ep,
                req_id=frame.req_id,
                arg=int(status),
                payload=data if status == A5kuStatus.OK else b"",
            )
        ]


def recv_a5ku_frame(
    sock: socket.socket, decoder: A5kuStreamDecoder | None = None
) -> A5kuFrame | None:
    """Read one A5KU frame from a connected TCP socket, or ``None`` on clean EOF."""
    dec = decoder or A5kuStreamDecoder()
    while True:
        chunk = sock.recv(4096)
        if not chunk:
            return None
        frames = dec.feed(chunk)
        if frames:
            return frames[0]
