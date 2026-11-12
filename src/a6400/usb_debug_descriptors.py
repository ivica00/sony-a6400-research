"""Offline USB contracts for the E0402 composite WinUSB debugger interface.

This module builds and validates the pieces the authored gadget module must add
to whichever USB configuration the camera is currently using:

* a vendor-specific interface (class 0xFF / subclass 0xDB / protocol 0x01) with
  one Bulk IN and one Bulk OUT endpoint;
* the Microsoft OS 1.0 String Descriptor (string index 0xEE, ``MSFT100``) and
  the Extended Compat ID descriptor carrying ``WINUSB`` so Windows binds
  ``WinUSB.sys`` without a manual INF;
* a pure EP0 reply model for those two requests.

Everything here is host-side and offline: it parses/merges captured or synthetic
configuration bytes and never guesses a live kernel address. The current base
configurations are documented in E0387 (PTP + UVC) and the stock MSC config.
"""
from __future__ import annotations

import struct

VENDOR_INTERFACE_CLASS = 0xFF
VENDOR_INTERFACE_SUBCLASS = 0xDB
VENDOR_INTERFACE_PROTOCOL = 0x01
BULK_IN_ADDRESS = 0x85
BULK_OUT_ADDRESS = 0x05
HS_BULK_MAX_PACKET = 512

MS_OS_STRING_INDEX = 0xEE
MS_OS_VENDOR_CODE = 0x01
MS_OS_COMPAT_INDEX = 0x0004
MS_OS_SIGNATURE = 'MSFT100'
WINUSB_COMPATIBLE_ID = b'WINUSB\0\0'
MS_OS_20_VENDOR_CODE = 0x02
MS_OS_20_SIGNATURE = 'MSFT20'
MS_OS_20_DESCRIPTOR_SET_INDEX = 0x0007
MS_OS_20_CONFIGURATION_SUBSET_INDEX = 0x0008
MS_OS_20_WINDOWS_VERSION_8_1 = 0x06030000
MS_OS_20_FEATURE_COMPATIBLE_ID = 0x0003
MS_OS_20_REQUIRED_BCD_USB = 0x0210
MS_OS_20_DESCRIPTOR_SET = 0x0000
MS_OS_20_CONFIGURATION_SUBSET = 0x0001
MS_OS_20_FUNCTION_SUBSET = 0x0002

DESCRIPTOR_DEVICE = 0x01
DESCRIPTOR_CONFIG = 0x02
DESCRIPTOR_STRING = 0x03
DESCRIPTOR_INTERFACE = 0x04
DESCRIPTOR_ENDPOINT = 0x05
ENDPOINT_TYPE_BULK = 0x02


class DescriptorError(ValueError):
    """The descriptor bytes are not a valid base for the debugger interface."""


def _walk(config: bytes):
    """Yield (offset, length, type) for each descriptor in a configuration blob."""
    if len(config) < 9 or config[1] != DESCRIPTOR_CONFIG:
        raise DescriptorError('not a configuration descriptor')
    declared = struct.unpack_from('<H', config, 2)[0]
    if declared > len(config):
        raise DescriptorError(f'truncated configuration: {declared} > {len(config)}')
    offset = 0
    while offset < declared:
        if offset + 2 > declared:
            raise DescriptorError('truncated descriptor header')
        length = config[offset]
        if length < 2 or offset + length > declared:
            raise DescriptorError(f'invalid descriptor length {length} at {offset}')
        yield offset, length, config[offset + 1]
        offset += length


def existing_endpoint_addresses(config: bytes) -> set[int]:
    return {config[offset + 2] for offset, length, kind in _walk(config)
            if kind == DESCRIPTOR_ENDPOINT and length >= 7}


def existing_interface_numbers(config: bytes) -> list[int]:
    return [config[offset + 2] for offset, length, kind in _walk(config)
            if kind == DESCRIPTOR_INTERFACE and length >= 9]


