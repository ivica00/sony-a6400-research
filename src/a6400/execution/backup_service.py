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
KNOWN_PRESETS = (
    (DEFAULT_PRESET_REL, DEFAULT_PRESET_SHA256),
    ('firmware/extracted_a6400/firmware.tar_unpacked/0110_backup/SYSASTRA-DSLR/PDC/CX77700_UC2.bin',
     'f201df1d3e8d09c917ebd1af44dc4a8785c7adf270b6aa7154929ca9787cee1e'),  # ILCE-6100A: preset named by its MainDest.txt
)


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
        tried = []
        for rel, sha in KNOWN_PRESETS:
            path = base / rel
            tried.append(str(path))
            if path.is_file():
                return cls(path.read_bytes(), sha)
        raise FileNotFoundError('Default preset not found: ' + ' ; '.join(tried))

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

    def reset_data_offset(self, desc: PropertyDescriptor) -> int:
        """Data_GetResetDataPt: the reset (default) copy sits right after the live data
        (after vmax bytes for variable-size units, after size bytes otherwise)."""
        flag = struct.unpack_from('<I', self.raw, desc.descriptor_offset + 2)[0] >> 24
        return desc.data_offset + (desc.vmax if flag == 0 else desc.size)

    def reset_unit(self, mode: int, desc: PropertyDescriptor) -> int:
        """Reset core: copies the reset copy over the live data."""
        if not desc.attribute & 0x74:
            return -1
        count, elem = 1, desc.size
        if desc.attribute & 0x80:  # setting-attr unit: element count = byte of unit 0x3E000C + 1
            cdesc = self.search_id(0x3E000C)
            if cdesc is None:
                return -127
            if cdesc.size != 1:
                raise UnsupportedUipc('backup_reset_count_unit_size', size=cdesc.size)
            n = self.raw[cdesc.data_offset] + 1
            if n != 1:
                if desc.vmax or desc.size < n or desc.size % n:
                    return -127
                elem = desc.size // n
                count = n if mode == 1 else 1
        src = self.reset_data_offset(desc)
        if src + elem > len(self.raw):
            raise UnsupportedUipc('backup_reset_data_outside_preset', unit=desc.unit)
        for i in range(count):  # every element is reset from the same first `elem` bytes (as the original loop)
            self.raw[desc.data_offset + i * elem:desc.data_offset + (i + 1) * elem] = self.raw[src:src + elem]
        return 0

    def reset_subsystem(self, subsystem: int, mode: int) -> int:
        """Reset-subsystem core."""
        if subsystem >= self.subsystems or not 1 <= mode <= 4:
            return -7
        bit = {1: 0x40, 2: 0x10, 3: 0x20, 4: 0x04}[mode]
        for prop in range(struct.unpack_from('<H', self.raw, self.subsys_table_offset + subsystem * 6)[0]):
            desc = self.search_id(subsystem << 16 | prop)
            if desc is not None and desc.attribute & bit and self.reset_unit(mode, desc) < 0:
                return -127
        return 0


