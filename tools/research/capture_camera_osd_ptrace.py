"""Read the camera's OSD buffers through an existing process mapping.

Safer than opening /dev/stream from an external process: the target process
(e.g. im.elf) already maps the OSD A/B pages, so this tool only performs
read-only ptrace memory reads through the installed USB debugger.  No camera
mode switch, /dev/stream open, display write or SD write is performed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

from project_paths import PROJECT_ROOT
from src.a6400.execution.guest_display import (
    DISPLAY_SURFACES, rgb565_to_rgba, rgba4444_to_rgba, surface_to_image,
)

MAP_LINE = re.compile(r'([0-9a-f]+)-([0-9a-f]+)\s+(\S{4})\s+([0-9a-f]+)\s+\S+\s+\d+\s+(\S.*)?$')
OSD_OFFSETS = {0x23A80000: 'osd_a', 0x23B16000: 'osd_b'}
GL_COMMON_PHYS = 0x202E0000
GL_COMMON_VA_OFFSET = 0x1000          # Sugilite colour-buffer 0 candidate
GL_COMMON_SURFACE_BYTES = 960 * 540 * 2
CHUNK = 4064


def parse_all_stream_mappings(maps_text: str) -> dict:
    """Return every /dev/stream mapping keyed by its physical offset."""
    found = {}
    for line in maps_text.splitlines():
        match = MAP_LINE.match(line)
        if not match:
            continue
        start, end, perms, offset, path = match.groups()
        if (path or '').strip() != '/dev/stream':
            continue
        physical = int(offset, 16)
        found[physical] = {'virtual_start': int(start, 16), 'virtual_end': int(end, 16),
                           'length': int(end, 16) - int(start, 16), 'physical': physical,
                           'perms': perms}
    return found


def parse_stream_mappings(maps_text: str) -> dict:
    found = {}
    for physical, mapping in parse_all_stream_mappings(maps_text).items():
        if physical not in OSD_OFFSETS:
            continue
        found[OSD_OFFSETS[physical]] = mapping
    return found


def read_mapping(debugger, pid: int, mapping: dict) -> bytes:
    data = bytearray()
    address = mapping['virtual_start']
    while len(data) < mapping['length']:
        size = min(CHUNK, mapping['length'] - len(data))
        block = debugger.memory(pid, address + len(data), size)
        if len(block) != size:
            raise ValueError(f'Short process memory read at {len(data)}/{mapping["length"]}')
        data.extend(block)
    return bytes(data)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def capture(debugger, pid: int, out: Path, both: bool = False) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    maps_text, truncated = debugger.read_all(f'/proc/{pid}/maps')
    if truncated:
        raise ValueError('Camera maps read was truncated')
    (out / 'maps.txt').write_text(maps_text.decode(errors='replace'), encoding='utf-8')
    mappings = parse_stream_mappings(maps_text.decode(errors='replace'))
    if 'osd_a' not in mappings:
        raise ValueError('Target process does not map OSD A /dev/stream 0x23A80000')
    manifest = {'kind': 'read-only OSD capture via existing process mapping',
                'pid': pid, 'both': both, 'chunks': 0, 'surfaces': {},
                'no_dev_stream_open': True, 'no_camera_write': True,
                'maps_sha256': sha256(maps_text)}
    targets = ['osd_a', 'osd_b'] if both else ['osd_a']
    for key in targets:
        mapping = mappings.get(key)
        if mapping is None:
            continue
        if mapping['length'] < DISPLAY_SURFACES[key].byte_size:
            raise ValueError(f'{key} mapping is too small: {mapping["length"]}')
        raw = read_mapping(debugger, pid, mapping)
        manifest['chunks'] += (mapping['length'] + CHUNK - 1) // CHUNK
        (out / f'{key}.raw').write_bytes(raw)
        surface = DISPLAY_SURFACES[key]
        rgba = rgba4444_to_rgba(raw[:surface.byte_size], surface.width, surface.height)
        png = out / f'{key}-rgba4444.png'
        surface_to_image(surface, rgba).save(png)
        manifest['surfaces'][key] = {
            'virtual_start': mapping['virtual_start'], 'length': mapping['length'],
            'raw': f'{key}.raw', 'raw_sha256': sha256(raw[:surface.byte_size]),
            'png': png.name, 'png_sha256': sha256(png.read_bytes()),
            'nonzero_bytes': sum(1 for byte in raw[:surface.byte_size] if byte),
        }
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    return manifest


def capture_gl_common(debugger, pid: int, out: Path) -> dict:
    """Read the Sugilite colour-buffer candidate from im.elf's gl_common mapping."""
    out.mkdir(parents=True, exist_ok=True)
    maps_text, truncated = debugger.read_all(f'/proc/{pid}/maps')
    if truncated:
        raise ValueError('Camera maps read was truncated')
    mapping = parse_all_stream_mappings(maps_text.decode(errors='replace')).get(GL_COMMON_PHYS)
    if mapping is None:
        raise ValueError('Target process does not map /dev/stream 0x202E0000')
    start = mapping['virtual_start'] + GL_COMMON_VA_OFFSET
    if start + GL_COMMON_SURFACE_BYTES > mapping['virtual_end']:
        raise ValueError('gl_common mapping does not contain the colour buffer')
    raw = read_mapping(debugger, pid, {'virtual_start': start, 'length': GL_COMMON_SURFACE_BYTES})
    (out / 'sugilite_color0.raw').write_bytes(raw)
    surface = DISPLAY_SURFACES['sugilite_color0']
    rgba = rgba4444_to_rgba(raw, surface.width, surface.height)
    png = out / 'sugilite_color0-rgba4444.png'
    surface_to_image(surface, rgba).save(png)
    rgb565 = rgb565_to_rgba(raw, surface.width, surface.height)
    png565 = out / 'sugilite_color0-rgb565.png'
    surface_to_image(surface, rgb565).save(png565)
    return {'physical': GL_COMMON_PHYS, 'virtual_start': start,
            'length': GL_COMMON_SURFACE_BYTES, 'raw_sha256': sha256(raw),
            'rgba4444_png': png.name, 'rgba4444_png_sha256': sha256(png.read_bytes()),
            'rgb565_png': png565.name, 'rgb565_png_sha256': sha256(png565.read_bytes()),
            'nonzero_bytes': sum(1 for byte in raw if byte),
            'chunks': (GL_COMMON_SURFACE_BYTES + CHUNK - 1) // CHUNK}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pid', type=int, default=149, help='camera process that maps the OSD (im.elf)')
    parser.add_argument('--out', type=Path, default=PROJECT_ROOT / 'artifacts/display/camera-ptrace')
    parser.add_argument('--both', action='store_true', help='also read OSD buffer B')
    parser.add_argument('--gl-common', action='store_true',
                        help='also read the Sugilite colour-buffer candidate from gl_common')
    args = parser.parse_args()
    import sys
    sys.path.insert(0, str(PROJECT_ROOT))
    from tools.camera_debugger import connect
    with connect() as debugger:
        manifest = capture(debugger, args.pid, args.out, both=args.both)
        if args.gl_common:
            manifest['gl_common'] = capture_gl_common(debugger, args.pid, args.out)
            (args.out / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(json.dumps({'out': str(args.out), 'pid': args.pid, 'chunks': manifest['chunks'],
                      'surfaces': {key: {'nonzero_bytes': value['nonzero_bytes'],
                                         'raw_sha256': value['raw_sha256']}
                                   for key, value in manifest['surfaces'].items()},
                      'gl_common': manifest.get('gl_common')}, indent=2))


if __name__ == '__main__':
    main()
