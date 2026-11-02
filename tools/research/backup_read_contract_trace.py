"""Compare backup descriptors with bounded original ARM getter execution."""
import json
import struct

import unicorn

from project_paths import PROJECT_ROOT
from src.a6400.execution.backup_service import BK4PresetState, DEFAULT_PRESET_REL
from tools.research.backup_state_trace import MODULE, PRESET_BASE, RETURN, prepare, call
from tools.research.liro_startup_trace import STATE, STRINGS
from tools.research.mount_evidence import checked_input


def run():
    inventory = json.loads((PROJECT_ROOT / 'artifacts/inventory/elf-inventory.json').read_text())
    expected = {entry['path']: entry['sha256'] for entry in inventory['entries']}
    baseline = json.loads((PROJECT_ROOT / 'artifacts/inventory/baseline.json').read_text())
    preserved = {entry['path']: entry['sha256'] for entry in baseline['inputs']}
    raw = checked_input(PROJECT_ROOT, MODULE, expected[MODULE])
    preset = checked_input(PROJECT_ROOT, DEFAULT_PRESET_REL, preserved[DEFAULT_PRESET_REL])
    state = BK4PresetState(preset, preserved[DEFAULT_PRESET_REL])
    elf, code, entries, ranges, patches = prepare(raw)
    state_size = elf.get_section_by_name('.bss')['sh_size']
    shared = [(STRINGS, elf.get_section_by_name('.rodata.str1.1').data(), unicorn.UC_PROT_READ),
              (RETURN, bytes(4), unicorn.UC_PROT_READ | unicorn.UC_PROT_EXEC)]
    regions = [(STATE, bytes(state_size), unicorn.UC_PROT_READ | unicorn.UC_PROT_WRITE),
               (PRESET_BASE, preset, unicorn.UC_PROT_READ), *shared]
    initialization, mu = call(code, entries['Data_init']['st_value'], ranges, regions, PRESET_BASE)
    if initialization['registers']['r0'] != 0:
        raise ValueError('Original Data_init rejected preset')
    initialized = bytes(mu.mem_read(STATE, state_size))
    regions = [(STATE, initialized, unicorn.UC_PROT_READ), regions[1], *shared]
    selected = {}
    for subsystem in range(state.subsystems):
        count = struct.unpack_from('<H', preset, 0x100 + subsystem * 6)[0]
        for prop in range(count):
            unit = (subsystem << 16) | prop
            desc = state.search_id(unit)
            if desc is None:
                continue
            flag = preset[desc.descriptor_offset + 5]
            encoding = 'variable' if flag == 0 else 'extended' if flag == 255 else 'inline-size'
            selected.setdefault(encoding, unit)
    cases = []
    for encoding, unit in selected.items():
        lookup, _ = call(code, entries['Data_SearchId']['st_value'], ranges, regions, unit)
        pointer = lookup['registers']['r0']
        desc = state.search_id(unit)
        values, traces = {}, {'lookup': lookup}
        for name in ('Data_GetSize', 'Data_GetDataPt', 'Data_GetVmaxSize', 'Data_GetAttr'):
            result, _ = call(code, entries[name]['st_value'], ranges, regions, pointer)
            values[name] = result['registers']['r0']
            traces[name] = result
        original_offset = values['Data_GetDataPt'] - PRESET_BASE
        original_size = values['Data_GetSize']
        if (desc.data_offset != original_offset or desc.size != original_size
                or desc.vmax != values['Data_GetVmaxSize'] or desc.attribute != values['Data_GetAttr']):
            raise ValueError(f'Host descriptor disagrees with original ARM getters: {encoding}')
        if state.read_unit(unit) != preset[original_offset:original_offset + original_size]:
            raise ValueError('Host data differs from original selected bytes')
        cases.append({'encoding': encoding, 'unit': unit, 'descriptor': desc.to_dict(),
                      'original_values': values, 'original_traces': traces})
    if set(selected) != {'variable', 'extended', 'inline-size'}:
        raise ValueError('Preset does not cover all descriptor encodings')
    return {'status': 'original_getters_match', 'module_sha256': expected[MODULE],
            'preset_sha256': preserved[DEFAULT_PRESET_REL], 'initialization': initialization,
            'cases': cases, 'selected_relocations': patches,
            'limitations': ['Isolated original getter execution on explicit package preset state.',
                            'No kernel IPC, locks, callbacks, device or camera-runtime state supplied.']}


def main():
    report = run()
    output = PROJECT_ROOT / 'artifacts/execution/backup-read-contract-trace.json'
    if output.exists():
        raise FileExistsError('Preserve the existing trace before rerunning')
    output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(output)
    print(report['status'], [(case['encoding'], hex(case['unit'])) for case in report['cases']])


if __name__ == '__main__':
    main()
