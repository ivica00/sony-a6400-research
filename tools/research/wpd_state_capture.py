"""Read-only WPD/PnP state capture beside a PTP probe session.

Polls the raw WPD device list (unfiltered) and the PnP PTP/UVC children so the
state during a liveview re-enumeration can be compared. No camera access.
"""
import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from tools.research.run_ptp_liveview_probe import wpd_snapshot

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--duration', type=float, default=240.0)
    parser.add_argument('--interval', type=float, default=1.0)
    parser.add_argument('--output-dir', required=True, type=Path)
    args = parser.parse_args()
    out = args.output_dir.resolve()
    if not out.is_relative_to(ROOT / 'artifacts'):
        parser.error('Output must be under artifacts')
    if args.interval < 0.2:
        parser.error('Interval must be >= 0.2 s')
    out.mkdir(parents=True, exist_ok=False)
    samples = []
    started = time.time()
    while time.time() - started < args.duration:
        sample = {'utc': datetime.now(timezone.utc).isoformat(),
                  'elapsed': round(time.time() - started, 3),
                  **wpd_snapshot()}
        samples.append(sample)
        (out / 'samples.jsonl').write_text(''.join(json.dumps(s) + '\n' for s in samples))
        time.sleep(args.interval)
    manifest = {'status': 'completed', 'samples': len(samples),
                'window_with_children': sum(1 for s in samples if s.get('ptp_children')),
                'window_with_raw_wpd': sum(1 for s in samples if s.get('raw_ids'))}
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
