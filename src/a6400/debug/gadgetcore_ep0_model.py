"""Offline model for the E0405b descriptor extension, EP0 chunk transport and
save/restore guard. No hardware access.

The model is deliberately explicit so it can be validated byte-for-byte:
* the device descriptor carries the `bcdUSB = 0x0210` override;
* the MSC configuration keeps interface 0 and appends the zero-endpoint vendor
  interface 1 (`0xFF/0xDB/0x01`);
* string 0xEE is the MS OS 2.0 `MSFT20` descriptor and the vendor request
  `bRequest=0x02, wIndex=7` returns the configuration/function-subset set;
* EP0 control chunks are <=64 bytes and reassemble exactly one 4096-byte frame;
* every runtime patch is registered in a save/restore guard that must be
  restored before any USB reconfiguration.
"""
from __future__ import annotations

import struct

from src.a6400 import usb_debug_descriptors as descriptors
from src.a6400.debug.gadgetcore_chunk_stub import STUB_SYMBOLS, STUB_TEXT

FRAME_SIZE = 4096
CHUNK_SIZE = 64
UNICORN_CODE_BASE = 0x10000000


class ModelError(RuntimeError):
    pass


def zero_endpoint_vendor_interface(interface_number: int) -> bytes:
    if not 0 <= interface_number <= 0xFF:
        raise ModelError('interface number outside one byte')
    return struct.pack('<BBBBBBBBB', 9, descriptors.DESCRIPTOR_INTERFACE,
                       interface_number, 0, 0, descriptors.VENDOR_INTERFACE_CLASS,
                       descriptors.VENDOR_INTERFACE_SUBCLASS,
                       descriptors.VENDOR_INTERFACE_PROTOCOL, 0)


def extend_msc_configuration(config: bytes, interface_number: int = 1) -> dict:
    interfaces = descriptors.existing_interface_numbers(config)
    endpoints = descriptors.existing_endpoint_addresses(config)
    if interface_number in interfaces:
        raise ModelError('vendor interface number already used')
    base_total = struct.unpack_from('<H', config, 2)[0]
    addition = zero_endpoint_vendor_interface(interface_number)
    merged = bytearray(config[:base_total])
    merged[2:4] = struct.pack('<H', base_total + len(addition))
    merged[4] = max(config[4], interface_number + 1)
    merged.extend(addition)
    return {'bytes': bytes(merged), 'interface_number': interface_number,
            'base_interfaces': interfaces, 'base_endpoints': sorted(endpoints),
            'total_length': base_total + len(addition)}


def device_descriptor(vendor_id=0x054C, product_id=0x0CA8, bcd_device=0x0200,
                      bcd_usb=0x0210, max_packet0=64, config_count=1) -> bytes:
    return struct.pack('<BBHBBBBHHHBBBB', 18, descriptors.DESCRIPTOR_DEVICE,
                       bcd_usb, 0, 0, 0, max_packet0, vendor_id, product_id,
                       bcd_device, 0, 0, 0, config_count)


class DescriptorModel:
    def __init__(self, base_config: bytes, interface_number: int = 1,
                 product_id: int = 0x0CA8):
        self._base = bytes(base_config)
        self._extended = extend_msc_configuration(self._base, interface_number)
        self.interface_number = interface_number
        self.product_id = product_id
        self.msos_set = descriptors.ms_os_20_composite_descriptor_set(1, interface_number)
        descriptors.validate_winusb_20_composite_binding(self.msos_set, 1, interface_number)

    def config(self) -> bytes:
        return self._extended['bytes']

    def device(self) -> bytes:
        return device_descriptor(bcd_usb=0x0210, product_id=self.product_id,
                                 config_count=1 if len(self._extended['base_interfaces']) else 1)

    def string_ee(self) -> bytes:
        return descriptors.ms_os_20_string_descriptor()

    def handle_setup(self, setup: bytes) -> dict:
        if len(setup) != 8:
            raise ModelError('setup packet must be 8 bytes')
        request_type, request, value, index, length = struct.unpack('<BBHHH', setup)
        if request_type == 0x80 and request == 0x06:
            descriptor_type, descriptor_index = value >> 8, value & 0xFF
            if descriptor_type == descriptors.DESCRIPTOR_DEVICE:
                payload, name = self.device(), 'device_descriptor'
            elif descriptor_type == descriptors.DESCRIPTOR_CONFIG and descriptor_index == 0:
                payload, name = self.config(), 'config_descriptor'
            elif descriptor_type == descriptors.DESCRIPTOR_STRING \
                    and descriptor_index == descriptors.MS_OS_STRING_INDEX:
                payload, name = self.string_ee(), 'ms_os_20_string'
            else:
                return {'handled': False, 'name': 'other_standard'}
            return {'handled': True, 'name': name, 'payload': payload[:length]}
        reply = descriptors.ms_os_20_vendor_reply(setup, self.msos_set)
        if reply['handled']:
            return reply
        return {'handled': False, 'name': 'other'}


