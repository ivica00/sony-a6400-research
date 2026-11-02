"""Independently bind retained backup REA queries to preserved ELF identities."""
import hashlib
import json

from project_paths import PROJECT_ROOT
from tools.research.mount_evidence import checked_input


def main():
    inventory = json.loads((PROJECT_ROOT / 'artifacts/inventory/elf-inventory.json').read_text(encoding='utf-8'))
    expected = {row['path']: row['sha256'] for row in inventory['entries']}
    reports = []
    for name in ('backup-state-batch', 'backup-client-batch', 'backup-client-exact-batch',
                 'im-backup-write-batch', 'backup-load-batch', 'backup-queue-verified-batch'):
        folder = PROJECT_ROOT / 'artifacts/tools/rea' / name
        manifest = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
        digest = expected[manifest['target']]
        checked_input(PROJECT_ROOT, manifest['target'], digest)
        if manifest['sha256'] != digest or manifest['source_sha256_after'] != digest:
            raise ValueError('REA batch identity differs from the preserved input')
        records = []
        for query in manifest['queries']:
            path = (folder / query['file']).resolve()
            path.relative_to(folder.resolve())
            raw = path.read_bytes()
            result = json.loads(raw)['structuredContent']
            if result['subject']['digest']['sha256'] != digest:
                raise ValueError('Retained REA query has a different target identity')
            records.append({'query': query, 'evidence_id': result['evidence_id'],
                            'report_sha256': hashlib.sha256(raw).hexdigest()})
        reports.append({'batch': name, 'status': manifest['status'], 'target': manifest['target'],
                        'sha256': digest, 'elapsed_seconds': manifest['elapsed_seconds'], 'queries': records})
    output = PROJECT_ROOT / 'artifacts/execution/package-h-rea-backup-audit.json'
    output.write_text(json.dumps(reports, indent=2), encoding='utf-8')
    print(output)
    print('Verified', sum(len(r['queries']) for r in reports), 'retained query identities;',
          sum(r['status'] == 'failed' for r in reports), 'explicitly failed batch.')


if __name__ == '__main__':
    main()
