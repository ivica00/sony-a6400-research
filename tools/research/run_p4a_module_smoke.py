"""P4a: bounded e0212 module load/unload smoke test in Mass Storage.

No INIT, no PC Remote switch, no UVC session. Writes only owned /tmp_bt files.
"""
import argparse
import hashlib
import json
import re
import shlex
import time
from datetime import datetime, timezone
from pathlib import Path

from tools.camera_debugger import connect

ROOT = Path(__file__).resolve().parents[2]
OOPS = (b'Oops', b'BUG:', b'Unable to handle kernel', b'Kernel panic', b'Internal error')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output-dir', required=True, type=Path)
    p.add_argument('--module-build', type=Path,
                   default=ROOT / 'artifacts/native/uvc-ptp-module-e0212')
    args = p.parse_args()
    out = args.output_dir.resolve()
    if not out.is_relative_to(ROOT / 'artifacts'):
        p.error('Output must be under artifacts')
    out.mkdir(parents=True, exist_ok=False)

    module_file = args.module_build.resolve() / 'usbg_video_a6400_shared_candidate.ko'
    raw = module_file.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    manifest = json.loads((args.module_build.resolve() / 'manifest.json').read_text())
    if manifest.get('sha256') != sha or manifest.get('size_bytes') != len(raw):
        raise ValueError('Module build identity mismatch')

    stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
    remote_mod = f'/tmp_bt/p4a_{stamp}.ko'
    remote_klog = f'/tmp_bt/p4a_{stamp}.klog'
    report = {
        'status': 'started', 'mode': 'p4a_module_smoke', 'camera_access': True,
        'module_sha256': sha, 'module_bytes': len(raw), 'module_build': str(module_file),
        'paths': {'module': remote_mod, 'klog': remote_klog},
        'files': {},
    }

    def save():
        (out / 'manifest.json').write_text(json.dumps(report, indent=2) + '\n')

    def artifact(name, data):
        (out / name).write_bytes(data)
        report['files'][name] = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}

    def command(dbg, text, name):
        res = dbg.request(3, text.encode())
        artifact(name + '.txt', res['payload'])
        report[name] = {'status': res['status'], 'flags': res['flags']}
        save()
        if res['status'] or res['flags']:
            raise RuntimeError(f'{name} failed: {text}')
        return res['payload']

    def has_oops(data):
        return [m.decode('ascii', 'replace') for m in OOPS if m in data]

    loaded = False
    try:
        with connect() as dbg:
            uptime_before, _ = dbg.read_all('/proc/uptime', 4096)
            artifact('uptime-before.txt', uptime_before)
            modules_before, _ = dbg.read_all('/proc/modules', 1 << 16)
            artifact('modules-before.txt', modules_before)
            status_before, _ = dbg.read_all('/proc/149/status', 16384)
            artifact('status-before.txt', status_before)
            if any(l.startswith(b'usbg_video ') for l in modules_before.splitlines()):
                raise RuntimeError('usbg_video already loaded')
            if not re.search(rb'^TracerPid:\s+0$', status_before, re.M):
                raise RuntimeError('TracerPid is not 0')

            report['upload'] = dbg.push(remote_mod, raw)
            save()
            command(dbg, f'insmod {shlex.quote(remote_mod)}', 'insmod')
            loaded = True
            modules_loaded, _ = dbg.read_all('/proc/modules', 1 << 16)
            artifact('modules-loaded.txt', modules_loaded)
            report['module_visible'] = any(l.startswith(b'usbg_video ') for l in modules_loaded.splitlines())
            if not report['module_visible']:
                raise RuntimeError('module not visible after insmod')

            command(dbg, f'dmesg > {shlex.quote(remote_klog)}', 'dmesg-load')
            dmesg_load, _ = dbg.read_all(remote_klog, 1 << 20)
            artifact('dmesg-after-load.txt', dmesg_load)
            report['dmesg_load_oops'] = has_oops(dmesg_load)
            if report['dmesg_load_oops']:
                raise RuntimeError('kernel oops after load')

            command(dbg, 'rmmod usbg_video', 'rmmod')
            loaded = False
            modules_after, _ = dbg.read_all('/proc/modules', 1 << 16)
            artifact('modules-after.txt', modules_after)
            report['module_list_restored'] = modules_after == modules_before
            if not report['module_list_restored']:
                raise RuntimeError('module list not restored after rmmod')

            command(dbg, f'dmesg > {shlex.quote(remote_klog)}', 'dmesg-unload')
            dmesg_unload, _ = dbg.read_all(remote_klog, 1 << 20)
            artifact('dmesg-after-unload.txt', dmesg_unload)
            report['dmesg_unload_oops'] = has_oops(dmesg_unload)
            uptime_after, _ = dbg.read_all('/proc/uptime', 4096)
            artifact('uptime-after.txt', uptime_after)
            report['reboot'] = float(uptime_after.split()[0]) < float(uptime_before.split()[0])
            if report['dmesg_unload_oops'] or report['reboot']:
                raise RuntimeError('oops or reboot after unload')

            status_after, _ = dbg.read_all('/proc/149/status', 16384)
            artifact('status-after.txt', status_after)
            report['tracer_clean_after'] = bool(re.search(rb'^TracerPid:\s+0$', status_after, re.M))
            report['status'] = ('p4a_module_smoke_passed'
                                if report['tracer_clean_after'] else 'failed')
            save()
    except Exception as exc:
        report['error'] = repr(exc)
        report['status'] = 'failed'
        save()
        if loaded:
            try:
                with connect() as dbg:
                    dbg.request(3, b'rmmod usbg_video')
            except Exception as cleanup_error:
                report['cleanup_error'] = repr(cleanup_error)
                save()
    finally:
        try:
            with connect() as dbg:
                for path in (remote_mod, remote_klog):
                    dbg.request(3, f'rm -f {shlex.quote(path)}'.encode())
                listing = dbg.request(3, b'ls /tmp_bt')['payload']
                names = listing.decode('ascii', 'replace')
                report['tmp_bt_owned_left'] = [n for n in (remote_mod, remote_klog) if n.rsplit('/', 1)[-1] in names]
                save()
        except Exception as cleanup_error:
            report['tmp_bt_cleanup_error'] = repr(cleanup_error)
            save()

    print(json.dumps(report, indent=2))
    if report['status'] != 'p4a_module_smoke_passed':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
