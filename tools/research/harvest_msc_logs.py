"""Read-only MSC log harvest through the USB debugger.

Lists bounded directories, reads small/log files (including kikilog.dat), saves
them under artifacts and scans for USB/PTP/liveview keywords. No camera writes.
"""
import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from tools.camera_debugger import connect

ROOT = Path(__file__).resolve().parents[2]
LIST_DIRS = ['/', '/tmp', '/log', '/setting', '/system']
EXPLICIT = ['/log/feeder.log', '/tmp/autoexec.log', '/tmp/fb_diag.txt', '/tmp/kikilog.dat']
KEYWORDS = [b'liveview', b'LiveView', b'SDIO', b'stillimage', b'usbg_video', b'PTP',
            b'FFFFC002', b'Composite', b'UVC', b'PC Remote', b'descriptor', b'054c', b'0caa']


def parse_ls(payload):
    """Return (name, size) for regular files in ls -la output."""
    files = []
    for line in payload.decode('latin-1').splitlines():
        parts = line.split()
        if len(parts) < 9 or not line.startswith('-'):
            continue
        try:
            size = int(parts[4])
        except (ValueError, IndexError):
            continue
        files.append((parts[-1], size))
    return files


def scan_keywords(data):
    hits = []
    lowered = data
    for keyword in KEYWORDS:
        for match in re.finditer(re.escape(keyword), lowered, re.IGNORECASE):
            start = max(0, match.start() - 60)
            end = min(len(data), match.end() + 60)
            context = data[start:end].decode('latin-1', 'replace').replace('\x00', '.')
            hits.append({'keyword': keyword.decode('latin-1'), 'offset': match.start(), 'context': context})
    return hits


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', required=True, type=Path)
    parser.add_argument('--max-bytes', type=int, default=4 * 1024 * 1024)
    args = parser.parse_args()
    out = args.output_dir.resolve()
    if not out.is_relative_to(ROOT / 'artifacts'):
        parser.error('Output must be under artifacts')
    out.mkdir(parents=True, exist_ok=False)
    report = {'status': 'started', 'started_utc': datetime.now(timezone.utc).isoformat(),
              'directories': {}, 'files': {}, 'hits': {}}

    def save():
        (out / 'manifest.json').write_text(json.dumps(report, indent=2) + '\n')

    save()
    with connect() as dbg:
        uptime_before, _ = dbg.read_all('/proc/uptime', 4096)
        modules_before, _ = dbg.read_all('/proc/modules', 1 << 16)
        candidates = set(EXPLICIT)
        for directory in LIST_DIRS:
            try:
                payload = dbg.request(3, ('ls -la ' + directory).encode())['payload']
            except Exception as exc:
                report['directories'][directory] = {'error': repr(exc)}
                continue
            entries = parse_ls(payload)
            report['directories'][directory] = {'entries': [{'name': n, 'size': s} for n, s in entries[:200]]}
            for name, size in entries:
                if size > args.max_bytes:
                    continue
                if re.search(r'(kikilog|\.log$|log\.txt|\.txt$)', name, re.IGNORECASE):
                    if directory == '/tmp' or directory == '/log':
                        candidates.add(directory.rstrip('/') + '/' + name)
        save()
        hits_total = 0
        for path in sorted(candidates):
            try:
                data, truncated = dbg.read_all(path, args.max_bytes)
            except Exception as exc:
                report['files'][path] = {'error': repr(exc)}
                save()
                continue
            name = path.strip('/').replace('/', '_')
            (out / name).write_bytes(data)
            hits = scan_keywords(data)
            report['files'][path] = {'bytes': len(data), 'truncated': truncated,
                                     'sha256': hashlib.sha256(data).hexdigest(),
                                     'saved_as': name, 'hits': len(hits)}
            if hits:
                (out / (name + '.hits.jsonl')).write_text('\n'.join(json.dumps(h) for h in hits) + '\n')
                hits_total += len(hits)
            save()
        uptime_after, _ = dbg.read_all('/proc/uptime', 4096)
        modules_after, _ = dbg.read_all('/proc/modules', 1 << 16)
    report['camera_unchanged'] = {'uptime_monotonic': uptime_after >= uptime_before,
                                  'modules_equal': modules_after == modules_before}
    report['hits_total'] = hits_total
    report['status'] = 'completed'
    report['stopped_utc'] = datetime.now(timezone.utc).isoformat()
    save()
    print(json.dumps({'status': report['status'], 'files': list(report['files']),
                      'hits_total': hits_total, 'camera_unchanged': report['camera_unchanged']}, indent=2))


if __name__ == '__main__':
    main()
