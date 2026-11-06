"""Remove only the known unsafe touch preload entries; preserve other entries."""
import sys
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'Sony-PMCA-RE'))
from pmca.commands.usb import senserShellCommand


def disable(cam):
    original = cam.readFile('/etc/ld.so.preload')
    entries = {b'/setting/input_sniffer.so', b'/tmp/input_sniffer.so', b'/tmp/menu_touch_tab.so'}
    replacement = b''.join(line for line in original.splitlines(keepends=True) if line.strip() not in entries)
    dest = ROOT / 'artifacts' / 'hardware' / ('touch-disable-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
    dest.mkdir(parents=True, exist_ok=False)
    (dest / 'ld.so.preload.before').write_bytes(original)
    if replacement != original:
        cam.writeFile('/etc/ld.so.preload', replacement)
    verified = cam.readFile('/etc/ld.so.preload')
    (dest / 'ld.so.preload.after').write_bytes(verified)
    if verified != replacement:
        raise RuntimeError('Preload read-back mismatch')
    print('VERIFIED: unsafe touch preload entries removed; other entries preserved.')
    print('This does not undo existing RAM patches. No SD card writes performed.')
    print('Evidence:', dest)


if __name__ == '__main__':
    senserShellCommand(driverName='libusb', complete=disable)
