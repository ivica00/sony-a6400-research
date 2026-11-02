"""Inspect original filesystem metadata and plan guest paths without extracting links."""
import json
import posixpath
import stat
import sys
from pathlib import Path

from project_paths import PROJECT_ROOT
from tools.research.inventory import digest


from src.a6400.images.guest_paths import canonical, resolve_guest


def filesystem_manifest():
    sys.path.insert(0, str(PROJECT_ROOT / 'fwtool.py'))
    from fwtool.archive import readArchive
    base = PROJECT_ROOT / 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev'
    nodes, images = {}, []
    for name, mount in [('nflasha7', '/'), ('nflasha15', '/usr')]:
        image = base / name
        images.append({'path': image.relative_to(PROJECT_ROOT).as_posix(),
                       'sha256': digest(image), 'planned_mount': mount})
        with image.open('rb') as stream:
            for entry in readArchive(stream):
                path = canonical(posixpath.join(mount, entry.path.lstrip('/')))
                kind = ('directory' if stat.S_ISDIR(entry.mode) else 'symlink' if stat.S_ISLNK(entry.mode)
                        else 'file' if stat.S_ISREG(entry.mode) else 'special')
                node = {'kind': kind, 'mode': entry.mode, 'uid': entry.uid, 'gid': entry.gid,
                        'size': entry.size, 'image': name, 'archive_path': entry.path}
                if kind == 'symlink':
                    node['target'] = entry.contents.read().decode('utf-8', errors='strict')
                if kind == 'file':
                    local = base / (name + '_unpacked') / entry.path.lstrip('/')
                    node['extracted_path'] = local.relative_to(PROJECT_ROOT).as_posix()
                    node['extracted_file_present'] = local.is_file()
                nodes[path] = node
    return {'images': images, 'nodes': nodes,
            'assumptions': ['nflasha7 is modeled as guest / after pivot; verify actual boot mode.',
                            'nflasha15 is modeled as /usr based on mount.conf.',
                            'No writable partitions, devices, procfs, or runtime state have been supplied.']}


def process_plan(manifest, elf_entries, entry='/usr/bin/im.elf', search_paths=('/lib', '/usr/lib')):
    nodes = manifest['nodes']
    by_local = {e['path']: e for e in elf_entries}
    queue, visited, objects, missing = [entry], set(), [], []
    while queue:
        requested = queue.pop(0)
        resolved = resolve_guest(nodes, requested)
        if resolved['status'] != 'resolved':
            missing.append({'requested': requested, **resolved})
            continue
        path = resolved['path']
        if path in visited:
            continue
        visited.add(path)
        record = by_local.get(nodes[path].get('extracted_path'))
        if record is None:
            missing.append({'requested': requested, 'path': path, 'status': 'not_in_elf_inventory'})
            continue
        dependencies = []
        if record['interpreter']:
            queue.append(record['interpreter'])
        for needed in record['needed']:
            candidates = []
            paths = [needed] if '/' in needed else [posixpath.join(directory, needed) for directory in search_paths]
            for candidate in paths:
                result = resolve_guest(nodes, candidate)
                if result['status'] == 'resolved':
                    candidates.append({'requested': candidate, **result})
            dependencies.append({'needed': needed, 'candidates': candidates})
            if candidates:
                # Inventory all candidates; do not silently choose a loader search order.
                queue.extend(c['requested'] for c in candidates)
            else:
                missing.append({'requester': path, 'needed': needed, 'status': 'no_candidate_in_declared_paths'})
        objects.append({'path': path, 'local_path': record['path'], 'sha256': record['sha256'],
                        'tls': record['tls'], 'relocations': record['relocations'],
                        'initializers': record['initializers'], 'interpreter': record['interpreter'],
                        'dependencies': dependencies})
    return {'entry': entry, 'status': 'static_candidate_plan_only', 'search_paths': list(search_paths),
            'objects': objects, 'missing': missing,
            'limitations': ['The listed search paths are explicit research assumptions, not recovered loader policy.',
                            'Only DT_NEEDED closure is included; dlopen modules, symbol versions, init order, and device behavior remain unvalidated.',
                            'All candidates are retained where ambiguous; no executable environment was created.']}


def main():
    output = PROJECT_ROOT / 'artifacts/inventory'
    elf_entries = json.loads((output / 'elf-inventory.json').read_text(encoding='utf-8'))['entries']
    manifest = filesystem_manifest()
    plan = process_plan(manifest, elf_entries)
    (output / 'guest-filesystem.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    (output / 'im-process-plan.json').write_text(json.dumps(plan, indent=2), encoding='utf-8')
    links = sum(n['kind'] == 'symlink' for n in manifest['nodes'].values())
    print(f'Recovered {len(manifest["nodes"])} guest paths, {links} symlinks; '
          f'{len(plan["objects"])} candidate process objects, {len(plan["missing"])} missing references.')
    print(f'Reports: {output}')


if __name__ == '__main__':
    main()
