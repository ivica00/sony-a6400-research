"""Minimal read-only WPD presence probe (no PTP commands).

Polls Windows WPD device enumeration to test whether host WPD client activity alone
triggers the camera's PC Remote liveview start. Optionally opens/closes the device
(no vendor/PTP commands), controlled by --open.
"""
import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'Sony-PMCA-RE'))


def summarize_devices(devices):
    return [getattr(device, 'handle', None) for device in devices]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--duration', type=float, default=120.0)
    parser.add_argument('--interval', type=float, default=0.5)
    parser.add_argument('--open', action='store_true', help='Open/close the WPD device (no PTP)')
    parser.add_argument('--output-dir', required=True, type=Path)
    args = parser.parse_args()
    out = args.output_dir.resolve()
    if not out.is_relative_to(ROOT / 'artifacts'):
        parser.error('Output must be under artifacts')
    out.mkdir(parents=True, exist_ok=False)
    from pmca.usb.driver.windows.wpd import MtpContext

    context = MtpContext()
    samples = []
    started = time.time()
    while time.time() - started < args.duration:
        devices = list(context.listDevices(0x054C))
        opened = None
        if args.open and devices:
            try:
                opened = context.openDevice(devices[0])
                opened.device.Close()
            except Exception as exc:
                opened = repr(exc)
        samples.append({'utc': datetime.now(timezone.utc).isoformat(),
                        'elapsed': round(time.time() - started, 3),
                        'count': len(devices),
                        'handles': summarize_devices(devices),
                        'opened': typeof_string(opened)})
        (out / 'samples.jsonl').write_text(''.join(json.dumps(s) + '\n' for s in samples))
        time.sleep(args.interval)
    manifest = {'status': 'completed', 'duration_sec': args.duration,
                'interval_sec': args.interval, 'open': args.open,
                'samples': len(samples),
                'max_count': max((s['count'] for s in samples), default=0)}
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest, indent=2))


def typeof_string(value):
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return 'opened+closed'


if __name__ == '__main__':
    main()
