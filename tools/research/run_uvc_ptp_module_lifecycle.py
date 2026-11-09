"""Execute candidate module insmod/rmmod lifecycle on camera without activation.

Camera writes strictly confined to RAM /tmp_bt.
Preserves debugger PID 703 and all existing processes.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shlex

from tools.camera_debugger import connect
from tools.research.build_uvc_composite_module import ROOT


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--module', type=Path, required=True, help='Candidate .ko file')
    parser.add_argument('--output-dir', type=Path, required=True, help='Directory to store lifecycle receipts')
    args = parser.parse_args()

    module_path = args.module.resolve()
    out = args.output_dir.resolve()
    if not out.is_relative_to(ROOT / 'artifacts'):
        parser.error('Output must remain under artifacts')
    out.mkdir(parents=True, exist_ok=False)

    module_bytes = module_path.read_bytes()
    module_sha = digest(module_bytes)

    suffix = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')
    remote = f'/tmp_bt/uvc_shared_lifecycle_{suffix}.ko'
    report = {
        'status': 'started',
        'captured_utc': datetime.now(timezone.utc).isoformat(),
        'camera_payload': remote,
        'module_sha256': module_sha,
        'module_bytes': len(module_bytes),
        'mode_switch': False,
        'video_device_open': False,
        'activation_ioctl': False,
        'camera_payload_writes': '/tmp_bt only',
        'files': {}
    }

    def save():
        (out / 'manifest.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')

    def artifact(name, raw):
        (out / name).write_bytes(raw)
        report['files'][name] = {'bytes': len(raw), 'sha256': digest(raw)}

    save()

    with connect() as dbg:
        # 1. Debugger before
        dbg_before = dbg.request(1)['payload']
        artifact('debugger-before.txt', dbg_before)

        # 2. Modules before
        mods_before, _ = dbg.read_all('/proc/modules', 64 * 1024)
        artifact('modules-before.txt', mods_before)
        if b'usbg_video' in mods_before:
            raise RuntimeError('usbg_video already loaded before test')

        # 3. Upload & verify
        chk = dbg.request(3, f'test ! -e {shlex.quote(remote)}'.encode())
        if chk['status'] or chk['flags']:
            raise RuntimeError('Remote payload path already exists')
        upload_res = dbg.push(remote, module_bytes)
        report['upload'] = upload_res
        save()

        # 4. insmod
        insmod_res = dbg.request(3, f'insmod {shlex.quote(remote)}'.encode())
        artifact('insmod-output.txt', insmod_res['payload'])
        report['insmod'] = {'status': insmod_res['status'], 'flags': insmod_res['flags']}
        save()
        if insmod_res['status'] != 0:
            dmesg_fail = dbg.request(3, b'dmesg | tail -n 30')['payload']
            artifact('kernel-log-failure.txt', dmesg_fail)
            dbg.request(3, f'rm -f {shlex.quote(remote)}'.encode())
            raise RuntimeError(f'insmod failed with status {insmod_res["status"]}')

        # 5. Modules loaded
        mods_loaded, _ = dbg.read_all('/proc/modules', 64 * 1024)
        artifact('modules-loaded.txt', mods_loaded)
        loaded_lines = [l.decode(errors='replace') for l in mods_loaded.splitlines() if l.startswith(b'usbg_video')]
        report['loaded_module_lines'] = loaded_lines
        save()
        if not loaded_lines:
            dbg.request(3, b'rmmod usbg_video')
            dbg.request(3, f'rm -f {shlex.quote(remote)}'.encode())
            raise RuntimeError('usbg_video missing from /proc/modules after insmod')

        # 6. rmmod
        rmmod_res = dbg.request(3, b'rmmod usbg_video')
        artifact('rmmod-output.txt', rmmod_res['payload'])
        report['rmmod'] = {'status': rmmod_res['status'], 'flags': rmmod_res['flags']}
        save()
        if rmmod_res['status'] != 0:
            raise RuntimeError(f'rmmod failed with status {rmmod_res["status"]}')

        # 7. Modules after
        mods_after, _ = dbg.read_all('/proc/modules', 64 * 1024)
        artifact('modules-after.txt', mods_after)
        report['module_absent_after'] = (b'usbg_video' not in mods_after)
        if b'usbg_video' in mods_after:
            raise RuntimeError('usbg_video still present after rmmod')

        # 8. Clean up remote file
        dbg.request(3, f'rm -f {shlex.quote(remote)}'.encode())

        # 9. Debugger after
        dbg_after = dbg.request(1)['payload']
        artifact('debugger-after.txt', dbg_after)

        # 10. Status of PID 149
        status_149, _ = dbg.read_all('/proc/149/status', 16 * 1024)
        artifact('status-final.txt', status_149)

        # 11. Kernel log via dmesg
        dmesg_res = dbg.request(3, b'dmesg | tail -n 40')
        artifact('kernel-log-after.txt', dmesg_res['payload'])

        report['status'] = 'lifecycle_passed'
        save()

    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
