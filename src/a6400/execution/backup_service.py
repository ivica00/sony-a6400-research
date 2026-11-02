"""Authentic BK4 preset state and backup service contracts.

Verified against Sony firmware module /usr/kmod/backup.ko, userland library
/usr/lib/libbackup.so, and preserved BK4 preset files.
"""

import hashlib
import struct
from typing import Any, Dict, List, Optional
from pathlib import Path

from project_paths import PROJECT_ROOT
from src.a6400.execution.guest_uipc import BACKUP_SERVICE_QUEUE, UnsupportedUipc

# Verified default preset packaging file
DEFAULT_PRESET_REL = 'firmware/extracted_a6400/firmware.tar_unpacked/0110_backup/SYSASTRA-DSLR/DX2/CX62600_UC2.bin'
DEFAULT_PRESET_SHA256 = '241c8521035bc9ff1edbe66cf3d42d81879a4bef8ff9e21cbfb84530a1446154'


def checked_bk4(raw: bytes) -> Dict[str, int]:
    """Validates BK4 structural format and checksum; fails closed on corrupt data."""
    if len(raw) < 0x100 or raw[12:16] != b'BK4\0':
        raise ValueError('Expected a complete BK4 header with BK4\\0 identifier')
    subsystems, properties, data_offset, data_size, checksum = struct.unpack_from('<5I', raw, 0x10)
    if 0x100 + 6 * subsystems + 6 * properties > data_offset:
        raise ValueError('Preset tables overlap payload or exceed its offset')
    if data_offset > len(raw) or data_size > len(raw) - data_offset:
        raise ValueError('Preset payload exceeds supplied bytes')
    end = data_offset + data_size
    if (sum(raw[:0x20]) + sum(raw[0x24:end])) & 0xffffffff != checksum:
        raise ValueError('Preset checksum mismatch')
    return {
        'subsystems': subsystems,
        'properties': properties,
        'data_offset': data_offset,
        'data_size': data_size,
        'checksum': checksum
    }


class PropertyDescriptor:
    """Decoded unit descriptor matching Data_SearchId and property table layout."""

    def __init__(self, unit: int, subsystem: int, prop_index: int,
                 descriptor_offset: int, attribute: int, size: int,
                 vmax: int, data_offset: int):
        self.unit = unit
        self.subsystem = subsystem
        self.prop_index = prop_index
        self.descriptor_offset = descriptor_offset
        self.attribute = attribute
        self.size = size
        self.vmax = vmax
        self.data_offset = data_offset

    def to_dict(self) -> Dict[str, Any]:
        return {
            'unit': self.unit,
            'subsystem': self.subsystem,
            'prop_index': self.prop_index,
            'descriptor_offset': self.descriptor_offset,
            'attribute': self.attribute,
            'size': self.size,
            'vmax': self.vmax,
            'data_offset': self.data_offset
        }


class BK4PresetState:
    """Maintains mutable BK4 preset RAM state initialized from authentic preset bytes."""

    def __init__(self, raw: bytes, expected_sha256: Optional[str] = None):
        if expected_sha256 is not None:
            actual = hashlib.sha256(raw).hexdigest()
            if actual != expected_sha256:
                raise ValueError(f'Preset SHA-256 mismatch: expected {expected_sha256}, got {actual}')
        checked = checked_bk4(raw)
        self.raw = bytearray(raw)
        self.subsystems = checked['subsystems']
        self.properties = checked['properties']
        self.data_offset = checked['data_offset']
        self.data_size = checked['data_size']
        self.checksum = checked['checksum']
        self.subsys_table_offset = 0x100
        self.props_table_offset = 0x100 + self.subsystems * 6

    @classmethod
    def load_default(cls, root: Optional[Path] = None) -> 'BK4PresetState':
        base = root or PROJECT_ROOT
        path = base / DEFAULT_PRESET_REL
        if not path.is_file():
            raise FileNotFoundError(f'Default preset not found: {path}')
        return cls(path.read_bytes(), DEFAULT_PRESET_SHA256)

    def search_id(self, unit: int) -> Optional[PropertyDescriptor]:
        """Resolves unit ID using the exact algorithm of original Data_SearchId."""
        subsystem = unit >> 16
        prop = unit & 0xffff
        if subsystem >= self.subsystems:
            return None
        subsys_entry_offset = self.subsys_table_offset + subsystem * 6
        num_props, base_idx = struct.unpack_from('<HI', self.raw, subsys_entry_offset)
        if prop >= num_props:
            return None
        prop_entry_offset = self.props_table_offset + (base_idx + prop) * 6
        attr, val = struct.unpack_from('<HI', self.raw, prop_entry_offset)
        if val == 0xffffffff:
            return None
        flag = val >> 24
        off = val & 0x00ffffff
        if flag == 0:
            size = struct.unpack_from('<H', self.raw, off)[0]
            data_offset = off + 4
            vmax = struct.unpack_from('<H', self.raw, off + 2)[0]
        elif flag == 0xff:
            size = struct.unpack_from('<H', self.raw, off)[0]
            data_offset = off + 2
            vmax = 0
        else:
            size = flag
            data_offset = off
            vmax = 0
        return PropertyDescriptor(
            unit=unit,
            subsystem=subsystem,
            prop_index=prop,
            descriptor_offset=prop_entry_offset,
            attribute=attr,
            size=size,
            vmax=vmax,
            data_offset=data_offset
        )

    def read_unit(self, unit: int) -> bytes:
        desc = self.search_id(unit)
        if desc is None:
            raise KeyError(f'Unit 0x{unit:08x} not found in BK4 preset')
        return bytes(self.raw[desc.data_offset : desc.data_offset + desc.size])

    def write_unit(self, unit: int, payload: bytes) -> int:
        desc = self.search_id(unit)
        if desc is None:
            raise KeyError(f'Unit 0x{unit:08x} not found in BK4 preset')
        if len(payload) != desc.size and (desc.vmax == 0 or len(payload) > desc.vmax):
            raise ValueError(
                f'Payload size {len(payload)} does not match unit 0x{unit:08x} (size={desc.size}, vmax={desc.vmax})'
            )
        self.raw[desc.data_offset : desc.data_offset + len(payload)] = payload
        return 0


