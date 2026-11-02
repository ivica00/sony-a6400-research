"""Reuse retained successful REA evidence with exact identity and profile checks."""
import hashlib
import json
from pathlib import Path


def bounded_json(path, maximum=8 * 1024 * 1024):
    if path.stat().st_size > maximum:
        raise ValueError('Evidence JSON exceeds size bound')
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError('Evidence JSON must be an object')
    return value


class EvidenceCache:
    def __init__(self, root, provider_version='12.1.4'):
        self.root = Path(root).resolve()
        self.provider_version = provider_version
        self.entries = {}
        self.rejected = []
        if not self.root.exists():
            return
        folders = sorted(self.root.iterdir())
        if len(folders) > 1024:
            raise ValueError('Too many retained REA batches')
        for folder in folders:
            manifest = folder / 'manifest.json'
            if not folder.is_dir() or not manifest.is_file():
                continue
            if not folder.resolve().is_relative_to(self.root):
                continue
            try:
                record = bounded_json(manifest, 2 * 1024 * 1024)
                digest = record.get('sha256')
                if (record.get('status') != 'completed' or record.get('source_unchanged') is not True
                        or record.get('source_sha256_after') != digest):
                    continue
                if len(record.get('queries', [])) > 48:
                    raise ValueError('Retained batch exceeds query bound')
                for query in record.get('queries', []):
                    path = (folder / query['file']).resolve()
                    if not path.is_relative_to(folder.resolve()) or not path.is_relative_to(self.root):
                        raise ValueError('REA query reference escapes batch')
                    data = bounded_json(path)
                    evidence = data.get('structuredContent', {})
                    profile = evidence.get('analysis_profile', {}).get('digest')
                    if (data.get('isError') or not profile
                            or evidence.get('subject', {}).get('digest', {}).get('sha256') != digest
                            or evidence.get('provider', {}).get('id') != 'ghidra'
                            or evidence.get('provider', {}).get('version') != provider_version
                            or evidence.get('operation') != query['operation']
                            or evidence.get('parameters', {}).get('procedure') != query['procedure']):
                        continue
                    key = (digest, query['operation'], query['procedure'])
                    self.entries.setdefault(key, []).append({'path': path, 'profile': profile,
                        'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
            except (OSError, ValueError, KeyError, TypeError) as error:
                self.rejected.append({'batch': str(folder), 'reason': str(error)[:300]})

    def lookup(self, digest, operation, procedure):
        candidates = self.entries.get((digest, operation, procedure), [])
        # Different analysis profiles must never be silently interchanged.
        if len({item['profile'] for item in candidates}) != 1:
            return None
        for item in candidates:
            path = item['path']
            try:
                data = bounded_json(path)
                if hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
                    continue
            except (OSError, ValueError):
                continue
            return {'data': data, 'source': str(path), 'sha256': item['sha256'],
                    'analysis_profile': item['profile']}
        return None