def vendor_interface_bytes(interface_number: int, in_address: int = BULK_IN_ADDRESS,
                           out_address: int = BULK_OUT_ADDRESS,
                           string_index: int = 0) -> bytes:
    if not 0 <= interface_number <= 0xFF:
        raise DescriptorError('interface number outside one byte')
    if in_address & 0x80 == 0 or out_address & 0x80:
        raise DescriptorError('bulk IN must be 0x80|n and bulk OUT must not')
    interface = struct.pack('<BBBBBBBBB', 9, DESCRIPTOR_INTERFACE, interface_number, 0, 2,
                            VENDOR_INTERFACE_CLASS, VENDOR_INTERFACE_SUBCLASS,
                            VENDOR_INTERFACE_PROTOCOL, string_index)
    endpoint_in = struct.pack('<BBBBHB', 7, DESCRIPTOR_ENDPOINT, in_address,
                              ENDPOINT_TYPE_BULK, HS_BULK_MAX_PACKET, 0)
    endpoint_out = struct.pack('<BBBBHB', 7, DESCRIPTOR_ENDPOINT, out_address,
                               ENDPOINT_TYPE_BULK, HS_BULK_MAX_PACKET, 0)
    return interface + endpoint_in + endpoint_out


def merge_vendor_interface(config: bytes, interface_number: int | None = None,
                           in_address: int = BULK_IN_ADDRESS,
                           out_address: int = BULK_OUT_ADDRESS) -> dict:
    """Append the debugger interface to a full configuration descriptor.

    Returns the merged bytes plus a receipt. Refuses endpoint/interface number
    collisions and any structural inconsistency instead of guessing.
    """
    interfaces = existing_interface_numbers(config)
    endpoints = existing_endpoint_addresses(config)
    if not interfaces:
        raise DescriptorError('base configuration has no interface')
    if interface_number is None:
        interface_number = max(interfaces) + 1
    if interface_number in interfaces:
        raise DescriptorError(f'interface number {interface_number} already used')
    if interface_number > 0xFF:
        raise DescriptorError('no free interface number')
    for address, name in ((in_address, 'IN'), (out_address, 'OUT')):
        if address in endpoints:
            raise DescriptorError(f'endpoint 0x{address:02x} ({name}) already used')
    addition = vendor_interface_bytes(interface_number, in_address, out_address)
    base_total = struct.unpack_from('<H', config, 2)[0]
    total = base_total + len(addition)
    if total > 0xFFFF:
        raise DescriptorError('merged configuration exceeds 65535 bytes')
    if config[4] != len(set(interfaces)):
        raise DescriptorError('bNumInterfaces disagrees with the interface descriptors')
    merged = bytearray(config[:base_total])
    merged[2:4] = struct.pack('<H', total)
    merged[4] = max(config[4], interface_number + 1)
    merged.extend(addition)
    return {
        'bytes': bytes(merged),
        'interface_number': interface_number,
        'in_endpoint': in_address,
        'out_endpoint': out_address,
        'added_bytes': len(addition),
        'base_total_length': base_total,
        'total_length': total,
        'base_interfaces': interfaces,
        'base_endpoints': sorted(endpoints),
    }


def ms_os_string_descriptor(vendor_code: int = MS_OS_VENDOR_CODE) -> bytes:
    if not 0 < vendor_code <= 0xFF:
        raise DescriptorError('vendor code outside one byte')
    signature = MS_OS_SIGNATURE.encode('utf-16-le')  # 14 bytes, no terminator
    body = signature + bytes([vendor_code, 0])
    return bytes([len(body) + 2, DESCRIPTOR_STRING]) + body


def ms_os_compat_id_descriptor(interface_number: int,
                               compatible_id: bytes = WINUSB_COMPATIBLE_ID) -> bytes:
    if not 0 <= interface_number <= 0xFF:
        raise DescriptorError('interface number outside one byte')
    if len(compatible_id) != 8:
        raise DescriptorError('compatible ID must be exactly 8 bytes')
    section = struct.pack('<BB', interface_number, 0) + compatible_id + b'\0' * 8 + b'\0' * 6
    header = struct.pack('<IHHB', 0, 0x0100, MS_OS_COMPAT_INDEX, 1) + b'\0' * 7
    body = header + section
    return struct.pack('<I', len(body)) + body[4:]


