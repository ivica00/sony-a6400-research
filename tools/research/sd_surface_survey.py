"""Read-only SD metadata/header survey and hash-checked firmware string leads.

No image decoding, updater execution, card writes, or payload generation.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import stat

from project_paths import PROJECT_ROOT
from tools.research.rea_wsl_batch import checked_input

MARKERS = {
    'card_layout': re.compile(rb'(?i)DCIM|AVF_INFO|AVIN0001|M4ROOT|MSDCF|AVCHD'),
    'image_parser': re.compile(rb'(?i)Exif|MakerNote|TIFF|JPEG|\.ARW\b'),
    'card_update': re.compile(rb'(?i)\bSD\b[^\x00\r\n]{0,24}updat|updat[^\x00\r\n]{0,24}(?:SD.card|memory.card)|BODYDATA|firmware\.dat|update\.dat|\.upd\b'),
    'updater_source': re.compile(rb'IAMLDUDWRT|MSBOOT|DATSRC_|MS_MOUNT_POINT|SENSER'),
    'update_validation': re.compile(rb'(?i)signature|verify|authenticate|RSA|SHA256|checksum'),
}
STRINGS = re.compile(rb'[\x20-\x7e]{5,240}')
MEDIA = {'.ARW', '.JPG', '.JPEG', '.MP4', '.MTS'}


def card_inventory(root):
    root = root.resolve(strict=True)
    records, skipped = [], []
    # Deliberately exclude Windows system folders and never follow reparse points.
    def visit(directory):
        for path in sorted(directory.iterdir()):
            info = path.lstat()
            relative = path.relative_to(root).as_posix()
            if getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT or path.is_symlink():
                skipped.append({'path': relative, 'reason': 'reparse point'})
                continue
            if path.is_dir():
                if directory == root and path.name not in ('DCIM', 'PRIVATE', 'AVF_INFO'):
                    skipped.append({'path': relative, 'reason': 'outside declared camera trees'})
                else:
                    visit(path)
            elif path.is_file():
                before = (info.st_size, info.st_mtime_ns)
                with path.open('rb') as stream:
                    prefix = stream.read(64)
                    # Full identity for small metadata only; never copy personal media.
                    if path.suffix.upper() not in MEDIA and info.st_size <= 8 * 1024 * 1024:
                        stream.seek(0)
                        full_hash = hashlib.file_digest(stream, 'sha256').hexdigest()
                    else:
                        full_hash = None
                after = path.stat()
                if before != (after.st_size, after.st_mtime_ns):
                    raise ValueError('Card file changed during read-only survey')
                records.append({'path': relative, 'bytes': info.st_size, 'extension': path.suffix.upper(),
                                'prefix64_hex': prefix.hex(), 'prefix64_sha256': hashlib.sha256(prefix).hexdigest(),
                                'sha256': full_hash})
    visit(root)
    return {'files': records, 'skipped': skipped,
            'extensions': dict(sorted(Counter(r['extension'] for r in records).items())),
            'limitations': ['Mounted filesystem view, not raw card/partition acquisition.',
                            'Prefix hashes do not identify complete media files; personal media not decoded or copied.',
                            'No claim about deleted files, filesystem integrity or camera acceptance.']}


def firmware_leads():
    baseline = json.loads((PROJECT_ROOT / 'artifacts/inventory/baseline.json').read_text())['inputs']
    results = []
    for item in baseline:
        path = item['path']
        # Installed software plus updater software; not whole partition/package containers.
        if '_unpacked/' not in path or Path(path).suffix.lower() not in ('.so', '.elf', '.sh', '.src'):
            continue
        raw = checked_input(PROJECT_ROOT, path, item['sha256'])
        hits, counts, retained = [], Counter(), Counter()
        matched_strings = 0
        for match in STRINGS.finditer(raw):
            value = match.group()
            groups = [name for name, pattern in MARKERS.items() if pattern.search(value)]
            if groups:
                counts.update(groups)
                matched_strings += 1
                if any(retained[group] < 40 for group in groups):
                    hits.append({'offset': match.start(), 'groups': groups, 'text': value.decode('ascii')})
                    retained.update(groups)
        checked_input(PROJECT_ROOT, path, item['sha256'])
        results.append({'path': path, 'sha256': item['sha256'], 'bytes': len(raw),
                        'counts': dict(counts), 'hits': hits, 'hits_truncated': matched_strings > len(hits)})
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--card', type=Path, required=True)
    parser.add_argument('--report-dir', required=True)
    args = parser.parse_args()
    output = (PROJECT_ROOT / args.report_dir).resolve()
    if not output.is_relative_to(PROJECT_ROOT / 'artifacts'):
        parser.error('Reports must remain under artifacts')
    if output.is_relative_to(args.card.resolve()):
        parser.error('Reports must not be written on the source card')
    output.mkdir(parents=True, exist_ok=False)
    card = card_inventory(args.card)
    (output / 'card-inventory.json').write_text(json.dumps(card, indent=2))
    firmware = firmware_leads()
    (output / 'firmware-leads.json').write_text(json.dumps(firmware, indent=2))
    summary = {'card_extensions': card['extensions'], 'card_files': len(card['files']),
               'firmware_inputs_scanned': len(firmware),
               'limitations': ['String matches are research leads, not call graphs, vulnerabilities or supported update paths.']}
    (output / 'summary.json').write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
