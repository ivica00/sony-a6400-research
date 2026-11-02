"""Compact, bounded summary of a probe JSON report (never prints raw event lists)."""
import argparse
import json
from collections import Counter
from pathlib import Path

from project_paths import PROJECT_ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report', nargs='?', type=Path,
                        default=PROJECT_ROOT / 'artifacts/execution/interpreter-ui-boot-test.json')
    parser.add_argument('--tail', type=int, default=5, help='number of last serviced events to show (max 20)')
    args = parser.parse_args()
    data = json.loads(args.report.read_text(encoding='utf-8'))
    events = data.get('serviced_syscalls', [])
    regs = data.get('registers', {})
    print('status:', data.get('status'), '| instructions:', data.get('instructions_executed'))
    print('engine_error:', data.get('engine_error'))
    print('tid:', data.get('tls_observation', {}).get('current_tid'),
          '| pc:', hex(regs.get('pc', 0)), '| lr:', hex(regs.get('lr', 0)))
    print('events:', len(events), '| by type:', dict(Counter(
        e.get('syscall') or e.get('signal') for e in events).most_common(8)))
    signals = [e for e in events if 'signal' in e]
    print('signals delivered:', len(signals), [(hex(e['fault_pc']), hex(e['handler'])) for e in signals[:5]])
    fb = data.get('framebuffer', {})
    print('framebuffer transactions:', len(fb.get('transactions', [])), '| vram_base:', fb.get('vram_base'))
    print('boundary:', json.dumps(data.get('boundary'))[:300])
    for e in events[-min(args.tail, 20):]:
        text = {k: v for k, v in e.items() if k in ('syscall', 'signal', 'path', 'returned', 'reason', 'fault_pc')}
        print('  ', json.dumps(text)[:200])


if __name__ == '__main__':
    main()