def ms_os_20_string_descriptor(vendor_code: int = MS_OS_20_VENDOR_CODE) -> bytes:
    """Microsoft OS 2.0 String Descriptor: 18 bytes, ``MSFT20`` + NUL + vendor code."""
    if not 0 < vendor_code <= 0xFF:
        raise DescriptorError('vendor code outside one byte')
    signature = (MS_OS_20_SIGNATURE + '\0').encode('utf-16-le')  # 14 bytes
    body = signature + bytes([vendor_code, 0])
    return bytes([len(body) + 2, DESCRIPTOR_STRING]) + body


def ms_os_20_descriptor_set(compatible_id: bytes = WINUSB_COMPATIBLE_ID) -> bytes:
    """Device-level Microsoft OS 2.0 descriptor set with a WINUSB compatible ID.

    The set is returned for a device-recipient vendor request with
    ``wIndex = 0x0007``; no configuration subset is needed for a device-level
    compatible ID feature. The device must report ``bcdUSB >= 0x0210`` for
    Windows to issue the request.
    """
    if len(compatible_id) != 8:
        raise DescriptorError('compatible ID must be exactly 8 bytes')
    feature = struct.pack('<HH', 20, MS_OS_20_FEATURE_COMPATIBLE_ID) + compatible_id + b'\0' * 8
    total = 10 + len(feature)
    header = struct.pack('<HHIH', total, 0x0000, MS_OS_20_WINDOWS_VERSION_8_1, total)
    return header + feature


def ms_os_20_composite_descriptor_set(configuration_value: int = 1,
                                      interface_number: int = 1,
                                      compatible_id: bytes = WINUSB_COMPATIBLE_ID) -> bytes:
    """MS OS 2.0 set with a configuration subset and one function subset.

    Scope: exactly one function subset for ``interface_number`` with
    ``bInterfaceCount = 1`` and the ``WINUSB`` compatible ID. This is what keeps
    WinUSB bound to the vendor interface instead of the composite parent.

    Layout: descriptor-set header (10) + configuration subset header (8) +
    function subset header (8) + compatible-ID feature (20) = 46 bytes.
    """
    if not 0 <= configuration_value <= 0xFF:
        raise DescriptorError('configuration value outside one byte')
    if not 0 <= interface_number <= 0xFF:
        raise DescriptorError('interface number outside one byte')
    if len(compatible_id) != 8:
        raise DescriptorError('compatible ID must be exactly 8 bytes')
    feature = struct.pack('<HH', 20, MS_OS_20_FEATURE_COMPATIBLE_ID) + compatible_id + b'\0' * 8
    function_subset = struct.pack('<HHBBH', 8 + len(feature), MS_OS_20_FUNCTION_SUBSET,
                                  interface_number, 0, 8 + len(feature)) + feature
    configuration_subset = struct.pack('<HHBBH', 8 + len(function_subset),
                                       MS_OS_20_CONFIGURATION_SUBSET,
                                       configuration_value, 0, 8 + len(function_subset)) + function_subset
    body = configuration_subset
    total = 10 + len(body)
    header = struct.pack('<HHIH', total, MS_OS_20_DESCRIPTOR_SET, MS_OS_20_WINDOWS_VERSION_8_1, total)
    return header + body