class PresetBackedBackupService:
    """Services UIPC backup messages against authentic preset state."""

    def __init__(self, preset_state: BK4PresetState):
        self.preset_state = preset_state
        self.events: List[Dict[str, Any]] = []

    def handle_uipc_sync_message(self, memory_reader, memory_writer, msg_ptr: int, alloc_size: int = 64) -> int:
        if alloc_size < 24:
            raise UnsupportedUipc('backup_message_header_truncated', allocated_size=alloc_size)
        raw_msg = memory_reader(msg_ptr, min(alloc_size, 64))
        if len(raw_msg) < 24:
            raise UnsupportedUipc('backup_message_header_truncated', supplied_size=len(raw_msg))
        words = list(struct.unpack_from('<' + 'I' * (len(raw_msg) // 4), raw_msg))
        op = words[0]
        queue = words[3]
        if queue != BACKUP_SERVICE_QUEUE:
            raise UnsupportedUipc('unexpected_backup_queue', queue=queue, expected=BACKUP_SERVICE_QUEUE)
        required_words = {0: 7, 2: 7, 3: 8, 4: 7, 8: 9, 30: 9}.get(op)
        if required_words is not None and len(words) < required_words:
            raise UnsupportedUipc('backup_message_arguments_truncated', operation=op,
                                  supplied_words=len(words), required_words=required_words)

        if op in (0, 2):  # Backup_get_datasize / Backup_get_attribute
            unit = words[6]
            desc = self.preset_state.search_id(unit)
            value = (-1 if desc is None else desc.size if op == 0 else desc.attribute)
            if memory_writer:
                memory_writer(msg_ptr + 4, struct.pack('<I', value & 0xffffffff))
            self.events.append({'type': 'Backup_get_datasize' if op == 0 else 'Backup_get_attribute',
                                'unit': unit, 'returned': value})
            return 0

        elif op in (3, 30):  # Backup_read / Backup_nread share the original copy helper.
            unit, dst_ptr = words[6:8]
            read_name = 'Backup_nread' if op == 30 else 'Backup_read'
            capacity = struct.unpack('<i', struct.pack('<I', words[8]))[0] if op == 30 else None
            desc = self.preset_state.search_id(unit)
            if desc is None:
                if memory_writer:
                    memory_writer(msg_ptr + 4, struct.pack('<i', -1))
                self.events.append({'type': read_name, 'unit': unit, 'returned': -1})
                return 0
            # Original helper compares signed sizes and enters its assertion path;
            # it does not truncate the copy to the caller's capacity.
            if capacity is not None and capacity < desc.size:
                raise UnsupportedUipc('backup_nread_capacity_assertion', unit=unit,
                                      capacity=capacity, required=desc.size)
            data = self.preset_state.read_unit(unit)
            if len(data) != desc.size:
                raise UnsupportedUipc('backup_payload_outside_preset', unit=unit, required=desc.size)
            if memory_writer:
                memory_writer(dst_ptr, data)
                memory_writer(msg_ptr + 4, struct.pack('<I', len(data)))
            self.events.append({'type': read_name, 'unit': unit, 'size': len(data),
                                'capacity': capacity, 'payload_hex': data.hex(), 'returned': len(data)})
            return 0

        elif op == 8:  # Backup_write(subsystem, unit, val_ptr)
            subsystem = words[6]
            unit = words[7]
            src_ptr = words[8]
            if subsystem != (unit >> 16):
                # Backup_write_core enforces subsystem == unit >> 16, else returns -4
                if memory_writer:
                    memory_writer(msg_ptr + 4, struct.pack('<i', -4))
                return 0
            desc = self.preset_state.search_id(unit)
            if desc is None:
                raise UnsupportedUipc('backup_unit_not_found', unit=unit, op=op)
            payload = memory_reader(src_ptr, desc.size)
            self.preset_state.write_unit(unit, payload)
            if memory_writer:
                memory_writer(msg_ptr + 4, struct.pack('<i', 0))
            self.events.append({
                'type': 'Backup_write',
                'subsystem': subsystem,
                'unit': unit,
                'size': desc.size,
                'payload_hex': payload.hex(),
                'returned': 0
            })
            return 0

        elif op == 4:  # Backup_read_4Byte(unit)
            unit = words[6]
            desc = self.preset_state.search_id(unit)
            data = self.preset_state.read_unit(unit) if desc is not None and desc.size == 4 else b''
            val = struct.unpack_from('<I', data)[0] if len(data) == 4 else 0
            if memory_writer:
                memory_writer(msg_ptr + 4, struct.pack('<I', val))
            self.events.append({
                'type': 'Backup_read_4Byte',
                'unit': unit,
                'val': val,
                'val_hex': f'0x{val:08x}'
            })
            return 0

        else:
            raise UnsupportedUipc('unsupported_backup_operation', operation=op, words=words)
