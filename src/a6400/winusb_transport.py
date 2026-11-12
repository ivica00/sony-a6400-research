"""Host-side WinUSB bulk transport for the E0402 always-on debugger.

The authored gadget module (not yet deployed) exposes a vendor-specific
interface (class 0xFF / subclass 0xDB / protocol 0x01) with one Bulk IN and one
Bulk OUT endpoint. Windows binds WinUSB through the Microsoft OS 1.0 compat-ID
descriptors built in :mod:`src.a6400.usb_debug_descriptors`, so PyUSB's
libusb-1.0 backend can open the interface with no manual driver installation.

Frames are exactly the protocol-v2 4096-byte packets; ``encode``/``decode`` stay
in :mod:`tools.camera_debugger`, so this module only moves bytes. It never
guesses a device: when the vendor interface is absent it raises
``TransportUnavailable`` and the caller falls back to the ext-command channel.
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FRAME_SIZE = 4096
VENDOR_CLASS = 0xFF
VENDOR_SUBCLASS = 0xDB
VENDOR_PROTOCOL = 0x01
DEFAULT_TIMEOUT_MS = 2000
SONY_VID = 0x054C
BUNDLED_LIBUSB = ROOT / 'Sony-PMCA-RE' / 'libusb-1.0.dll'


class TransportUnavailable(RuntimeError):
    """No WinUSB debugger interface is present (or libusb is unavailable)."""


def _libusb_backend():
    import usb.backend.libusb1
    if os.name == 'nt' and BUNDLED_LIBUSB.is_file():
        backend = usb.backend.libusb1.get_backend(find_library=lambda name: str(BUNDLED_LIBUSB))
        if backend is not None:
            return backend
    return usb.backend.libusb1.get_backend()


def _vendor_interface(configuration):
    """Return (interface, in_endpoint, out_endpoint) for the debugger interface."""
    for interface in configuration:
        if (interface.bInterfaceClass == VENDOR_CLASS
                and interface.bInterfaceSubClass == VENDOR_SUBCLASS
                and interface.bInterfaceProtocol == VENDOR_PROTOCOL):
            bulk_in = bulk_out = None
            for endpoint in interface:
                attributes = endpoint.bmAttributes & 0x03
                if attributes != 0x02:  # BULK
                    continue
                if endpoint.bEndpointAddress & 0x80:
                    bulk_in = endpoint
                else:
                    bulk_out = endpoint
            if bulk_in is None or bulk_out is None:
                raise TransportUnavailable('vendor interface is missing a bulk endpoint')
            return interface, bulk_in, bulk_out
    return None


def find_debugger_interface(backend=None, vendor_id=SONY_VID):
    """Locate the vendor interface; never opens an unrelated device."""
    import usb.core
    if backend is None:
        backend = _libusb_backend()
    if backend is None:
        raise TransportUnavailable('libusb backend unavailable (bundled DLL missing?)')
    for device in usb.core.find(find_all=True, idVendor=vendor_id, backend=backend):
        try:
            configuration = device.get_active_configuration()
        except Exception:
            continue
        found = _vendor_interface(configuration)
        if found is None:
            continue
        interface, bulk_in, bulk_out = found
        return {
            'device': device,
            'configuration': configuration,
            'interface': interface,
            'interface_number': interface.bInterfaceNumber,
            'in_endpoint': bulk_in.bEndpointAddress,
            'out_endpoint': bulk_out.bEndpointAddress,
            'in_max_packet': bulk_in.wMaxPacketSize,
            'out_max_packet': bulk_out.wMaxPacketSize,
            'bus': device.bus,
            'address': device.address,
            'idVendor': device.idVendor,
            'idProduct': device.idProduct,
        }
    return None


class WinUsbExchange:
    """Synchronous request/response exchange over the two bulk endpoints."""

    def __init__(self, device, interface_number, in_endpoint, out_endpoint,
                 timeout_ms=DEFAULT_TIMEOUT_MS):
        self.device = device
        self.interface_number = interface_number
        self.in_address = in_endpoint & 0x7F
        self.out_address = out_endpoint & 0x7F
        self.timeout_ms = timeout_ms
        self.claimed = False
        if device.is_kernel_driver_active(interface_number):
            try:
                device.detach_kernel_driver(interface_number)
            except Exception as exc:
                raise TransportUnavailable(f'kernel driver holds the interface: {exc}')
        device.set_configuration()
        device.claim_interface(interface_number)
        self.claimed = True

    def close(self):
        if self.claimed:
            try:
                self.device.release_interface(self.interface_number)
            finally:
                self.claimed = False

    def _write_frame(self, frame):
        if len(frame) != FRAME_SIZE:
            raise ValueError(f'expected a {FRAME_SIZE}-byte frame, got {len(frame)}')
        written = self.device.write(self.out_address, frame, self.timeout_ms)
        if written != FRAME_SIZE:
            raise TransportUnavailable(f'short bulk OUT write: {written}/{FRAME_SIZE}')
        return written

    def _read_frame(self):
        try:
            data = bytes(self.device.read(self.in_address, FRAME_SIZE, self.timeout_ms))
        except Exception as exc:
            raise TransportUnavailable(f'bulk IN read failed: {exc}')
        if len(data) != FRAME_SIZE:
            raise TransportUnavailable(f'short bulk IN read: {len(data)}/{FRAME_SIZE}')
        return data

    def __call__(self, frame):
        self._write_frame(frame)
        return self._read_frame()


class LoopbackExchange:
    """Test double: feeds frames through a callable instead of USB."""

    def __init__(self, handler):
        self.handler = handler

    def __call__(self, frame):
        return self.handler(bytes(frame))


def open_winusb_exchange(timeout_ms=DEFAULT_TIMEOUT_MS):
    """Open the debugger vendor interface; raises TransportUnavailable when absent."""
    found = find_debugger_interface()
    if found is None:
        raise TransportUnavailable('no Sony vendor debugger interface (0xff/0xdb/0x01)')
    try:
        exchange = WinUsbExchange(found['device'], found['interface_number'],
                                  found['in_endpoint'], found['out_endpoint'],
                                  timeout_ms=timeout_ms)
    except TransportUnavailable:
        raise
    except Exception as exc:
        raise TransportUnavailable(f'WinUSB open failed: {exc}')
    found['exchange'] = exchange
    return exchange, found