class PresetBackedBackupService:
    """Services UIPC backup messages against authentic preset state."""

    def __init__(self, preset_state: BK4PresetState):
        self.preset_state = preset_state
        self.events: List[Dict[str, Any]] = []

    def _write_core(self, memory_reader, subsystem: int, unit: int, src_ptr: int, size: int) -> int:
        """Write core (ops 8, 9, 10). Returns the byte count written on success
        (size 0 means the whole fixed unit), so Backup_write returns the unit size, not 0; callers
        test `> 0` for success."""
        desc = self.preset_state.search_id(unit)
        if subsystem != unit >> 16:
            return -4
        if desc is None:
            return -1
        if desc.attribute & 1 and struct.unpack_from('<I', self.preset_state.raw, 0x28)[0] == 1:
            return -3  # attribute bit0 unit while header ID1 (offset 0x28) == 1
        if size == 0:
            if desc.vmax:
                return -1
            size = desc.size
        elif size > (desc.vmax or desc.size) or (desc.vmax == 0 and size != desc.size):
            return -5
        if desc.attribute & 8:
            # backup_sharedcb_send_msg posts a notification message (result ignored by the core); not modeled.
            self.events.append({'type': 'Backup_sharedcb_not_modeled', 'unit': unit})
        raw = self.preset_state.raw
        raw[desc.data_offset:desc.data_offset + size] = memory_reader(src_ptr, size)
        if desc.vmax and size != desc.size:  # Data_GetDataSizePt: u16 size field in front of the data
            struct.pack_into('<H', raw, desc.data_offset - 4, size)
        return size

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
        required_words = {0: 7, 1: 8, 2: 7, 3: 8, 4: 7, 5: 8, 8: 9, 9: 10, 10: 9, 14: 7, 15: 6, 18: 8, 19: 8, 20: 7,
                          26: 9, 28: 10, 30: 9, 31: 9, 34: 10, 36: 7, 37: 8}.get(op)
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

        elif op == 1:  # Backup_get_datasize_multi(units_ptr, sizes_ptr)
            units_ptr, sizes_ptr = words[6:8]
            descs = []
            idx = 0
            while True:
                unit = struct.unpack('<I', memory_reader(units_ptr + idx * 4, 4))[0]
                if unit == 0:
                    break
                desc = self.preset_state.search_id(unit)
                if desc is None:
                    if memory_writer:
                        memory_writer(msg_ptr + 4, struct.pack('<i', -1))
                    self.events.append({'type': 'Backup_get_datasize_multi', 'units_ptr': units_ptr, 'returned': -1})
                    return 0
                descs.append(desc)
                idx += 1
            total_size = 0
            for i, desc in enumerate(descs):
                total_size += desc.size
                if sizes_ptr != 0 and memory_writer:
                    memory_writer(sizes_ptr + i * 4, struct.pack('<I', desc.size))
            if memory_writer:
                memory_writer(msg_ptr + 4, struct.pack('<I', total_size))
            self.events.append({
                'type': 'Backup_get_datasize_multi',
                'units': [d.unit for d in descs],
                'returned': total_size
            })
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
                if dst_ptr != 0:
                    memory_writer(dst_ptr, data)
                memory_writer(msg_ptr + 4, struct.pack('<I', len(data)))
            self.events.append({'type': read_name, 'unit': unit, 'size': len(data),
                                'capacity': capacity, 'payload_hex': data.hex(), 'returned': len(data)})
            return 0

        elif op in (5, 31):  # Backup_read_multi / Backup_nread_multi
            units_ptr, dst_ptrs_ptr = words[6:8]
            capacities_ptr = words[8] if op == 31 else None
            read_name = 'Backup_nread_multi' if op == 31 else 'Backup_read_multi'
            first_unit = struct.unpack('<I', memory_reader(units_ptr, 4))[0]
            if first_unit == 0:
                if memory_writer:
                    memory_writer(msg_ptr + 4, struct.pack('<I', 0))
                self.events.append({'type': read_name, 'units': [], 'returned': 0})
                return 0
            idx = 0
            units_read = []
            while True:
                unit = struct.unpack('<I', memory_reader(units_ptr + idx * 4, 4))[0]
                if unit == 0:
                    break
                capacity = None
                if capacities_ptr is not None:
                    capacity = struct.unpack('<i', memory_reader(capacities_ptr + idx * 4, 4))[0]
                    if idx > 0 and capacity == 0:
                        break
                dst_ptr = struct.unpack('<I', memory_reader(dst_ptrs_ptr + idx * 4, 4))[0]
                desc = self.preset_state.search_id(unit)
                if desc is None or desc.size <= 0:
                    if memory_writer:
                        memory_writer(msg_ptr + 4, struct.pack('<i', -1))
                    self.events.append({'type': read_name, 'units': units_read, 'failed_unit': unit, 'returned': -1})
                    return 0
                if capacity is not None and capacity < desc.size:
                    raise UnsupportedUipc('backup_nread_capacity_assertion', unit=unit,
                                          capacity=capacity, required=desc.size)
                data = self.preset_state.read_unit(unit)
                if len(data) != desc.size:
                    raise UnsupportedUipc('backup_payload_outside_preset', unit=unit, required=desc.size)
                if memory_writer and dst_ptr != 0:
                    memory_writer(dst_ptr, data)
                units_read.append(unit)
                idx += 1
            if memory_writer:
                memory_writer(msg_ptr + 4, struct.pack('<I', len(units_read)))
            self.events.append({
                'type': read_name,
                'units': units_read,
                'count': len(units_read),
                'returned': len(units_read)
            })
            return 0

        elif op == 8:  # Backup_write(subsystem, unit, val_ptr): write core with size 0
            subsystem, unit, src_ptr = words[6] & 0xffff, words[7], words[8]
            ret = self._write_core(memory_reader, subsystem, unit, src_ptr, 0)
            if memory_writer:
                memory_writer(msg_ptr + 4, struct.pack('<i', ret))
            event = {'type': 'Backup_write', 'subsystem': subsystem, 'unit': unit, 'returned': ret}
            if ret > 0:
                event.update(size=ret, payload_hex=self.preset_state.read_unit(unit).hex())
            self.events.append(event)
            return 0

        elif op == 10:  # Backup_write_multi(subsystem, units_ptr, src_ptrs_ptr)
            subsystem = words[6] & 0xffff
            units_ptr = words[7]
            src_ptrs_ptr = words[8]
            unit_descs = []
            idx = 0
            while True:
                unit = struct.unpack('<I', memory_reader(units_ptr + idx * 4, 4))[0]
                if unit == 0:
                    break
                if (unit >> 16) != subsystem:
                    if memory_writer:
                        memory_writer(msg_ptr + 4, struct.pack('<i', -4))
                    self.events.append({'type': 'Backup_write_multi', 'subsystem': subsystem,
                                        'failed_unit': unit, 'returned': -4})
                    return 0
                desc = self.preset_state.search_id(unit)
                if desc is None or desc.size <= 0:
                    if memory_writer:
                        memory_writer(msg_ptr + 4, struct.pack('<i', -1))
                    self.events.append({'type': 'Backup_write_multi', 'subsystem': subsystem,
                                        'failed_unit': unit, 'returned': -1})
                    return 0
                unit_descs.append((unit, desc))
                idx += 1
            for i, (unit, desc) in enumerate(unit_descs):
                src_ptr = struct.unpack('<I', memory_reader(src_ptrs_ptr + i * 4, 4))[0]
                self._write_core(memory_reader, subsystem, unit, src_ptr, 0)  # per-unit result ignored, as the original
            if memory_writer:
                memory_writer(msg_ptr + 4, struct.pack('<I', len(unit_descs)))
            self.events.append({
                'type': 'Backup_write_multi',
                'subsystem': subsystem,
                'units': [u for u, _ in unit_descs],
                'returned': len(unit_descs)
            })
            return 0

        elif op in (14, 15):  # Backup_sync_subsystem / Backup_sync_all
            subsystem = (words[6] & 0xffff) if op == 14 else None
            if memory_writer:
                memory_writer(msg_ptr + 4, struct.pack('<I', 0))
            self.events.append({
                'type': 'Backup_sync_subsystem' if op == 14 else 'Backup_sync_all',
                'subsystem': subsystem,
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

        elif op == 28:  # Backup_write_setting_attr(index, subsystem, unit, src_ptr)
            index, subsystem, unit, src_ptr = words[6:10]
            count = self.preset_state.read_unit(0x3E000C)[0] + 1  # element count = byte of unit 0x3E000C + 1
            desc = self.preset_state.search_id(unit)
            if index >= count:
                ret = -7
            elif subsystem != unit >> 16:
                ret = -4
            elif desc is None:
                raise UnsupportedUipc('backup_unit_not_found', unit=unit, op=op)
            elif desc.attribute & 1:
                raise UnsupportedUipc('backup_setting_attr_id1_check_not_modeled', unit=unit)
            elif not desc.attribute & 0x80:
                ret = -3
            elif desc.vmax or desc.size < count or desc.size % count:
                ret = -1
            elif desc.attribute & 8:
                raise UnsupportedUipc('backup_sharedcb_not_modeled', unit=unit)
            else:
                ret = desc.size // count  # element size E; server returns bytes written
                data = bytearray(self.preset_state.read_unit(unit))
                data[index * ret:(index + 1) * ret] = memory_reader(src_ptr, ret)
                self.preset_state.write_unit(unit, bytes(data))
            if memory_writer:
                memory_writer(msg_ptr + 4, struct.pack('<i', ret))
            self.events.append({'type': 'Backup_write_setting_attr', 'index': index, 'subsystem': subsystem,
                                'unit': unit, 'returned': ret})
            return 0

        elif op in (26, 34):  # Backup_read_setting_attr(index, unit, dst) / Backup_nread_setting_attr(+capacity)
            index, unit, dst_ptr = words[6:9]
            name = 'Backup_read_setting_attr' if op == 26 else 'Backup_nread_setting_attr'
            count = self.preset_state.read_unit(0x3E000C)[0] + 1
            desc = self.preset_state.search_id(unit)
            if index >= count:
                ret = -7
            elif desc is None:
                raise UnsupportedUipc('backup_unit_not_found', unit=unit, op=op)
            elif not desc.attribute & 0x80:
                ret = -3
            else:
                # capacity is compared (signed) against the whole unit size; smaller enters the assertion path
                if op == 34 and struct.unpack('<i', struct.pack('<I', words[9]))[0] < desc.size:
                    raise UnsupportedUipc('backup_nread_capacity_assertion', unit=unit,
                                          capacity=words[9], required=desc.size)
                if desc.size < count or desc.size % count:
                    ret = -1
                else:
                    ret = desc.size // count
                    if memory_writer:
                        memory_writer(dst_ptr, self.preset_state.read_unit(unit)[index * ret:(index + 1) * ret])
            if memory_writer:
                memory_writer(msg_ptr + 4, struct.pack('<i', ret))
            self.events.append({'type': name, 'index': index, 'unit': unit, 'returned': ret})
            return 0

        elif op == 9:  # Backup_write_vsize(subsystem, unit, src_ptr, size): write core
            subsystem, unit, src_ptr, size = words[6] & 0xffff, words[7], words[8], words[9]
            ret = self._write_core(memory_reader, subsystem, unit, src_ptr, size)
            if memory_writer:
                memory_writer(msg_ptr + 4, struct.pack('<i', ret))
            self.events.append({'type': 'Backup_write_vsize', 'subsystem': subsystem, 'unit': unit,
                                'size': size, 'returned': ret})
            return 0

        elif op in (18, 19, 20):  # Backup_reset(subsystem, unit) / reset_subsystem(subsystem, mode) / reset_all(mode)
            if op == 18:  # -4 subsystem mismatch, -1 unit missing, else reset-core mode 1
                subsystem, unit = words[6] & 0xffff, words[7]
                desc = self.preset_state.search_id(unit)
                ret = -4 if subsystem != unit >> 16 else -1 if desc is None else self.preset_state.reset_unit(1, desc)
                detail = {'subsystem': subsystem, 'unit': unit}
            elif op == 19:  # reset-subsystem core
                subsystem, mode = words[6] & 0xffff, words[7]
                ret = self.preset_state.reset_subsystem(subsystem, mode)
                detail = {'subsystem': subsystem, 'mode': mode}
            else:  # every subsystem in header order; any failure collapses to -7
                mode = words[6]
                ret = 0
                for sub in range(self.preset_state.subsystems):
                    if self.preset_state.reset_subsystem(sub, mode):
                        ret = -7
                        break
                detail = {'mode': mode}
            if memory_writer:
                memory_writer(msg_ptr + 4, struct.pack('<i', ret))
            self.events.append({'type': {18: 'Backup_reset', 19: 'Backup_reset_subsystem', 20: 'Backup_reset_all'}[op],
                                **detail, 'returned': ret})
            return 0

        elif op == 37:  # Backup_read_rst_attr(unit, dst_ptr): copy the reset data copy out
            unit, dst_ptr = words[6:8]
            desc = self.preset_state.search_id(unit)
            ret = -1 if desc is None else desc.size
            if desc is not None and memory_writer:
                off = self.preset_state.reset_data_offset(desc)
                memory_writer(dst_ptr, bytes(self.preset_state.raw[off:off + desc.size]))
            if memory_writer:
                memory_writer(msg_ptr + 4, struct.pack('<i', ret))
            self.events.append({'type': 'Backup_read_rst_attr', 'unit': unit, 'returned': ret})
            return 0

        elif op == 36:  # Backup_get_pdt_stat(dst_ptr): header summary struct (40 bytes)
            raw = self.preset_state.raw
            hexval = lambda c: int(chr(c), 16) if chr(c) in '0123456789abcdefABCDEF' else 0  # backup_senser_atonx(p, 1)
            rev = 4 if raw[12:15] == b'BK4' else 3 if raw[12:15] == b'BK3' else 2 if raw[12:15] == b'BK2' else 1
            first = hexval(raw[0xe]) << 4
            if rev == 1:
                out = struct.pack('<II', first, 0) + bytes(0x20)
            else:
                out = struct.pack('<II', (first + hexval(raw[0x24])) & 0xffffffff,
                                  struct.unpack_from('<I', raw, 0x30)[0]) + bytes(raw[0xc0:0xe0])
            if memory_writer:
                memory_writer(words[6], out)
                memory_writer(msg_ptr + 4, struct.pack('<i', 0))
            self.events.append({'type': 'Backup_get_pdt_stat', 'returned': 0, 'payload_hex': out.hex()})
            return 0

        elif op in (22, 23, 24, 25):
            # preserve/restore/rewrite/protect are backed by files on flash; no file store is modeled.
            raise UnsupportedUipc('backup_file_backed_operation_not_modeled', operation=op, words=words)

        else:
            raise UnsupportedUipc('unsupported_backup_operation', operation=op, words=words)
