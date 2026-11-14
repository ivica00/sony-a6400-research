"""Start the original ARM interpreter with a declared syscall policy."""
import argparse
import json
from pathlib import Path
from unicorn import UcError

from project_paths import PROJECT_ROOT
from src.a6400.images.process_elf import inspect_image
from src.a6400.execution.interpreter_probe import InterpreterProbe
from tools.research.guest_layout import resolve_guest
from tools.research.inventory import digest
from src.a6400.execution.guest_uname import extract_kernel_uts
from src.a6400.images.verified_content import VerifiedContent
from src.a6400.images.ext2_metadata import Ext2Metadata
from tools.research.mount_evidence import checked_input, inspect_init, unsupplied_mount_roots
from src.a6400.execution.guest_filesystem import UNKNOWN_ROOTS
from src.a6400.execution.guest_kuser import extract_kuser_template
from src.a6400.targets import get_profile


def load_guest_image(manifest, inventory, guest_path):
    resolution = resolve_guest(manifest['nodes'], guest_path)
    if resolution['status'] != 'resolved':
        raise ValueError(f'Guest path not resolved: {resolution}')
    node = manifest['nodes'][resolution['path']]
    if node['kind'] != 'file':
        raise ValueError('Guest image must be a regular file')
    local = (PROJECT_ROOT / node['extracted_path']).resolve()
    firmware_root = (PROJECT_ROOT / 'firmware').resolve()
    if not local.is_relative_to(firmware_root):
        raise ValueError('Guest image path escapes local firmware directory')
    expected = next(e['sha256'] for e in inventory if e['path'] == node['extracted_path'])
    return inspect_image(local, expected)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--entry', default='/usr/bin/im.elf')
    parser.add_argument('--argument', action='append', default=[])
    parser.add_argument('--instructions', type=int, default=100000)
    parser.add_argument('--timeout-us', type=int, default=2000000)
    parser.add_argument('--syscalls', choices=('stop', 'brk', 'brk-uname', 'files', 'metadata', 'mmap', 'kuser', 'uipc', 'threads'), default='stop',
                        help='explicit guest contracts; uname reads of runtime-unknown fields remain guarded')
    parser.add_argument('--report', type=Path)
    parser.add_argument('--respect-runtime-mounts', action='store_true',
                        help='stop at original init mount targets whose runtime contents are unsupplied')
    parser.add_argument('--target', default='ilce_6400',
                        help='registered CXD90045 target_id from src/a6400/targets/')
    args = parser.parse_args()
    target_profile = get_profile(args.target)
    if args.report is None:
        name = {'stop': 'interpreter-probe.json', 'brk': 'interpreter-brk.json',
                'brk-uname': 'interpreter-uname.json', 'files': 'interpreter-files.json',
                'metadata': 'interpreter-metadata.json', 'mmap': 'interpreter-mmap.json',
                'kuser': 'interpreter-kuser.json', 'uipc': 'interpreter-uipc.json',
                'threads': 'interpreter-threads.json'}[args.syscalls]
        args.report = PROJECT_ROOT / 'artifacts/execution' / name
        if args.respect_runtime_mounts:
            args.report = args.report.with_stem(args.report.stem + '-mount-aware')
    if args.syscalls in ('uipc', 'threads') and args.instructions == 100000:
        args.instructions = 10000000
        args.timeout_us = 30000000
    elif args.syscalls == 'kuser' and args.instructions == 100000:
        args.instructions = 3000000
        args.timeout_us = 15000000
    report = {'status': 'configuration_error', 'camera_fidelity_validated': False}
    try:
        if args.respect_runtime_mounts and args.syscalls not in ('files', 'metadata', 'mmap', 'kuser', 'uipc', 'threads'):
            raise ValueError('Runtime mount checks require files, metadata, mmap, kuser, uipc, or threads policy')
        folder = PROJECT_ROOT / 'artifacts/inventory'
        manifest = json.loads((folder / 'guest-filesystem.json').read_text(encoding='utf-8'))
        inventory = json.loads((folder / 'elf-inventory.json').read_text(encoding='utf-8'))['entries']
        for image in manifest['images']:
            path = (PROJECT_ROOT / image['path']).resolve()
            if not path.is_relative_to((PROJECT_ROOT / 'firmware').resolve()) or digest(path) != image['sha256']:
                raise ValueError('Original filesystem image path/hash mismatch')
        application = load_guest_image(manifest, inventory, args.entry)
        if not application['interpreter']:
            raise ValueError('Application has no PT_INTERP')
        interpreter = load_guest_image(manifest, inventory, application['interpreter'])
        uname_profile = None
        kuser_template = None
        if args.syscalls in ('brk-uname', 'files', 'metadata', 'mmap', 'kuser', 'uipc', 'threads'):
            kernel = 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked/vmlinux.bin'
            baseline = json.loads((folder / 'baseline.json').read_text(encoding='utf-8'))
            expected = next(e['sha256'] for e in baseline['inputs'] if e['path'] == kernel)
            uname_profile = extract_kernel_uts(PROJECT_ROOT / kernel, expected)
            uname_profile['source_path'] = kernel
            if args.syscalls in ('kuser', 'uipc', 'threads'):
                kuser_template = extract_kuser_template(PROJECT_ROOT / kernel, expected)
        filesystem = None
        if args.syscalls in ('files', 'metadata', 'mmap', 'kuser', 'uipc', 'threads'):
            expected_inputs = {item['path']: item['sha256'] for item in baseline['inputs']}

            content_loader = VerifiedContent(PROJECT_ROOT, PROJECT_ROOT / 'firmware', expected_inputs)
            filesystem = {'nodes': manifest['nodes'], 'content_loader': content_loader}
            mount_profile = None
            if args.respect_runtime_mounts:
                init_path = 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha7_unpacked/sbin/init'
                init = checked_input(PROJECT_ROOT, init_path, expected_inputs[init_path])
                roots = unsupplied_mount_roots(inspect_init(init)['mounts'])
                # Preserve the default unknown roots as well as discovered ones.
                filesystem['unknown_roots'] = tuple(sorted(set(UNKNOWN_ROOTS).union(roots)))
                mount_profile = {'source_path': init_path, 'source_sha256': expected_inputs[init_path],
                                 'unsupplied_mount_candidates': roots,
                                 'method': 'conservative static mount targets; success/boot mode not established'}
            if args.syscalls in ('metadata', 'mmap', 'kuser', 'uipc', 'threads'):
                boot_mount_data = None
                if args.syscalls in ('mmap', 'kuser', 'uipc', 'threads'):
                    boot_mount_data = json.loads((folder / 'boot-mount-trace.json').read_text(encoding='utf-8'))
                    major = boot_mount_data['devnodes_summary']['nflasha']['major']
                for image in manifest['images']:
                    source = Ext2Metadata(PROJECT_ROOT / image['path'], image['sha256'])
                    indexed = source.index()
                    for node in filesystem['nodes'].values():
                        if node.get('image') != Path(image['path']).name:
                            continue
                        metadata = indexed[node['archive_path'] or '/']
                        if any(metadata[key] != node[key] for key in ('mode', 'uid', 'gid')):
                            raise ValueError('ext2 namespace metadata mismatch')
                        if node['kind'] == 'file' and metadata['size'] != node['size']:
                            raise ValueError('ext2 namespace file size mismatch')
                        node_stat = {**metadata, 'image_sha256': image['sha256']}
                        if args.syscalls in ('mmap', 'kuser', 'uipc', 'threads'):
                            # Evidence Record 0014: major 252, nflasha7=0xfc07, nflasha15=0xfc0f
                            part_num = 7 if 'nflasha7' in image['path'] else 15
                            dev = (major << 8) | part_num
                            node_stat['st_dev'] = dev
                        node['stat_metadata'] = node_stat
        probe = InterpreterProbe(syscall_policy=args.syscalls, uname_profile=uname_profile,
                                 filesystem=filesystem, kuser_template=kuser_template,
                                 target_profile=target_profile)
        probe.prepare(application, interpreter, [args.entry, *args.argument])
        report = probe.run(args.instructions, args.timeout_us)
        if args.respect_runtime_mounts:
            report['runtime_mount_profile'] = mount_profile
        report['guest_paths'] = {'application': args.entry, 'interpreter': application['interpreter']}
        report['filesystem_sources'] = manifest['images']
        print(f"Stopped: {report['status']}; original-code instructions: {report['instructions_executed']}")
        if 'boundary' in report:
            print(json.dumps(report['boundary'], indent=2))
        return 0 if report['status'] in ('syscall_boundary', 'memory_boundary') else 2
    except (ValueError, KeyError, StopIteration, OSError, UcError) as error:
        report['error'] = str(error)
        print(f'Probe configuration failed: {error}')
        return 2
    finally:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(f'Report: {args.report}')


if __name__ == '__main__':
    raise SystemExit(main())
