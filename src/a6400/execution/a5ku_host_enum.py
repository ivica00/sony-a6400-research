"""A5KU host-side USB enumeration client and verified-descriptor gadget adapter.

Combines the clean-room A5KU USB-over-TCP wire protocol
(``src/a6400/execution/a5ku_protocol.py``, adapted from
``Oein/a5000-emulator`` ``docs/RE_USB_HOST_PATH.md`` §6.2) with the
hash-verified UVC+PTP descriptor validator
(``src/a6400/execution/usb_host_enum.py``).

All device descriptors must be supplied explicitly by the caller (no VID/PID
or configuration bytes are fabricated), and unsupported control/bulk requests
fail closed with ``A5kuStatus.STALL``.
"""

from __future__ import annotations

from dataclasses import dataclass
import socket
import struct
from typing import Any, Callable

from src.a6400.execution.a5ku_protocol import (
    A5KU_PROTOCOL_VERSION,
    A5kuFrame,
    A5kuMessageType,
    A5kuProtocolError,
    A5kuSpeed,
    A5kuStatus,
    A5kuStreamDecoder,
    UsbSetupPacket,
    make_hello_frame,
)
from src.a6400.execution.usb_host_enum import (
    DEFAULT_DESCRIPTOR_MANIFEST,
    DEFAULT_ENABLEMENT_MANIFEST,
    USB_DT_CONFIG,
    USB_DT_DEVICE,
    UsbConfiguration,
    load_descriptor_bytes,
    parse_configuration_descriptor,
    plan_set_configuration,
    select_uvc_ptp_configuration,
)

_DEVICE_DESC_SIZE = 18
_CONFIG_HEADER_SIZE = 9
_HELLO_ACK_STRUCT = struct.Struct("<IIII")
_U32_STRUCT = struct.Struct("<I")


class A5kuTransferError(RuntimeError):
    """Raised when an A5KU USB transfer completes with a non-OK status."""

    def __init__(self, status: A5kuStatus, message: str) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class A5kuDeviceDescriptor:
    """Parsed 18-byte USB Device Descriptor."""

    bcd_usb: int
    device_class: int
    device_subclass: int
    device_protocol: int
    max_packet_size_0: int
    id_vendor: int
    id_product: int
    bcd_device: int
    num_configurations: int

    @classmethod
    def parse(cls, raw: bytes) -> "A5kuDeviceDescriptor":
        """Parse and validate an 18-byte USB Device Descriptor."""
        if len(raw) < _DEVICE_DESC_SIZE or raw[0] < _DEVICE_DESC_SIZE or raw[1] != USB_DT_DEVICE:
            raise A5kuProtocolError(
                f"Invalid USB device descriptor (len={len(raw)}, "
                f"bLength={raw[0] if raw else None}, bDescriptorType={raw[1] if len(raw) > 1 else None})"
            )
        bcd_usb, dev_cls, dev_sub, dev_proto, mps0, vid, pid, bcd_dev, num_cfg = (
            struct.unpack_from("<HBBBBHHH3xB", raw, 2)
        )
        return cls(
            bcd_usb=bcd_usb,
            device_class=dev_cls,
            device_subclass=dev_sub,
            device_protocol=dev_proto,
            max_packet_size_0=mps0,
            id_vendor=vid,
            id_product=pid,
            bcd_device=bcd_dev,
            num_configurations=num_cfg,
        )


@dataclass(frozen=True)
class A5kuEnumerationResult:
    """Result of the 6-step A5KU host enumeration sequence."""

    speed: A5kuSpeed
    address: int
    device_descriptor: A5kuDeviceDescriptor
    configuration: UsbConfiguration
    set_config_plan: dict[str, Any] | None


