"""Read existing touch diagnostics; never deploy a payload or write to the SD card."""
import json
import io
import argparse
import sys
import traceback
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'Sony-PMCA-RE'))
from pmca.commands.usb import senserShellCommand


def inspect(cam, include_legacy_log=False):
    destination = ROOT / 'artifacts' / 'hardware' / ('touch-inspect-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
    destination.mkdir(parents=True, exist_ok=False)
    results = {}
    paths = ['/etc/ld.so.preload', '/setting/touch_native_guarded_v3.log', '/setting/touch_native_guarded_v2.log', '/setting/touch_native_guarded_v1.log', '/setting/touch_probe_maps_v2.log', '/setting/touch_probe_v1.log', '/setting/touch_probe_maps_v1.log', '/tmp/input_dump.log',
                   '/tmp/touch_tab.log', '/tmp/touch_daemon.pid', '/proc/bus/input/devices',
                   '/proc/149/maps', '/proc/mounts']
    if include_legacy_log:
        paths.append('/setting/input_dump.log')
    for remote in paths:
        buffer = io.BytesIO()
        local = remote.strip('/').replace('/', '__')
        try:
            cam.readFile(remote, buffer)
            data = buffer.getvalue()
            (destination / local).write_bytes(data)
            results[remote] = {'bytes': len(data), 'file': local}
            if remote in ['/etc/ld.so.preload', '/setting/touch_native_guarded_v3.log', '/setting/touch_native_guarded_v2.log', '/setting/touch_native_guarded_v1.log', '/setting/touch_probe_maps_v2.log', '/setting/touch_probe_v1.log', '/setting/touch_probe_maps_v1.log', '/setting/input_dump.log', '/tmp/touch_tab.log', '/proc/bus/input/devices']:
                print(remote, data[-16000:].decode(errors='replace'))
        except Exception as exc:
            data = buffer.getvalue()
            (destination / (local + '.partial')).write_bytes(data)
            results[remote] = {'error': repr(exc), 'traceback': traceback.format_exc(),
                               'partial_bytes': len(data), 'partial_file': local + '.partial'}
            print(remote, repr(exc), 'partial_bytes=', len(data))
            if data:
                print(data[-16000:].decode(errors='replace'))
            # A failed bulk transfer may leave the protocol out of sync. Do not
            # mistake subsequent transport failures for missing remote files.
            from pmca.usb.driver.generic import GenericUsbException
            if isinstance(exc, GenericUsbException):
                print('Stopping reads after transport failure; partial response preserved.')
                break
    (destination / 'manifest.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
    print('Saved:', destination)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--include-legacy-log', action='store_true',
                        help='Read the large historical log last; it may time out.')
    args = parser.parse_args()
    senserShellCommand(driverName='libusb', complete=lambda cam: inspect(cam, args.include_legacy_log))
