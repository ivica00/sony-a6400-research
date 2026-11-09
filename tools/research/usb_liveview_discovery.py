"""Read-only USB/live-view discovery. Never invokes camera application functions.

Retains bounded procfs/sysfs observations and hash-verified local ELF candidates.
No device-node reads, camera uploads, mode changes, ptrace or ioctl calls.
"""
import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from tools.camera_debugger import connect

ROOT = Path(__file__).resolve().parents[2]
PATTERN = re.compile(r'UsbLiveView|LiveViewTransfer|mjpeg|mjpg|uvc|Sfr.*Jpeg|LiveViewJpeg|LiveViewStatus', re.I)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report-dir', type=Path, required=True)
    args = parser.parse_args()
    out = args.report_dir.resolve()
    if not out.is_relative_to(ROOT / 'artifacts'):
        parser.error('Report must be under artifacts')
    out.mkdir(parents=True, exist_ok=False)
    report = {'utc': datetime.now(timezone.utc).isoformat(), 'camera_mutations': False,
              'ptrace': False, 'mode_switches': False, 'observations': {}, 'local_candidates': []}

    def retain(name, data, **metadata):
        (out / name).write_bytes(data)
        report['observations'][name] = {'bytes': len(data),
            'sha256': hashlib.sha256(data).hexdigest(), **metadata}
        (out / 'manifest.json').write_text(json.dumps(report, indent=2), encoding='utf-8')

    with connect() as dbg:
        retain('debug-info.txt', dbg.request(1)['payload'])
        for path in ['/proc/version', '/proc/modules', '/proc/devices', '/proc/mounts',
                     '/proc/149/maps', '/proc/149/status', '/proc/net/tcp']:
            name = path.strip('/').replace('/', '_') + '.txt'
            try:
                data, truncated = dbg.read_all(path, limit=256*1024)
                retain(name, data, path=path, truncated=truncated)
            except Exception as exc:
                report['observations'][name] = {'path': path, 'error': repr(exc)}
        commands = {
            'device-names': 'for p in /dev/* /dev/usb/* /sys/class/udc/*; do printf "%s\\n" "$p"; done',
            'open-fds': 'ls -l /proc/149/fd',
            'usb-sysfs': 'for p in /sys/class/udc/*/current_speed /sys/class/udc/*/maximum_speed /sys/class/udc/*/state; do if [ -f "$p" ]; then printf "%s\\n" "$p"; while IFS= read -r v; do printf "%s\\n" "$v"; done < "$p"; fi; done',
        }
        for name, command in commands.items():
            try:
                row = dbg.request(3, command.encode())
                retain(name+'.txt', row['payload'], command=command, status=row['status'], flags=row['flags'])
            except Exception as exc:
                report['observations'][name] = {'command': command, 'error': repr(exc)}
        # Linked ELF addresses, not process addresses. Read regular library files
        # only; translate each range using its original PT_LOAD file mapping.
        from elftools.elf.elffile import ELFFile
        windows = [('libObj.so', 0x71a320, 0x398),
                   ('libObj.so', 0x5cd7dc, 0x72),
                   ('libInfraRemote.so', 0xccf4, 0x8c),
                   ('libInfraStreamingServer.so', 0x10ad8, 0x84),
                   ('libInfraStreamingServer.so', 0x156a0, 0x1bc)]
        libroot = ROOT/'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/lib'
        for library, address, size in windows:
            name = f'{library}-{address:08x}.bin'
            try:
                with (libroot/library).open('rb') as handle:
                    elf = ELFFile(handle)
                    segments = [s for s in elf.iter_segments() if s['p_type']=='PT_LOAD'
                        and s['p_vaddr'] <= address and address+size <= s['p_vaddr']+s['p_filesz']]
                    if len(segments) != 1:
                        raise ValueError('Ambiguous file mapping')
                    seg = segments[0]
                    offset = address-seg['p_vaddr']+seg['p_offset']
                    handle.seek(offset)
                    expected = handle.read(size)
                data = dbg.read('/usr/lib/'+library, offset, size)
                retain(name, data, path='/usr/lib/'+library, file_offset=offset,
                       linked_address=address, expected_sha256=hashlib.sha256(expected).hexdigest(),
                       source_equal=data == expected, note='File equality, not live process-memory equality')
            except Exception as exc:
                report['observations'][name] = {'error': repr(exc)}
        # Resolve version-dependent entry points from the actual camera ELF.
        # Never infer a live address by applying a blanket version delta.
        from tools.research.remote_elf import RemoteElf32, debugger_reader
        for library, names in [
            ('libObj.so', ['ModelUsbLiveViewToInstance', 'ModelLiveViewTransferToInstance']),
            ('libInfraRemote.so', ['_ZN17MrpwDeviceManager17GetLiveViewStatusEv']),
        ]:
            try:
                remote = RemoteElf32(debugger_reader(dbg, '/usr/lib/'+library))
                for symbol in names:
                    record = remote.resolve(symbol)
                    if not 0 < record['size'] <= 4096:
                        raise ValueError('Function exceeds capture bound')
                    data = remote.virtual(record['value'] & ~1, record['size'])
                    retain(library+'-'+symbol+'.bin', data, path='/usr/lib/'+library,
                           symbol=record, capture='Actual camera ELF regular file')
            except Exception as exc:
                report['observations'][library+'-dynamic-symbols'] = {'error': repr(exc)}
    entries = json.loads((ROOT/'artifacts/inventory/elf-inventory.json').read_text())['entries']
    for entry in entries:
        hits = [{**symbol, 'table': table} for table in ('imports', 'exports')
                for symbol in entry[table] if PATTERN.search(symbol['name'])]
        if not hits:
            continue
        path = ROOT / entry['path']
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        report['local_candidates'].append({'path': entry['path'], 'sha256': actual,
            'inventory_sha256': entry['sha256'], 'identity_matches': actual == entry['sha256'],
            'symbols': hits})
    report['limitations'] = ['Non-atomic USB-connected observations; no active live-view capture.',
        'Symbol names do not prove capability, supported resolution, FPS or USB transport.',
        'Local ELF identity is checked against inventory, not whole-file equality with live camera.']
    (out/'manifest.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(out)
    for row in report['local_candidates']:
        print(Path(row['path']).name, len(row['symbols']), 'identity_matches=', row['identity_matches'])


if __name__ == '__main__':
    main()
