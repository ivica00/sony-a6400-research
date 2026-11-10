"""Continuously sample Windows PnP USB state and tail setupapi.dev.log.

Read-only host monitoring for a camera connection. No USB control transfers,
no driver changes, no camera commands.
"""
import argparse
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SETUPAPI = Path(r'C:\Windows\INF\setupapi.dev.log')
KEYWORDS = ('054C', 'VID_0000', 'descriptor', 'Sony', 'ILCE', 'usbvideo', 'WUDF',
            'MTP', 'usbccgp', 'USB\\VID')

PS = r'''
$items = @(Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue | Where-Object { $_.InstanceId -like 'USB*' } |
  ForEach-Object { [pscustomobject]@{ Status=$_.Status; Class=$_.Class; FriendlyName=$_.FriendlyName;
    InstanceId=$_.InstanceId; Problem=$_.Problem } })
ConvertTo-Json -Compress -InputObject $items
'''


def now():
    return datetime.now(timezone.utc).isoformat()


def snapshot():
    try:
        result = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', PS],
                                capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {'error': repr(exc)}
    if result.returncode != 0:
        return {'error': 'powershell rc=%d %s' % (result.returncode, result.stderr[:200])}
    text = result.stdout.strip()
    if not text:
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return {'error': 'json: ' + repr(exc)}
    return data if isinstance(data, list) else [data]


def classify(devices):
    if isinstance(devices, dict):
        return {'sony': [], 'problem': [], 'error': devices.get('error')}
    sony = [d for d in devices if 'VID_054C' in str(d.get('InstanceId', ''))]
    problem = [d for d in devices if d.get('Status') != 'OK' or d.get('Problem') not in (None, 0)]
    return {'sony': sony, 'problem': problem}


def setupapi_sample(state):
    """Read only new bytes of setupapi.dev.log and return matching lines."""
    try:
        size = SETUPAPI.stat().st_size
        if state['offset'] is None or size < state['offset']:
            state['offset'] = size
            return []
        if size == state['offset']:
            return []
        with SETUPAPI.open('rb') as handle:
            handle.seek(state['offset'])
            raw = handle.read(size - state['offset'])
            state['offset'] = handle.tell()
        text = raw.decode('utf-8', 'replace')
        return [line for line in text.splitlines() if any(k in line for k in KEYWORDS)]
    except OSError as exc:
        return ['setupapi-read-error: ' + repr(exc)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', required=True, type=Path)
    parser.add_argument('--interval', type=float, default=1.0)
    parser.add_argument('--duration', type=float, default=180.0)
    args = parser.parse_args()
    out = args.output_dir.resolve()
    if not out.is_relative_to(ROOT / 'artifacts'):
        parser.error('Output must be under artifacts')
    out.mkdir(parents=True, exist_ok=False)
    state = {'offset': None}
    initial = setupapi_sample(state)
    start = time.time()
    report = {'status': 'monitoring', 'started_utc': now(), 'interval_sec': args.interval,
              'duration_sec': args.duration, 'setupapi': str(SETUPAPI),
              'initial_setupapi_lines': initial}
    (out / 'manifest.json').write_text(json.dumps(report, indent=2) + '\n')
    samples = (out / 'samples.jsonl').open('a', encoding='utf-8')
    delta = (out / 'setupapi-delta.log').open('a', encoding='utf-8')
    seen = None
    try:
        while time.time() - start < args.duration:
            devices = snapshot()
            parts = classify(devices)
            lines = setupapi_sample(state)
            for line in lines:
                delta.write(line + '\n')
            sample = {'t': now(), 'elapsed': round(time.time() - start, 2),
                      'device_count': len(devices) if isinstance(devices, list) else 0,
                      'sony': parts['sony'], 'problem': parts['problem'],
                      'setupapi_lines': lines}
            if 'error' in parts:
                sample['error'] = parts['error']
            samples.write(json.dumps(sample) + '\n')
            samples.flush()
            delta.flush()
            key = tuple(sorted(str(d.get('InstanceId')) for d in parts['sony']))
            if seen is None:
                seen = key
            elif key != seen:
                report.setdefault('transitions', []).append({'elapsed': sample['elapsed'], 'sony': list(key)})
                (out / 'manifest.json').write_text(json.dumps(report, indent=2) + '\n')
                seen = key
            time.sleep(args.interval)
    except KeyboardInterrupt:
        report['stopped'] = 'keyboard'
    finally:
        samples.close()
        delta.close()
        report['status'] = 'completed'
        report['stopped_utc'] = now()
        (out / 'manifest.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
