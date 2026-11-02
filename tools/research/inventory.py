"""Read-only local input and environment inventory. Does not contact a camera."""
import hashlib
import importlib.metadata
import json
import platform
import subprocess
from pathlib import Path

from project_paths import PROJECT_ROOT


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def main():
    files = []
    for directory in ('firmware', 'backups'):
        for path in sorted((PROJECT_ROOT / directory).rglob('*')):
            if path.is_file():
                files.append({'path': path.relative_to(PROJECT_ROOT).as_posix(),
                              'bytes': path.stat().st_size, 'sha256': digest(path)})
    upstream = []
    for name in ('fwtool.py', 'Sony-PMCA-RE'):
        directory = PROJECT_ROOT / name
        # Do not mistake an enclosing repository's revision for the upstream revision.
        revision = None
        if (directory / '.git').exists():
            result = subprocess.run(['git', '-C', str(directory), 'rev-parse', 'HEAD'],
                                    capture_output=True, text=True)
            revision = result.stdout.strip() if result.returncode == 0 else None
        licenses = [{'path': p.relative_to(PROJECT_ROOT).as_posix(), 'sha256': digest(p)}
                    for p in directory.glob('*') if p.is_file() and p.name.lower().startswith('license')]
        upstream.append({'path': name, 'revision': revision,
                         'provenance': 'local checkout; origin and modifications not verified',
                         'licenses': licenses})
    packages = sorted([{'name': d.metadata['Name'], 'version': d.version}
                       for d in importlib.metadata.distributions()], key=lambda d: d['name'].lower())
    native = []
    for package in ('unicorn', 'capstone', 'libusb', 'libusb_package', 'PIL'):
        directory = PROJECT_ROOT / 'venv' / 'Lib' / 'site-packages' / package
        if directory.exists():
            for path in sorted(directory.rglob('*')):
                if path.is_file() and path.suffix.lower() in ('.dll', '.pyd', '.so'):
                    native.append({'path': path.relative_to(PROJECT_ROOT).as_posix(), 'sha256': digest(path)})
    output = PROJECT_ROOT / 'artifacts' / 'inventory'
    output.mkdir(parents=True, exist_ok=True)
    report = {'schema_version': 1, 'python': platform.python_version(), 'platform': platform.platform(),
              'inputs': files, 'upstream': upstream, 'packages': packages, 'native_libraries': native,
              'limitations': ['Hashes identify local content, not authenticity or completeness.',
                              'Package snapshot is not a tested fresh-install dependency lock.',
                              'Upstream working-tree modifications are not characterized.']}
    (output / 'baseline.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(f'Inventoried {len(files)} input files, {len(native)} native libraries, {len(packages)} packages: {output / "baseline.json"}')


if __name__ == '__main__':
    main()