class A5kuVerifiedDescriptorHandler:
    """Fail-closed A5KU gadget handler serving an explicit device + verified config."""

    def __init__(
        self,
        device_descriptor: bytes,
        config_descriptor: bytes | None = None,
    ) -> None:
        A5kuDeviceDescriptor.parse(device_descriptor)
        self.device_descriptor = bytes(device_descriptor)
        if config_descriptor is None:
            config_descriptor, _ = load_descriptor_bytes()
        self.config_descriptor = bytes(config_descriptor)
        self.reset_count = 0
        self.device_address: int | None = None
        self.selected_configuration: int | None = None

    def handle_reset(self) -> tuple[A5kuStatus, int]:
        self.reset_count += 1
        self.device_address = None
        self.selected_configuration = None
        return A5kuStatus.OK, A5kuSpeed.HIGH

    def handle_control(
        self, setup: UsbSetupPacket, out_data: bytes
    ) -> tuple[A5kuStatus, bytes]:
        # Standard Device-to-Host GET_DESCRIPTOR
        if setup.bm_request_type == 0x80 and setup.b_request == 0x06:
            desc_type = (setup.w_value >> 8) & 0xFF
            desc_index = setup.w_value & 0xFF
            if desc_type == USB_DT_DEVICE and desc_index == 0:
                return A5kuStatus.OK, self.device_descriptor[: setup.w_length]
            if desc_type == USB_DT_CONFIG and desc_index == 0:
                return A5kuStatus.OK, self.config_descriptor[: setup.w_length]
            return A5kuStatus.STALL, b""

        # Standard Host-to-Device SET_ADDRESS
        if setup.bm_request_type == 0x00 and setup.b_request == 0x05 and not out_data:
            self.device_address = setup.w_value & 0x7F
            return A5kuStatus.OK, b""

        # Standard Host-to-Device SET_CONFIGURATION
        if setup.bm_request_type == 0x00 and setup.b_request == 0x09 and not out_data:
            expected_cfg = self.config_descriptor[5]
            if setup.w_value != expected_cfg:
                return A5kuStatus.STALL, b""
            self.selected_configuration = setup.w_value
            return A5kuStatus.OK, b""

        return A5kuStatus.STALL, b""

    def handle_out(
        self, ep: int, data: bytes, flags: int
    ) -> tuple[A5kuStatus, int]:
        return A5kuStatus.STALL, 0

    def handle_in(self, ep: int, max_length: int) -> tuple[A5kuStatus, bytes]:
        return A5kuStatus.STALL, b""


