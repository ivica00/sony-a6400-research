"""One-time Senser bootstrap; later debugger commands use native USB MSC/MTP."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'Sony-PMCA-RE'))

from src.a6400.targets.usb_debugger_compat import (  # noqa: E402
    DebuggerTargetSpec,
    get_debugger_target,
    list_debugger_targets,
    load_reference_usb_extcmd,
    verify_camera_debugger_compatibility,
)


def deploy(cam, spec: DebuggerTargetSpec, *, check_only: bool = False):
    destination = ROOT / 'artifacts/hardware' / (
        f"native-usb-debug-{'check' if check_only else 'deploy'}-{spec.target_id}-"
        + datetime.now().strftime('%Y%m%d-%H%M%S')
    )
    destination.mkdir(parents=True, exist_ok=False)
    previous = cam.readFile('/etc/ld.so.preload')
    (destination / 'ld.so.preload.before').write_bytes(previous)

    manifest = {
        'target_id': spec.target_id,
        'model_name': spec.model_name,
        'qualification': spec.qualification,
        'check_only': check_only,
        'bootstrap_mode': 'Senser',
        'operating_transport': 'native Sony USB external command',
        'feature': 35,
        'network_listeners': False,
        'files': {},
    }

    actual_ko = cam.readFile('/usr/kmod/usb_extcmd.ko')
    (destination / 'kmod__usb_extcmd.ko').write_bytes(actual_ko)
    actual_lib = cam.readFile('/usr/lib/libusbcmd.so')
    (destination / 'lib__libusbcmd.so').write_bytes(actual_lib)

    ref_path, ref_ko = load_reference_usb_extcmd(spec, ROOT)
    compat = verify_camera_debugger_compatibility(spec, actual_ko, actual_lib, ref_ko)
    compat['reference_usb_extcmd'] = (
        str(ref_path.relative_to(ROOT)) if ref_path is not None else 'normalized_sha256_only'
    )
    manifest['compatibility'] = compat

    if not compat['compatible']:
        manifest['state'] = 'stopped_before_payload_upload'
        (destination / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        print(destination)
        raise RuntimeError('Camera driver/API differs from qualified target spec: ' + str(compat['reason']))

    if check_only:
        manifest['state'] = 'check_only_compatible'
        (destination / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        print('Read-only compatibility check passed (no files written to camera).')
        print(destination)
        return

    for local, remote in [
        (spec.payload_daemon, '/setting/a6400_usb_debugd.elf'),
        (spec.payload_launcher, '/setting/usb_debug_launcher.so'),
    ]:
        data = (ROOT / local).read_bytes()
        if len(data) >= 32768:
            raise RuntimeError('Payload exceeds verified small-transfer bound')
        cam.writeFile(remote, data)
        if cam.readFile(remote) != data:
            raise RuntimeError('Upload verification failed; preload unchanged')
        manifest['files'][remote] = {
            'bytes': len(data),
            'sha256': hashlib.sha256(data).hexdigest(),
            'readback_verified': True,
        }

    desired = previous
    if b'/setting/usb_debug_launcher.so' not in previous.split():
        prefix = previous.rstrip()
        desired = (prefix + b'\n/setting/usb_debug_launcher.so\n') if prefix else b'/setting/usb_debug_launcher.so\n'
    cam.writeFile('/etc/ld.so.preload', desired)
    actual = cam.readFile('/etc/ld.so.preload')
    (destination / 'ld.so.preload.after').write_bytes(actual)
    if actual != desired:
        raise RuntimeError('Preload read-back mismatch')
    manifest['preload_verified'] = True
    manifest['state'] = 'deployed_and_verified'
    (destination / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print('Uploaded and verified; native USB registration/runtime permissions still need testing.')
    print(destination)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Verify or deploy native Sony USB debugger via Senser.')
    parser.add_argument(
        '--target',
        default='ilce_6400',
        choices=list_debugger_targets(),
        help='Qualified camera target ID (default: ilce_6400).',
    )
    parser.add_argument(
        '--check-only',
        action='store_true',
        help='Read-only pull and compatibility check without writing to /setting or /etc/ld.so.preload.',
    )
    args = parser.parse_args(argv)
    from pmca.commands.usb import senserShellCommand  # noqa: E402
    spec = get_debugger_target(args.target)
    state = {'completed': False}

    def run(cam):
        deploy(cam, spec, check_only=args.check_only)
        state['completed'] = True

    senserShellCommand(driverName='libusb', complete=run)
    return 0 if state['completed'] else 2


if __name__ == '__main__':
    sys.exit(main())
