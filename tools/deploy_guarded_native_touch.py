"""Stage the exact guarded native-touch experiment; --apply requires user approval."""
import argparse
import hashlib
import json
import sys
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'Sony-PMCA-RE'))


def deploy(cam):
    data = (ROOT / 'devcrashday_a6400/hook/touch_native_guarded_v1.so').read_bytes()
    before = cam.readFile('/etc/ld.so.preload')
    if before.strip() not in (b'/setting/touch_probe_v1.so', b'/setting/touch_native_guarded_v1.so'):
        raise RuntimeError('Unexpected existing preload; refusing replacement')
    try:
        cam.readFile('/setting/touch_native_guarded_v3.log')
    except Exception as error:
        if str(error) != 'Senser file control error 130':
            raise
    else:
        raise RuntimeError('A previous attempt log exists; refusing to rearm automatically')
    destination = ROOT / 'artifacts/hardware' / ('native-touch-deploy-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
    destination.mkdir(parents=True, exist_ok=False)
    (destination / 'ld.so.preload.before').write_bytes(before)
    (destination / 'payload.sha256').write_text(hashlib.sha256(data).hexdigest(), encoding='ascii')
    cam.writeFile('/setting/touch_native_guarded_v1.so', data)
    if cam.readFile('/setting/touch_native_guarded_v1.so') != data:
        raise RuntimeError('Upload read-back mismatch; preload not changed')
    desired = b'/setting/touch_native_guarded_v1.so\n'
    cam.writeFile('/etc/ld.so.preload', desired)
    after = cam.readFile('/etc/ld.so.preload')
    (destination / 'ld.so.preload.after').write_bytes(after)
    if after != desired:
        raise RuntimeError('Preload read-back mismatch')
    print('Deployment verified; runtime patching and touch behavior remain unverified.')
    print(destination)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='Deploy only after explicit runtime-patch approval')
    args = parser.parse_args()
    if args.apply:
        from pmca.commands.usb import senserShellCommand
        senserShellCommand(driverName='libusb', complete=deploy)
    else:
        binary = ROOT / 'devcrashday_a6400/hook/touch_native_guarded_v1.so'
        print(json.dumps({'state': 'prepared, not deployed', 'bytes': binary.stat().st_size,
                          'sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
                          'changes': ['InputService setTpEventSw: 04 46 -> 01 24 only if full function matches',
                                      'Menu setTouchable: two-byte CBZ replaced with NOP only if full function matches'],
                          'persistent': '/etc/ld.so.preload points to experimental library until removed',
                          'sd_writes': False}, indent=2))