class A5kuHostClient:
    """Synchronous A5KU host client for enumeration and control transfers."""

    def __init__(
        self,
        exchange_fn: Callable[[A5kuFrame], list[A5kuFrame]],
    ) -> None:
        self._exchange = exchange_fn
        self._next_id = 1
        self.events: list[A5kuFrame] = []

    @classmethod
    def from_socket(cls, sock: socket.socket) -> "A5kuHostClient":
        """Create an ``A5kuHostClient`` bound to a connected TCP socket."""
        decoder = A5kuStreamDecoder()

        def _exchange(frame: A5kuFrame) -> list[A5kuFrame]:
            sock.sendall(frame.encode())
            if frame.msg_type == A5kuMessageType.CANCEL:
                return []
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    raise ConnectionError("A5KU socket closed by device")
                frames = decoder.feed(chunk)
                if frames:
                    return frames

        return cls(_exchange)

    def _alloc_id(self) -> int:
        req_id = self._next_id
        self._next_id += 1
        return req_id

    def _request(self, frame: A5kuFrame, expected_reply: A5kuMessageType) -> A5kuFrame:
        replies = self._exchange(frame)
        for reply in replies:
            if reply.msg_type == A5kuMessageType.EVENT:
                self.events.append(reply)
                continue
            if reply.msg_type == expected_reply and reply.req_id == frame.req_id:
                status = A5kuStatus(reply.arg)
                if status != A5kuStatus.OK:
                    raise A5kuTransferError(
                        status,
                        f"A5KU {expected_reply.name} failed with status={status.name}",
                    )
                return reply
        raise A5kuProtocolError(
            f"Missing expected A5KU reply {expected_reply.name} for req_id={frame.req_id}"
        )

    def hello(self) -> tuple[bool, int, A5kuSpeed]:
        """Perform HELLO/HELLO_ACK handshake and return ``(attached, generation, speed)``."""
        frame = make_hello_frame(req_id=self._alloc_id(), version=A5KU_PROTOCOL_VERSION)
        reply = self._request(frame, A5kuMessageType.HELLO_ACK)
        if len(reply.payload) != _HELLO_ACK_STRUCT.size:
            raise A5kuProtocolError(f"Invalid HELLO_ACK payload length {len(reply.payload)}")
        version, attached, generation, speed = _HELLO_ACK_STRUCT.unpack(reply.payload)
        if version != A5KU_PROTOCOL_VERSION:
            raise A5kuProtocolError(f"Unsupported A5KU version {version}")
        return bool(attached), generation, A5kuSpeed(speed)

    def reset(self) -> A5kuSpeed:
        """Issue USB bus RESET and return negotiated bus speed."""
        frame = A5kuFrame(msg_type=A5kuMessageType.RESET, req_id=self._alloc_id())
        reply = self._request(frame, A5kuMessageType.RESET_DONE)
        if len(reply.payload) != _U32_STRUCT.size:
            raise A5kuProtocolError(f"Invalid RESET_DONE payload length {len(reply.payload)}")
        (speed,) = _U32_STRUCT.unpack(reply.payload)
        return A5kuSpeed(speed)

    def control_in(
        self,
        bm_request_type: int,
        b_request: int,
        w_value: int,
        w_index: int,
        w_length: int,
    ) -> bytes:
        """Issue a USB Control IN transfer over A5KU."""
        setup = UsbSetupPacket(
            bm_request_type=bm_request_type | 0x80,
            b_request=b_request,
            w_value=w_value,
            w_index=w_index,
            w_length=w_length,
        )
        frame = A5kuFrame(
            msg_type=A5kuMessageType.CONTROL,
            req_id=self._alloc_id(),
            payload=setup.encode(),
        )
        reply = self._request(frame, A5kuMessageType.CONTROL_DONE)
        return reply.payload

    def control_out(
        self,
        bm_request_type: int,
        b_request: int,
        w_value: int,
        w_index: int,
        data: bytes = b"",
    ) -> None:
        """Issue a USB Control OUT transfer over A5KU."""
        setup = UsbSetupPacket(
            bm_request_type=bm_request_type & 0x7F,
            b_request=b_request,
            w_value=w_value,
            w_index=w_index,
            w_length=len(data),
        )
        frame = A5kuFrame(
            msg_type=A5kuMessageType.CONTROL,
            req_id=self._alloc_id(),
            payload=setup.encode() + data,
        )
        self._request(frame, A5kuMessageType.CONTROL_DONE)

    def set_interface(self, interface: int, alt_setting: int) -> None:
        """Issue a standard USB SET_INTERFACE request."""
        self.control_out(0x01, 0x0B, alt_setting, interface)

    def bulk_in(self, ep: int, max_length: int) -> bytes:
        """Issue an A5KU IN transfer on ``ep`` up to ``max_length`` bytes."""
        frame = A5kuFrame(
            msg_type=A5kuMessageType.IN,
            ep=ep & 0xFF,
            req_id=self._alloc_id(),
            arg=max_length,
        )
        reply = self._request(frame, A5kuMessageType.IN_DONE)
        return reply.payload

    def enumerate_uvc_ptp(
        self,
        address: int = 1,
        *,
        plan_set_config: bool | None = None,
    ) -> A5kuEnumerationResult:
        """Execute the RE_USB_HOST_PATH §6.2 enumeration sequence and validate UVC+PTP."""
        speed = self.reset()
        dev_raw = self.control_in(0x80, 0x06, (USB_DT_DEVICE << 8) | 0, 0, _DEVICE_DESC_SIZE)
        dev_desc = A5kuDeviceDescriptor.parse(dev_raw)
        self.control_out(0x00, 0x05, address & 0x7F, 0)
        cfg_hdr = self.control_in(0x80, 0x06, (USB_DT_CONFIG << 8) | 0, 0, _CONFIG_HEADER_SIZE)
        if len(cfg_hdr) < _CONFIG_HEADER_SIZE or cfg_hdr[1] != USB_DT_CONFIG:
            raise A5kuProtocolError("Invalid USB configuration descriptor header")
        total_length = struct.unpack_from("<H", cfg_hdr, 2)[0]
        cfg_raw = self.control_in(0x80, 0x06, (USB_DT_CONFIG << 8) | 0, 0, total_length)
        configuration = select_uvc_ptp_configuration(parse_configuration_descriptor(cfg_raw))
        self.control_out(0x00, 0x09, configuration.value, 0)
        if plan_set_config is None:
            plan_set_config = (
                DEFAULT_DESCRIPTOR_MANIFEST.is_file()
                and DEFAULT_ENABLEMENT_MANIFEST.is_file()
            )
        plan = plan_set_configuration(configuration.value) if plan_set_config else None
        return A5kuEnumerationResult(
            speed=speed,
            address=address & 0x7F,
            device_descriptor=dev_desc,
            configuration=configuration,
            set_config_plan=plan,
        )
