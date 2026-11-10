"""Read-only camera display ground truth through the native USB debugger.

Only the installed MSC external-command debugger is used.  The helper opens
/dev/stream read-only, maps OSD/Sugilite pages with PROT_READ and writes its
own bounded dumps under /tmp_bt.  No camera mode switch, Senser/updater, SD
write, display write or arbitrary host path is used.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

from project_paths import PROJECT_ROOT
from src.a6400.execution.guest_display import (
    DISPLAY_SURFACES, rgb565_to_rgba, rgba4444_to_rgba, surface_to_image,
)

OSD_A = DISPLAY_SURFACES['osd_a']
OSD_B = DISPLAY_SURFACES['osd_b']
SUGILITE = DISPLAY_SURFACES['sugilite_color0']
HELPER_REMOTE = '/tmp_bt/a6400_capture_display.elf'
CHUNK = 512 * 1024
OSD_SIZE = OSD_A.byte_size
SUGILITE_SIZE = SUGILITE.byte_size


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def remote_read(debugger, path: str, size: int) -> bytes:
    data = bytearray()
    while len(data) < size:
        block = debugger.read(path, len(data), min(4064, size - len(data)))
        if not block:
            raise ValueError(f'Camera file ended early at {len(data)}/{size}: {path}')
        data.extend(block)
    if len(data) != size:
        raise ValueError(f'Camera read length mismatch: {len(data)} != {size}')
    return bytes(data)


def exec_command(debugger, command: str) -> dict:
    result = debugger.request(3, command.encode())
    return {'command': command, 'status': result['status'], 'flags': result['flags'],
            'output': result['payload'].decode(errors='replace')}


def capture(debugger, out: Path, helper: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    info = debugger.request(1)['payload'].decode(errors='replace')
    (out / 'debugger-info.txt').write_text(info, encoding='utf-8')
    uploaded = debugger.push(HELPER_REMOTE, helper.read_bytes())
    chmod = exec_command(debugger, f'chmod 700 {HELPER_REMOTE}')
    if chmod['status'] != 0:
        raise RuntimeError(f'chmod failed for helper: {chmod}')
    manifest = {
        'kind': 'read-only camera display ground truth',
        'camera_modes_switched': False,
        'senser_used': False,
        'sd_written': False,
        'display_written': False,
        'helper': uploaded,
        'out': str(out),
        'raw': {},
        'decoded': {},
        'commands': [],
    }
    manifest['commands'].append(chmod)

    def one(surface: str, offset: int, size: int, stem: str) -> bytes:
        remote = f'/tmp_bt/{stem}.raw'
        command = f'{HELPER_REMOTE} {surface} {offset} {size} {remote}'
        record = exec_command(debugger, command)
        manifest['commands'].append(record)
        if record['status'] != 0:
            raise RuntimeError(f'Helper failed for {stem}: {record}')
        data = remote_read(debugger, remote, size)
        (out / f'{stem}.raw').write_bytes(data)
        manifest['raw'][stem] = {'surface': surface, 'offset': offset, 'bytes': len(data),
                                 'sha256': sha256(data), 'remote': remote}
        cleanup = exec_command(debugger, f'rm -f {remote}')
        manifest['commands'].append(cleanup)
        return data

    try:
        osd_a = one('osd_a', 0, OSD_SIZE, 'osd_a')
        osd_b = one('osd_b', 0, OSD_SIZE, 'osd_b')
        sug_a = one('sugilite', 0, CHUNK, 'sugilite_a')
        sug_b = one('sugilite', CHUNK, SUGILITE_SIZE - CHUNK, 'sugilite_b')
    except Exception as error:
        manifest['error'] = {'type': type(error).__name__, 'message': str(error)}
        (out / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        raise
    sugilite = sug_a + sug_b

    def save_image(stem: str, rgba: bytes, surface) -> None:
        path = out / f'{stem}.png'
        surface_to_image(surface, rgba).save(path)
        manifest['decoded'][stem] = {'png': path.name,
                                     'png_sha256': sha256(path.read_bytes()),
                                     'pixels': surface.pixel_count,
                                     'format': surface.pixel_format,
                                     'format_source': surface.format_source}

    save_image('osd_a-rgba4444', rgba4444_to_rgba(osd_a, OSD_A.width, OSD_A.height), OSD_A)
    save_image('osd_b-rgba4444', rgba4444_to_rgba(osd_b, OSD_B.width, OSD_B.height), OSD_B)
    save_image('sugilite-rgba4444', rgba4444_to_rgba(sugilite, SUGILITE.width, SUGILITE.height), SUGILITE)
    save_image('sugilite-rgb565', rgb565_to_rgba(sugilite, SUGILITE.width, SUGILITE.height), SUGILITE)

    summary = exec_command(debugger, f'{HELPER_REMOTE} summary')
    manifest['commands'].append(summary)
    (out / 'gl-common-summary.txt').write_text(summary['output'], encoding='utf-8')
    manifest['gl_common_summary'] = {'status': summary['status'],
                                     'nonzero_total': _summary_total(summary['output'])}

    cleanup = exec_command(debugger, f'rm -f {HELPER_REMOTE}')
    manifest['commands'].append(cleanup)
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    return manifest


def _summary_total(text: str):
    for line in text.splitlines():
        if line.startswith('GL_COMMON nonzero_total='):
            try:
                return int(line.split('=', 1)[1])
            except ValueError:
                return None
    return None


def compare_manifest(manifest: dict, frame_receipt: dict) -> dict:
    """Compare the verified geometry/format fields; no pixel-identity claim."""
    osd = manifest['raw'].get('osd_a', {})
    return {
        'camera_osd_bytes': osd.get('bytes'),
        'camera_osd_surface': 'osd_a',
        'emulator_surface': frame_receipt.get('surface'),
        'emulator_format': frame_receipt.get('pixel_format'),
        'emulator_format_source': frame_receipt.get('format_source'),
        'note': ('Geometry/format comparison only; OSD A/B are not mapped in the emulator, '
                 'so the camera OSD is a reference for the display contract, not an emulator frame.'),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--helper', type=Path,
                        default=PROJECT_ROOT / 'devcrashday_a6400/capture_display_readonly.elf')
    parser.add_argument('--out', type=Path, default=PROJECT_ROOT / 'artifacts/display/camera')
    parser.add_argument('--compare', type=Path, default=None,
                        help='optional emulator frame receipt JSON to describe the contract comparison')
    args = parser.parse_args()
    if not args.helper.exists():
        parser.error(f'Helper not built: {args.helper}')
    sys.path.insert(0, str(PROJECT_ROOT))
    from tools.camera_debugger import connect
    with connect() as debugger:
        manifest = capture(debugger, args.out, args.helper)
    if args.compare and args.compare.exists():
        receipt = json.loads(args.compare.read_text(encoding='utf-8'))
        manifest['comparison'] = compare_manifest(manifest, receipt)
        (args.out / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(json.dumps({'out': str(args.out), 'raw': manifest['raw'],
                      'gl_common_nonzero': manifest['gl_common_summary']['nonzero_total']}, indent=2))


if __name__ == '__main__':
    main()
