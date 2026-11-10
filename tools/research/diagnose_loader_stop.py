"""Read-only loader/symbol stop diagnosis for a saved probe report.

This does not execute the guest; it only summarizes the report's stderr,
loader-stop section, library load/map events and thread states.
"""
import argparse
import json
from pathlib import Path

from src.a6400.execution.interpreter_probe import summarize_loader_stop

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def summarize(report):
    loader = report.get('loader_stop') or {}
    stdio = report.get('stdio') or {}
    stderr_text = stdio.get('stderr_preview') or report.get('stderr') or ''
    if not loader:
        loader = summarize_loader_stop(report.get('serviced_syscalls') or [], stderr_text,
                                       report.get('boundary'))
    lines = [
        f"status={report.get('status')} instructions={report.get('instructions_executed')}",
        f"stderr={stderr_text!r}",
        f"symbol_lookup_error={loader.get('symbol_lookup_error')}",
        f"undefined_symbol={loader.get('undefined_symbol')}",
    ]
    last_exit = loader.get('last_exit')
    if last_exit:
        lines.append(f"last_exit={last_exit.get('syscall')} status={last_exit.get('status')} "
                     f"tid={last_exit.get('tid')}")
    boundary_exit = loader.get('boundary_exit')
    if boundary_exit:
        lines.append(f"boundary_exit={boundary_exit.get('syscall')} status={boundary_exit.get('status')}")
    for path, events in (loader.get('libraries') or {}).items():
        lines.append(f'{path}: {len(events)} events')
        for event in events[-4:]:
            lines.append(f"  {event}")
    threads = report.get('threads') or {}
    for tid in sorted(threads, key=lambda value: int(value))[:12]:
        thread = threads[tid]
        lines.append(f"tid={tid} {thread.get('name')} {thread.get('state')} "
                     f"blocked={thread.get('blocked_uaddr')}")
    if report.get('boundary'):
        lines.append(f"boundary={json.dumps(report['boundary'], default=str)}")
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, required=True,
                        help='probe report JSON (read-only)')
    args = parser.parse_args(argv)
    path = args.report if args.report.is_absolute() else PROJECT_ROOT / args.report
    report = json.loads(path.read_text(encoding='utf-8'))
    print(summarize(report))


if __name__ == '__main__':
    main()
