"""Recover identified logging input/state from preserved package WBI memory."""
import hashlib
import argparse
import json
import struct

from project_paths import PROJECT_ROOT
from tools.research.rea_wsl_batch import checked_input
from tools.research.wbi_memory import IMAGE, parse_sections, decode_section

STATE_PHYSICAL = 0x089294c4


class PackageMemory:
    def __init__(self, raw):
        self.raw = raw
        self.header, self.sections = parse_sections(raw)
        ordered = sorted(self.sections, key=lambda s: s['physical'])
        if any(a['physical'] + a['size'] > b['physical'] for a, b in zip(ordered, ordered[1:])):
            raise ValueError('Ambiguous overlapping WBI physical ranges')
        self.decoded = {}

    def read(self, address, size):
        if not 0 <= address <= 0xffffffff or not 0 <= size <= 4 * 1024 * 1024 or address + size > 1 << 32:
            raise ValueError('Physical observation exceeds bounds')
        result = bytearray()
        while size:
            section = next((s for s in self.sections if s['physical'] <= address < s['physical'] + s['size']), None)
            if section is None:
                raise ValueError('Unsupplied WBI physical memory at ' + hex(address))
            index = section['index']
            if index not in self.decoded:
                self.decoded[index] = decode_section(self.raw, section)[0]
            offset = address - section['physical']
            count = min(size, section['size'] - offset)
            result.extend(self.decoded[index][offset:offset + count])
            address += count
            size -= count
        return bytes(result)


def cached_physical(address):
    if not 0x60000000 <= address < 0xa0000000:
        raise ValueError('Unsupported captured cached-pointer range')
    return address - 0x60000000


def records(data):
    position, result = 0, []
    while position < len(data):
        if len(result) >= 4096 or position + 8 > len(data):
            raise ValueError('Truncated or excessive logging tags')
        size, tag = struct.unpack_from('<I4s', data, position)
        if size < 8 or size % 4 or position + size > len(data) or not all(32 <= c < 127 for c in tag):
            raise ValueError('Invalid logging tag range/type')
        result.append({'offset': position, 'size': size, 'tag': tag.decode(), 'payload_hex': data[position + 8:position + size].hex()})
        position += size
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report-dir', default='artifacts/analysis/wbi-logging-recovered')
    args = parser.parse_args()
    inputs = json.loads((PROJECT_ROOT / 'artifacts/inventory/baseline.json').read_text(encoding='utf-8'))['inputs']
    digest = next(row['sha256'] for row in inputs if row['path'] == IMAGE)
    memory = PackageMemory(checked_input(PROJECT_ROOT, IMAGE, digest))
    state = struct.unpack('<8I', memory.read(STATE_PHYSICAL, 32))
    pointer, length, filename = state[:3]
    expected_name = b'/setting/ulogio.bin\0'
    if not 0 < length <= 65536 or memory.read(cached_physical(filename), len(expected_name)) != expected_name:
        raise ValueError('Captured module input tuple does not identify the expected logging file')
    config = memory.read(cached_physical(pointer), length)
    tags = records(config)
    required = {'LGNM', 'RECO', 'LOGB', 'DBGL', 'PRTB'}
    if not required <= {r['tag'] for r in tags}:
        raise ValueError('Captured file lacks mandatory logging tags')
    logb = [t for t in tags if t['tag'] == 'LOGB']
    if len(logb) != 1 or logb[0]['size'] != 16:
        raise ValueError('Ambiguous logging backing range')
    base, size = struct.unpack('<II', bytes.fromhex(logb[0]['payload_hex']))
    root = struct.unpack('<15I', memory.read(base, 60))
    if root[0] != 0x474f4c55 or cached_physical(state[7]) != base or cached_physical(root[2]) != base or root[14] + 60 != size:
        raise ValueError('Captured config, module state and ULOG root disagree')
    subsystems, cursor = [], base + 60
    if not 0 < root[3] <= 256:
        raise ValueError('Unsupported subsystem count')
    for index in range(root[3]):
        head = memory.read(cursor, 20)
        magic, subsystem, span = struct.unpack_from('<3I', head)
        count = struct.unpack_from('<H', head, 14)[0]
        if magic != 0x53425553 or count > 256 or span < 20 + count * 8 or cursor + span > base + size:
            raise ValueError('Captured subsystem escapes logging memory')
        areas = []
        for area, (extent, ptr) in enumerate(struct.iter_unpack('<II', memory.read(cursor + 20, count * 8))):
            physical = cached_physical(ptr) if ptr else None
            if physical is not None and not cursor <= physical < physical + extent <= cursor + span:
                raise ValueError('Captured area escapes its subsystem')
            areas.append({'area': area, 'size': extent, 'cached_pointer': ptr, 'physical': physical})
        subsystems.append({'index': index, 'physical': cursor, 'id': subsystem, 'size': span, 'areas': areas})
        cursor = (cursor + span + 3) & ~3
    selected = [s for s in subsystems if s['id'] == 0x61]
    if len(selected) != 1 or not selected[0]['areas']:
        raise ValueError('DMM subsystem/area is absent or ambiguous')
    dmm = selected[0]['areas'][0]
    if dmm['physical'] is None or dmm['size'] < 0xfb00:
        raise ValueError('DMM log extent is absent or too short')
    markers = []
    for offset, expected in ((0x24, 0x51434f4c), (0x1588, 0x51564452), (0x1aac, 0x4c545845),
                             (0xfab0, 0x56415350), (0xfaf8, 0x4c444e45)):
        value = struct.unpack('<I', memory.read(dmm['physical'] + offset, 4))[0]
        markers.append({'offset': offset, 'value': value, 'expected': expected, 'matches': value == expected})
    output = (PROJECT_ROOT / args.report_dir).resolve()
    if not output.is_relative_to(PROJECT_ROOT / 'artifacts'):
        parser.error('Output must remain under artifacts')
    output.mkdir(parents=True, exist_ok=False)
    (output / 'ulogio.bin').write_bytes(config)
    report = {'input': {'path': IMAGE, 'sha256': digest}, 'module_state_physical': STATE_PHYSICAL,
        'module_state_words': list(state), 'config_physical': cached_physical(pointer), 'config_size': length,
        'config_sha256': hashlib.sha256(config).hexdigest(), 'tags': tags,
        'logging_physical': base, 'logging_size': size, 'root_words': list(root),
        'subsystems': subsystems, 'dmm_subsystem': selected[0], 'dmm_markers': markers,
        'decoded_sections': sorted(memory.decoded),
        'limitations': ['Identified packaged warm-boot memory, not current camera state or a mounted partition-2 image.',
            'Tuple/layout agreement is not complete loaded-module identity validation or successful driver boot.',
            'No guest response or MMIO/timestamp invented; no application contract changed.']}
    (output / 'manifest.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(output / 'manifest.json')
    print('recovered /setting/ulogio.bin:', length, report['config_sha256'])
    print('DMM area:', dmm, 'markers:', [m['matches'] for m in markers])


if __name__ == '__main__':
    main()