class ChunkTransport:
    """EP0 vendor chunk framing: request OUT chunks -> one frame; reply IN chunks."""

    def __init__(self, frame_size: int = FRAME_SIZE, chunk_size: int = CHUNK_SIZE):
        self.frame_size = frame_size
        self.chunk_size = chunk_size
        self.request = bytearray()
        self.response = b''
        self.reply_offset = 0

    def reset_request(self):
        self.request = bytearray()

    def out_chunk(self, index: int, data: bytes):
        expected = len(self.request) // self.chunk_size
        if index != expected:
            raise ModelError(f'out-of-order chunk {index}, expected {expected}')
        if not 0 < len(data) <= self.chunk_size:
            raise ModelError('chunk length outside 1..64')
        if len(self.request) + len(data) > self.frame_size:
            raise ModelError('request frame overflow')
        self.request.extend(data)
        if len(self.request) == self.frame_size:
            frame = bytes(self.request)
            self.request = bytearray()
            return frame
        return None

    def load_response(self, frame: bytes):
        if len(frame) != self.frame_size:
            raise ModelError('response frame must be 4096 bytes')
        self.response = frame
        self.reply_offset = 0

    def in_chunk(self, index: int = None) -> bytes:
        if not self.response:
            return b''
        expected = self.reply_offset // self.chunk_size
        if index is not None and index != expected:
            raise ModelError(f'out-of-order IN chunk {index}, expected {expected}')
        chunk = self.response[self.reply_offset:self.reply_offset + self.chunk_size]
        self.reply_offset += len(chunk)
        return chunk


class SaveRestoreGuard:
    """Tracks every runtime patch and refuses reconfiguration until restored."""

    def __init__(self, memory=None):
        self.memory = bytearray(memory or b'')
        self.entries = {}

    def read(self, address: int, length: int) -> bytes:
        return bytes(self.memory[address:address + length])

    def save(self, name: str, address: int, length: int, patched: bytes):
        if name in self.entries:
            raise ModelError(f'{name} already saved')
        if len(patched) != length:
            raise ModelError('patched length mismatch')
        self.entries[name] = {'address': address, 'length': length,
                              'original': self.read(address, length),
                              'patched': bytes(patched), 'active': False}
        return self.entries[name]

    def patch(self, name: str):
        entry = self.entries[name]
        self.memory[entry['address']:entry['address'] + entry['length']] = entry['patched']
        entry['active'] = True

    def restore(self, name: str) -> dict:
        entry = self.entries[name]
        self.memory[entry['address']:entry['address'] + entry['length']] = entry['original']
        entry['active'] = False
        actual = self.read(entry['address'], entry['length'])
        return {'name': name, 'verified': actual == entry['original']}

    def restore_all(self) -> dict:
        results = [self.restore(name) for name in reversed(list(self.entries))]
        return {'restored': len(results), 'verified': all(r['verified'] for r in results),
                'results': results}

    def reconfiguration_allowed(self) -> bool:
        return not any(entry['active'] for entry in self.entries.values())


class UcChunkEngine:
    """Executes the generated ARM chunk routines under Unicorn."""

    def __init__(self):
        import unicorn
        from unicorn import arm_const
        self.unicorn = unicorn
        self.arm = arm_const
        self.uc = unicorn.Uc(unicorn.UC_ARCH_ARM, unicorn.UC_MODE_ARM)
        self.data_base = 0x20000000
        self.uc.mem_map(UNICORN_CODE_BASE, 0x10000)
        self.uc.mem_map(self.data_base, 0x40000)
        self.uc.mem_write(UNICORN_CODE_BASE, STUB_TEXT)
        self.uc.reg_write(arm_const.UC_ARM_REG_SP, self.data_base + 0x3F000)

    def _call(self, name, registers):
        address = UNICORN_CODE_BASE + STUB_SYMBOLS[name]
        stop = UNICORN_CODE_BASE + 0x8000
        for number, value in enumerate(registers):
            self.uc.reg_write(getattr(self.arm, f'UC_ARM_REG_R{number}'), value)
        self.uc.reg_write(self.arm.UC_ARM_REG_LR, stop)
        self.uc.emu_start(address, stop, count=100000)
        return self.uc.reg_read(self.arm.UC_ARM_REG_R0)

    def extract(self, frame: bytes, index: int) -> bytes:
        self.uc.mem_write(self.data_base, frame)
        out = self.data_base + 0x10000
        count = self._call('a6400_chunk_extract',
                           [self.data_base, len(frame), index, out])
        if count == 0xFFFFFFFF:
            raise ModelError('arm extract rejected')
        return bytes(self.uc.mem_read(out, count))

    def insert(self, frame: bytearray, index: int, chunk: bytes) -> int:
        self.uc.mem_write(self.data_base, bytes(frame))
        source = self.data_base + 0x10000
        self.uc.mem_write(source, chunk)
        stack = self.data_base + 0x3F000
        self.uc.mem_write(stack, struct.pack('<I', len(chunk)))
        count = self._call('a6400_chunk_insert',
                           [self.data_base, len(frame), index, source])
        if count == 0xFFFFFFFF:
            raise ModelError('arm insert rejected')
        frame[:] = self.uc.mem_read(self.data_base, len(frame))
        return count