def validate_winusb_20_composite_binding(descriptor_set: bytes,
                                         configuration_value: int = 1,
                                         interface_number: int = 1) -> dict:
    """Validate the composite MS OS 2.0 set byte-for-byte (lengths, counts)."""
    if len(descriptor_set) < 10:
        raise DescriptorError('descriptor set shorter than its header')
    length, kind, version, total = struct.unpack_from('<HHIH', descriptor_set, 0)
    if kind != MS_OS_20_DESCRIPTOR_SET or version != MS_OS_20_WINDOWS_VERSION_8_1:
        raise DescriptorError('descriptor set header is invalid')
    if length != len(descriptor_set) or total != len(descriptor_set):
        raise DescriptorError('descriptor set lengths are inconsistent')
    offset = 10
    if offset + 8 > len(descriptor_set):
        raise DescriptorError('missing configuration subset header')
    config_length, config_kind, config_value, config_reserved = struct.unpack_from(
        '<HHBB', descriptor_set, offset)
    if config_kind != MS_OS_20_CONFIGURATION_SUBSET or config_reserved != 0:
        raise DescriptorError('configuration subset header is invalid')
    if config_value != configuration_value:
        raise DescriptorError('configuration value mismatch')
    config_total = struct.unpack_from('<H', descriptor_set, offset + 6)[0]
    if config_length != config_total or offset + config_length > len(descriptor_set):
        raise DescriptorError('configuration subset length mismatch')
    offset += 8
    function_length, function_kind, first_interface, function_reserved = struct.unpack_from(
        '<HHBB', descriptor_set, offset)
    if function_kind != MS_OS_20_FUNCTION_SUBSET or function_reserved != 0:
        raise DescriptorError('function subset header is invalid')
    if first_interface != interface_number:
        raise DescriptorError('function subset first interface mismatch')
    function_total = struct.unpack_from('<H', descriptor_set, offset + 6)[0]
    if function_length != function_total or function_length != config_length - 8:
        raise DescriptorError('function subset length mismatch')
    offset += 8
    feature_length, feature_type = struct.unpack_from('<HH', descriptor_set, offset)
    if feature_type != MS_OS_20_FEATURE_COMPATIBLE_ID or feature_length != 20:
        raise DescriptorError('compatible ID feature descriptor is invalid')
    if offset + feature_length != len(descriptor_set):
        raise DescriptorError('compatible ID feature does not end the set')
    compatible = descriptor_set[offset + 4:offset + 12]
    if compatible != WINUSB_COMPATIBLE_ID or any(descriptor_set[offset + 12:offset + 20]):
        raise DescriptorError('compatible ID is not WINUSB with a zero sub-ID')
    return {'verified': True, 'bytes': len(descriptor_set),
            'configuration_value': config_value, 'interface_number': first_interface,
            'interface_count': 1, 'compatible_id': 'WINUSB'}


def ms_os_20_vendor_reply(setup: bytes, descriptor_set: bytes,
                          vendor_code: int = MS_OS_20_VENDOR_CODE) -> dict:
    """Model the device-recipient vendor request that returns the OS 2.0 set."""
    if len(setup) != 8:
        raise DescriptorError('setup packet must be 8 bytes')
    bm_request_type, request, value, index, length = struct.unpack('<BBHHH', setup)
    if (bm_request_type == 0xC0 and request == vendor_code and value == 0
            and index == MS_OS_20_DESCRIPTOR_SET_INDEX):
        return {'handled': True, 'name': 'ms_os_20_descriptor_set',
                'payload': descriptor_set[:length]}
    if (bm_request_type == 0xC0 and request == vendor_code and value == 0
            and index == MS_OS_20_CONFIGURATION_SUBSET_INDEX):
        subset = descriptor_set[10:] if len(descriptor_set) > 10 else b''
        return {'handled': True, 'name': 'ms_os_20_configuration_subset',
                'payload': subset[:length]}
    return {'handled': False, 'name': 'other'}


