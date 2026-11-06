"""Probe existing USB debug capabilities without Senser or updater mode."""
import sys
import json
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'Sony-PMCA-RE'))
from pmca.commands.usb import importDriver, listDevices
from pmca.usb.sony import SonyMscExtCmdDevice, SonyExtCmdCamera
from pmca.platform.backend.usb import UsbPlatformBackend


def main():
    report = {'mode_switches': False, 'updater_execution': False, 'probes': {}}
    destination = ROOT / 'artifacts/hardware' / ('usb-debug-probe-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
    destination.mkdir(parents=True, exist_ok=False)
    with importDriver('libusb') as driver:
        devices = list(listDevices(driver))
        candidates = [d for d in devices if isinstance(d, SonyMscExtCmdDevice)]
        if len(candidates) != 1:
            report['error'] = 'Expected one existing mass-storage camera; found ' + str(len(candidates))
        else:
            device = candidates[0]
            for name, probe in [('camera_info', lambda: SonyExtCmdCamera(device).getCameraInfo()._asdict()),
                                ('existing_pmca_debug_TEST', lambda: UsbPlatformBackend(device)._req(b'TEST'))]:
                try:
                    value = probe()
                    report['probes'][name] = {'ok': True, 'result': value}
                except Exception as exc:
                    report['probes'][name] = {'ok': False, 'error': repr(exc),
                                             'cause': repr(exc.__context__)}
    (destination / 'manifest.json').write_text(json.dumps(report, indent=2, default=lambda x: x.hex() if isinstance(x, bytes) else str(x)), encoding='utf-8')
    print(json.dumps(report, indent=2, default=lambda x: '<binary data>' if isinstance(x, bytes) else str(x)))
    print(destination)


if __name__ == '__main__':
    main()
