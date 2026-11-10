"""Read-only high-frequency Windows USB/PnP capture around the liveview transition.

Polls the existing PnP classification and records every state change, so a fast
disconnect/re-enumeration is visible. No camera access, no writes to the device.
"""
import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from tools.research.uvc_ptp_windows_host import classify, query_devices

ROOT = Path(__file__).resolve().parents[2]


def summarize(binding):
    return {
        'parents': len(binding.get('parents') or []),
        'ptp_children': len(binding.get('ptp_children') or []),
        'uvc_children': len(binding.get('uvc_children') or []),
        'composite_parent_ready': bool(binding.get('composite_parent_ready')),
        'ptp_ready': bool(binding.get('ptp_ready')),
        'uvc_ready': bool(binding.get('uvc_ready')),
    }


def detect_transitions(samples):
    """Return the samples where the summarized binding state changes."""
    transitions = []
    previous = None
    for index, sample in enumerate(samples):
        current = sample.get('summary')
        if current != previous:
            transitions.append({'index': index, 'utc': sample.get('utc'), 'summary': current})
            previous = current
    return transitions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--duration', type=float, default=120.0)
    parser.add_argument('--interval', type=float, default=0.2)
    parser.add_argument('--output-dir', required=True, type=Path)
    args = parser.parse_args()
    out = args.output_dir.resolve()
    if not out.is_relative_to(ROOT / 'artifacts'):
        parser.error('Output must be under artifacts')
    if args.interval < 0.05:
        parser.error('Interval must be >= 0.05 s')
    out.mkdir(parents=True, exist_ok=False)
    samples = []
    started = time.time()
    while time.time() - started < args.duration:
        binding = classify(query_devices())
        sample = {'utc': datetime.now(timezone.utc).isoformat(),
                  'elapsed': round(time.time() - started, 3),
                  'summary': summarize(binding)}
        samples.append(sample)
        (out / 'samples.jsonl').write_text(''.join(json.dumps(s) + '\n' for s in samples))
        time.sleep(args.interval)
    manifest = {'status': 'completed', 'duration_sec': args.duration,
                'interval_sec': args.interval, 'samples': len(samples),
                'transitions': detect_transitions(samples)}
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest['transitions'], indent=2))


if __name__ == '__main__':
    main()
