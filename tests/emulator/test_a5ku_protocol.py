"""Unit tests for the clean-room A5KU USB-over-TCP protocol codec and session."""

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

from src.a6400.execution.a5ku_protocol import (
    A5KU_HEADER_SIZE,
    A5KU_MAGIC,
    A5KU_PROTOCOL_VERSION,
    A5kuDeviceSession,
    A5kuEvent,
    A5kuFrame,
    A5kuMessageType,
    A5kuProtocolError,
    A5kuSpeed,
    A5kuStatus,
    A5kuStreamDecoder,
    UsbSetupPacket,
    decode_frame,
    make_hello_frame,
    parse_control_payload,
)


class _StubGadgetHandler:
    """Minimal explicit gadget handler for protocol session tests."""

    def __init__(self) -> None:
        self.resets = 0
        self.controls: list[tuple[UsbSetupPacket, bytes]] = []
        self.outs: list[tuple[int, bytes, int]] = []

    def handle_reset(self) -> tuple[A5kuStatus, int]:
        self.resets += 1
        return A5kuStatus.OK, A5kuSpeed.HIGH

    def handle_control(
        self, setup: UsbSetupPacket, out_data: bytes
    ) -> tuple[A5kuStatus, bytes]:
        self.controls.append((setup, out_data))
        if setup.is_in and setup.b_request == 0x06:  # GET_DESCRIPTOR
            return A5kuStatus.OK, b"\x12\x01\x00\x02"[: setup.w_length]
        if not setup.is_in and setup.b_request == 0x09:  # SET_CONFIGURATION
            return A5kuStatus.OK, b""
        return A5kuStatus.STALL, b""

    def handle_out(
        self, ep: int, data: bytes, flags: int
    ) -> tuple[A5kuStatus, int]:
        self.outs.append((ep, data, flags))
        return A5kuStatus.OK, len(data)

    def handle_in(self, ep: int, max_length: int) -> tuple[A5kuStatus, bytes]:
        return A5kuStatus.OK, b"\xAA\xBB\xCC"[:max_length]


class TestA5kuCodec(unittest.TestCase):
    def test_hello_roundtrip_and_header_size(self) -> None:
        frame = make_hello_frame(req_id=42)
        wire = frame.encode()
        self.assertEqual(len(wire), A5KU_HEADER_SIZE + 4)
        self.assertEqual(wire[:2], b"AU")
        magic, msg_type, ep, req_id, length, arg = struct.unpack_from("<HBBIII", wire, 0)
        self.assertEqual(magic, A5KU_MAGIC)
        self.assertEqual(msg_type, A5kuMessageType.HELLO)
        self.assertEqual(ep, 0)
        self.assertEqual(req_id, 42)
        self.assertEqual(length, 4)
        self.assertEqual(arg, 0)

        decoded, consumed = decode_frame(wire)
        self.assertEqual(consumed, len(wire))
        self.assertEqual(decoded, frame)

    def test_bad_magic_fails_closed(self) -> None:
        bad = b"XX" + b"\x00" * 14
        with self.assertRaises(A5kuProtocolError):
            decode_frame(bad)

    def test_stream_decoder_handles_fragmented_chunks(self) -> None:
        f1 = make_hello_frame(req_id=1)
        f2 = A5kuFrame(msg_type=A5kuMessageType.OUT, ep=0x02, req_id=2, arg=1, payload=b"hello")
        wire = f1.encode() + f2.encode()
        dec = A5kuStreamDecoder()
        out: list[A5kuFrame] = []
        for idx in range(0, len(wire), 3):
            out.extend(dec.feed(wire[idx : idx + 3]))
        self.assertEqual(out, [f1, f2])

    def test_parse_control_payload_validates_direction_and_length(self) -> None:
        in_setup = UsbSetupPacket(0x80, 0x06, 0x0100, 0x0000, 18)
        parsed, extra = parse_control_payload(in_setup.encode())
        self.assertEqual(parsed, in_setup)
        self.assertEqual(extra, b"")

        with self.assertRaises(A5kuProtocolError):
            parse_control_payload(in_setup.encode() + b"\x01")

        out_setup = UsbSetupPacket(0x21, 0x01, 0x0000, 0x0001, 3)
        parsed_out, data = parse_control_payload(out_setup.encode() + b"\x11\x22\x33")
        self.assertEqual(parsed_out, out_setup)
        self.assertEqual(data, b"\x11\x22\x33")


