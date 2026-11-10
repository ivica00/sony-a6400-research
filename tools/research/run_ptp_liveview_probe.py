"""Capture one PTP liveview JPEG over Windows WPD during a PC Remote session.

Read-only: Sony SDIO handshake + GetObject(liveview handle). No camera writes,
no module changes. Bounded wait for the WPD device; every outcome is recorded.
"""
import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from tools.research.ptp_frame import evaluate_frame, parse_expect

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'Sony-PMCA-RE'))


def wpd_snapshot():
    """Raw WPD and PnP snapshot for diagnosing an empty listDevices."""
    result = {'raw_ids': [], 'ptp_children': [], 'uvc_children': []}
    try:
        from pmca.usb.driver.windows.wpd import _listDevices
        result['raw_ids'] = [getattr(device, 'handle', None) for device in _listDevices()]
    except Exception as exc:
        result['raw_error'] = repr(exc)
    try:
        from tools.research.uvc_ptp_windows_host import classify, query_devices
        binding = classify(query_devices())
        result['ptp_children'] = [d.get('InstanceId') for d in binding.get('ptp_children', [])]
        result['uvc_children'] = [d.get('InstanceId') for d in binding.get('uvc_children', [])]
    except Exception as exc:
        result['pnp_error'] = repr(exc)
    return result


def select_device_index(count, index):
    """Validate a WPD device selection; returns the index or raises ValueError."""
    if count < 1:
        raise ValueError('no WPD device')
    if not 0 <= index < count:
        raise ValueError(f'index {index} outside 0..{count - 1}')
    return index


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--timeout', type=float, default=240.0)
    parser.add_argument('--poll', type=float, default=2.0)
    parser.add_argument('--settle', type=float, default=1.5,
                        help='Seconds to wait after the SDIO handshake before polling')
    parser.add_argument('--retries', type=int, default=120,
                        help='GetObject polls after settle (client sleeps ~15 ms each)')
    parser.add_argument('--device-index', type=int, default=0,
                        help='WPD device index when multiple Sony devices are present')
    parser.add_argument('--list-devices', action='store_true',
                        help='List Sony WPD devices and exit')
    parser.add_argument('--expect', default='1024x680')
    parser.add_argument('--validate-only', type=Path)
    args = parser.parse_args()

    if args.list_devices:
        from pmca.usb.driver.windows.wpd import MtpContext
        devices = list(MtpContext().listDevices(0x054C))
        print(json.dumps([{'index': i, 'handle': d.handle} for i, d in enumerate(devices)], indent=2))
        return 0
    expected = parse_expect(args.expect)
    if args.validate_only:
        data = args.validate_only.read_bytes()
        result = evaluate_frame(data, expected)
        print(json.dumps(result, indent=2))
        return 0 if result['ok'] else 1
    if not args.output_dir:
        parser.error('--output-dir is required unless --validate-only is used')
    out = args.output_dir.resolve()
    if not out.is_relative_to(ROOT / 'artifacts'):
        parser.error('Output must be under artifacts')
    out.mkdir(parents=True, exist_ok=False)
    report = {'status': 'waiting', 'started_utc': datetime.now(timezone.utc).isoformat(),
              'timeout_sec': args.timeout, 'settle_sec': args.settle, 'retries': args.retries,
              'device_index': args.device_index,
              'expected': list(expected) if expected else None}

    def save():
        (out / 'manifest.json').write_text(json.dumps(report, indent=2) + '\n')

    save()
    client = None
    deadline = time.time() + args.timeout
    while time.time() < deadline:
        try:
            from tools.research.ptp_liveview_client import SonyWpdPTPLiveView
            client = SonyWpdPTPLiveView()
            client.connect(args.device_index)
            report['status'] = 'connected'
            report['device_index'] = getattr(client, 'device_index', args.device_index)
            report['device_count'] = getattr(client, 'device_count', None)
            report['device_handle'] = getattr(client, 'device_handle', None)
            report['connected_utc'] = datetime.now(timezone.utc).isoformat()
            save()
            break
        except Exception as exc:
            report['last_error'] = repr(exc)
            report['attempts'] = report.get('attempts', 0) + 1
            if report['attempts'] % 10 == 0:
                report.setdefault('wpd_snapshots', []).append(
                    {'attempt': report['attempts'],
                     'utc': datetime.now(timezone.utc).isoformat(),
                     **wpd_snapshot()})
            save()
            client = None
            time.sleep(args.poll)
    if client is None:
        report['status'] = 'no_wpd_device'
        report['stopped_utc'] = datetime.now(timezone.utc).isoformat()
        save()
        print(json.dumps(report, indent=2))
        return 2

    try:
        try:
            time.sleep(args.settle)
            frame = client.get_frame(retries=args.retries)
        except Exception as exc:
            report['status'] = 'ptp_error'
            report['error'] = repr(exc)
            report['stopped_utc'] = datetime.now(timezone.utc).isoformat()
            print(json.dumps(report, indent=2))
            return 3
        if not frame:
            report['status'] = 'no_frame'
            report['last_response'] = getattr(client, 'last_response', None)
            report['stopped_utc'] = datetime.now(timezone.utc).isoformat()
            print(json.dumps(report, indent=2))
            return 3

        width, height, size, jpeg = frame
        result = evaluate_frame(jpeg, expected)
        (out / 'liveview.jpg').write_bytes(jpeg)
        report.update({
            'status': 'captured' if result['ok'] else 'invalid_frame',
            'width': width, 'height': height, 'frame_bytes': size,
            'validation': result,
            'frame_saved': 'liveview.jpg',
            'stopped_utc': datetime.now(timezone.utc).isoformat(),
        })
        print(json.dumps(report, indent=2))
        return 0 if result['ok'] else 4
    finally:
        try:
            client.close()
        except Exception:
            pass
        report['closed_utc'] = datetime.now(timezone.utc).isoformat()
        save()


if __name__ == '__main__':
    raise SystemExit(main())
