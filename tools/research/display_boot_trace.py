"""Reproduce bounded Package H display symbol observations; never execute updater code."""
import json
from pathlib import Path

from project_paths import PROJECT_ROOT
from tools.research.inventory import digest
from tools.research.startup_trace import analyze


def main():
    source = 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/lib/libObj.so'
    inventory = json.loads((PROJECT_ROOT / 'artifacts/inventory/elf-inventory.json').read_text(encoding='utf-8'))
    expected = next(entry['sha256'] for entry in inventory['entries'] if entry['path'] == source)
    path = PROJECT_ROOT / source
    if digest(path) != expected:
        raise ValueError('Preserved libObj.so identity mismatch')
    report = analyze(path, ['/dev/fb0'], ['ObjDisplay_Create', 'GRM_fbrmInitializeYUV'])
    guard_source = source.replace('libObj.so', 'libssp.so.0.0.0')
    guard_path = PROJECT_ROOT / guard_source
    guard_expected = next(entry['sha256'] for entry in inventory['entries'] if entry['path'] == guard_source)
    if digest(guard_path) != guard_expected:
        raise ValueError('Preserved libssp identity mismatch')
    report['stack_guard_dependency'] = analyze(
        guard_path, ['/dev/urandom'],
        explicit_blocks=[('init_array target at 0x9c5: stack guard setup', 0x9c5, 0x4a)])
    report['limitations'] = [
        'Static symbols and byte matches do not establish execution or display initialization.',
        'Absolute pointer candidates are unfiltered byte matches, not validated references.',
        'GRM_fbrmInitializeYUV returns zero in original code; its name does not establish a display path.',
        'Framebuffer geometry, format, physical address and submission semantics remain unverified.',
    ]
    output = PROJECT_ROOT / 'artifacts/execution/package-h-display-static.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(output)


if __name__ == '__main__':
    main()