class TestA5kuDeviceSession(unittest.TestCase):
    def test_detached_fails_closed_with_nodev(self) -> None:
        session = A5kuDeviceSession(_StubGadgetHandler(), attached=False)
        replies = session.handle_frame(A5kuFrame(msg_type=A5kuMessageType.RESET, req_id=7))
        self.assertEqual(len(replies), 1)
        self.assertEqual(replies[0].msg_type, A5kuMessageType.RESET_DONE)
        self.assertEqual(replies[0].req_id, 7)
        self.assertEqual(replies[0].arg, A5kuStatus.NODEV)

    def test_hello_attach_control_out_in_and_detach(self) -> None:
        handler = _StubGadgetHandler()
        session = A5kuDeviceSession(handler, attached=False)

        ack = session.handle_frame(make_hello_frame(req_id=1))[0]
        self.assertEqual(ack.msg_type, A5kuMessageType.HELLO_ACK)
        ver, attached, gen, speed = struct.unpack("<IIII", ack.payload)
        self.assertEqual((ver, attached, gen, speed), (A5KU_PROTOCOL_VERSION, 0, 0, 0))

        ev_attach = session.attach(A5kuSpeed.HIGH)[0]
        self.assertEqual(ev_attach.msg_type, A5kuMessageType.EVENT)
        self.assertEqual(ev_attach.arg, A5kuEvent.ATTACHED)
        self.assertEqual(struct.unpack("<II", ev_attach.payload), (1, A5kuSpeed.HIGH))

        rst = session.handle_frame(A5kuFrame(msg_type=A5kuMessageType.RESET, req_id=2))[0]
        self.assertEqual(rst.arg, A5kuStatus.OK)
        self.assertEqual(struct.unpack("<I", rst.payload)[0], A5kuSpeed.HIGH)

        get_desc = UsbSetupPacket(0x80, 0x06, 0x0100, 0x0000, 4).encode()
        ctl = session.handle_frame(
            A5kuFrame(msg_type=A5kuMessageType.CONTROL, req_id=3, payload=get_desc)
        )[0]
        self.assertEqual(ctl.arg, A5kuStatus.OK)
        self.assertEqual(ctl.payload, b"\x12\x01\x00\x02")

        out_done = session.handle_frame(
            A5kuFrame(msg_type=A5kuMessageType.OUT, ep=0x02, req_id=4, payload=b"ABCD")
        )[0]
        self.assertEqual(out_done.arg, A5kuStatus.OK)
        self.assertEqual(struct.unpack("<I", out_done.payload)[0], 4)

        in_done = session.handle_frame(
            A5kuFrame(msg_type=A5kuMessageType.IN, ep=0x81, req_id=5, arg=2)
        )[0]
        self.assertEqual(in_done.arg, A5kuStatus.OK)
        self.assertEqual(in_done.payload, b"\xAA\xBB")

        ev_detach = session.detach()[0]
        self.assertEqual(ev_detach.arg, A5kuEvent.DETACHED)

    def test_loopback_tcp_roundtrip(self) -> None:
        handler = _StubGadgetHandler()
        session = A5kuDeviceSession(handler, attached=True, speed=A5kuSpeed.HIGH)

        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]

        def _serve_once() -> None:
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

        thread = threading.Thread(target=_serve_once, daemon=True)
        thread.start()
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=5.0) as client:
                client.sendall(make_hello_frame(req_id=9).encode())
                dec = A5kuStreamDecoder()
                frames: list[A5kuFrame] = []
                while not frames:
                    frames.extend(dec.feed(client.recv(4096)))
                self.assertEqual(frames[0].msg_type, A5kuMessageType.HELLO_ACK)
                self.assertEqual(frames[0].req_id, 9)
        finally:
            server.close()
            thread.join(timeout=2.0)


if __name__ == "__main__":
    unittest.main()