def validate_winusb_20_binding(device_descriptor: bytes, descriptor_set: bytes) -> dict:
    """Validate the OS 2.0 set and the device descriptor preconditions."""
    if len(device_descriptor) < 4 or device_descriptor[1] != DESCRIPTOR_DEVICE:
        raise DescriptorError('invalid device descriptor')
    bcd_usb = struct.unpack_from('<H', device_descriptor, 2)[0]
    if bcd_usb < MS_OS_20_REQUIRED_BCD_USB:
        raise DescriptorError(
            f'bcdUSB 0x{bcd_usb:04x} below the MS OS 2.0 minimum 0x0210')
    if len(descriptor_set) < 10:
        raise DescriptorError('descriptor set shorter than its header')
    length, kind, version, total = struct.unpack_from('<HHIH', descriptor_set, 0)
    if kind != 0 or version != MS_OS_20_WINDOWS_VERSION_8_1 or length != len(descriptor_set):
        raise DescriptorError('descriptor set header is invalid')
    if total != length:
        raise DescriptorError('descriptor set total length mismatch')
    offset = 10
    compatible = None
    while offset + 4 <= len(descriptor_set):
        feature_length, feature_type = struct.unpack_from('<HH', descriptor_set, offset)
        if feature_length < 4 or offset + feature_length > len(descriptor_set):
            raise DescriptorError('feature descriptor length is invalid')
        if feature_type == MS_OS_20_FEATURE_COMPATIBLE_ID:
            if feature_length != 20:
                raise DescriptorError('compatible ID feature must be 20 bytes')
            compatible = descriptor_set[offset + 4:offset + 12]
            if any(descriptor_set[offset + 12:offset + 20]):
                raise DescriptorError('compatible ID sub-ID must be zero')
        offset += feature_length
    if offset != len(descriptor_set):
        raise DescriptorError('feature descriptors do not fill the descriptor set')
    if compatible != WINUSB_COMPATIBLE_ID:
        raise DescriptorError('descriptor set does not advertise WINUSB')
    return {'verified': True, 'bcdUSB': bcd_usb,
            'compatible_id': compatible.decode('latin1').rstrip('\0'),
            'descriptor_set_bytes': len(descriptor_set)}


def ep0_reply(setup: bytes, interface_number: int,
              vendor_code: int = MS_OS_VENDOR_CODE) -> dict:
    """Model the EP0 replies for the MS-OS requests; fail closed otherwise."""
    if len(setup) != 8:
        raise DescriptorError('setup packet must be 8 bytes')
    bm_request_type, request, value, index, length = struct.unpack('<BBHHH', setup)
    if bm_request_type == 0x80 and request == 0x06:
        descriptor_type = value >> 8
        descriptor_index = value & 0xFF
        if descriptor_type == DESCRIPTOR_STRING and descriptor_index == MS_OS_STRING_INDEX:
            payload = ms_os_string_descriptor(vendor_code)
            return {'handled': True, 'name': 'ms_os_string', 'payload': payload[:length]}
        return {'handled': False, 'name': 'other_standard_descriptor'}
    if bm_request_type == 0xC0 and request == vendor_code and index == MS_OS_COMPAT_INDEX:
        if value != 0:
            return {'handled': False, 'name': 'vendor_request_value_unsupported'}
        payload = ms_os_compat_id_descriptor(interface_number)
        return {'handled': True, 'name': 'ms_os_compat_id', 'payload': payload[:length]}
    return {'handled': False, 'name': 'other'}


def validate_winusb_binding(device_string: bytes, compat: bytes, interface_number: int) -> dict:
    """Validate the two EP0 payloads as Windows would consume them."""
    if len(device_string) != 18 or device_string[0] != 18 or device_string[1] != DESCRIPTOR_STRING:
        raise DescriptorError('OS string descriptor is not 18 bytes / string type')
    if device_string[2:16].decode('utf-16-le') != MS_OS_SIGNATURE:
        raise DescriptorError('OS string signature is not MSFT100')
    vendor_code = device_string[16]
    if device_string[17] != 0:
        raise DescriptorError('OS string pad byte must be zero')
    length, version, index, count = struct.unpack_from('<IHHB', compat, 0)
    if length != len(compat) or version != 0x0100 or index != MS_OS_COMPAT_INDEX or count != 1:
        raise DescriptorError('compat ID descriptor header is invalid')
    if any(compat[9:16]):
        raise DescriptorError('compat ID reserved header bytes must be zero')
    first_interface, section_reserved = compat[16], compat[17]
    if first_interface != interface_number or section_reserved != 0:
        raise DescriptorError('compat ID first interface/reserved mismatch')
    if compat[18:26] != WINUSB_COMPATIBLE_ID:
        raise DescriptorError('compat ID is not WINUSB')
    if any(compat[26:40]):
        raise DescriptorError('compat ID sub-ID/reserved bytes must be zero')
    return {'verified': True, 'vendor_code': vendor_code,
            'compatible_id': compat[18:26].decode('latin1').rstrip('\0'),
            'interface_number': first_interface}
