import struct
import unittest

from src.a6400 import usb_debug_descriptors as d
from src.a6400.winusb_transport import (FRAME_SIZE, LoopbackExchange, TransportUnavailable,
                                        WinUsbExchange, _vendor_interface,
                                        find_debugger_interface)


class FakeEndpoint:
    def __init__(self, address, attributes=2, max_packet=512):
        self.bEndpointAddress = address
        self.bmAttributes = attributes
        self.wMaxPacketSize = max_packet


class FakeInterface:
    def __init__(self, number, klass=0xFF, subclass=0xDB, protocol=0x01, endpoints=()):
        self.bInterfaceNumber = number
        self.bInterfaceClass = klass
        self.bInterfaceSubClass = subclass
        self.bInterfaceProtocol = protocol
        self._endpoints = list(endpoints)

    def __iter__(self):
        return iter(self._endpoints)


class FakeConfiguration:
    def __init__(self, interfaces):
        self._interfaces = list(interfaces)

    def __iter__(self):
        return iter(self._interfaces)


class FakeDevice:
    def __init__(self, in_bytes=b'', write_short=False, read_short=False):
        self.in_bytes = in_bytes
        self.written = []
        self.write_short = write_short
        self.read_short = read_short
        self.configured = False
        self.claimed = []
        self.released = []
        self.kernel_active = False

    def is_kernel_driver_active(self, interface):
        return self.kernel_active

    def detach_kernel_driver(self, interface):
        self.kernel_active = False

    def set_configuration(self):
        self.configured = True

    def claim_interface(self, interface):
        self.claimed.append(interface)

    def release_interface(self, interface):
        self.released.append(interface)

    def write(self, address, data, timeout):
        self.written.append((address, bytes(data)))
        return len(data) - 1 if self.write_short else len(data)

    def read(self, address, size, timeout):
        data = self.in_bytes[:size]
        return data[:-1] if self.read_short else data


class VendorInterfaceDiscoveryTests(unittest.TestCase):
    def test_finds_the_vendor_interface_and_both_bulk_endpoints(self):
        interface = FakeInterface(3, endpoints=[FakeEndpoint(0x85), FakeEndpoint(0x05),
                                                FakeEndpoint(0x83, attributes=3)])
        found = _vendor_interface(FakeConfiguration([FakeInterface(0, klass=6, subclass=1, protocol=1), interface]))
        self.assertIsNotNone(found)
        selected, bulk_in, bulk_out = found
        self.assertIs(selected, interface)
        self.assertEqual((bulk_in.bEndpointAddress, bulk_out.bEndpointAddress), (0x85, 0x05))

    def test_ignores_interfaces_without_the_vendor_triple_or_bulk_pair(self):
        wrong_class = FakeInterface(1, klass=0x08, endpoints=[FakeEndpoint(0x85), FakeEndpoint(0x05)])
        no_out = FakeInterface(2, endpoints=[FakeEndpoint(0x85)])
        self.assertIsNone(_vendor_interface(FakeConfiguration([wrong_class])))
        with self.assertRaises(TransportUnavailable):
            _vendor_interface(FakeConfiguration([no_out]))
    def test_missing_device_returns_none(self):
        from unittest import mock
        try:
            import usb.core  # noqa: F401
        except ImportError:
            self.skipTest('pyusb not installed')
        with mock.patch('usb.core.find', return_value=[]):
            self.assertIsNone(find_debugger_interface(backend=object()))


class ExchangeTests(unittest.TestCase):
    def test_loopback_exchange_round_trips_frames(self):
        def echo(frame):
            self.assertEqual(len(frame), FRAME_SIZE)
            return frame[::-1]
        exchange = LoopbackExchange(echo)
        frame = bytes(range(256)) * (FRAME_SIZE // 256)
        self.assertEqual(exchange(frame), frame[::-1])

    def test_winusb_exchange_writes_the_frame_to_bulk_out_and_reads_bulk_in(self):
        response = b'R' * FRAME_SIZE
        device = FakeDevice(in_bytes=response)
        exchange = WinUsbExchange(device, 3, 0x85, 0x05)
        self.assertTrue(device.configured)
        self.assertEqual(device.claimed, [3])
        frame = b'Q' * FRAME_SIZE
        self.assertEqual(exchange(frame), response)
        self.assertEqual(device.written, [(0x05, frame)])
        exchange.close()
        self.assertEqual(device.released, [3])

    def test_short_transfers_and_wrong_frame_sizes_are_rejected(self):
        with self.assertRaises(TransportUnavailable):
            WinUsbExchange(FakeDevice(write_short=True), 3, 0x85, 0x05)(b'Q' * FRAME_SIZE)
        with self.assertRaises(TransportUnavailable):
            WinUsbExchange(FakeDevice(read_short=True), 3, 0x85, 0x05)(b'Q' * FRAME_SIZE)
        with self.assertRaises(ValueError):
            WinUsbExchange(FakeDevice(), 3, 0x85, 0x05)(b'short')

    def test_kernel_held_interface_is_detached_only_when_present(self):
        device = FakeDevice(in_bytes=b'R' * FRAME_SIZE)
        device.kernel_active = True
        exchange = WinUsbExchange(device, 3, 0x85, 0x05)
        self.assertFalse(device.kernel_active)
        exchange.close()


if __name__ == '__main__':
    unittest.main()
