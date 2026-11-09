"""Bounded read-only capture of dependencies exposed by offline activation.

Never calls camera application functions. Missing code must match its original
camera ELF; missing data is explicitly a later, non-atomic USB observation.
Emulator scratch memory and unverified writes are never filled or bypassed.
"""
import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from tools.camera_debugger import connect
from tools.research.prepare_active_menu_control import capture_tag
from tools.research.remote_elf import RemoteElf32, debugger_reader
from tools.research.active_menu_snapshot_probe import HW, ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--steps', type=int, default=8)
    parser.add_argument('--main-thread-control', action='store_true')
    parser.add_argument('--resource-snapshot', action='store_true')
    parser.add_argument('--menu-resource-header', action='store_true')
    parser.add_argument('--active-state', type=Path)
    parser.add_argument('--native-row-entry', action='store_true')
    parser.add_argument('--auxiliary-usb-control', action='store_true')
    parser.add_argument('--packed-index-usb-control', action='store_true')
    parser.add_argument('--code-only', action='store_true', help='Stop before acquiring any missing data')
    parser.add_argument('--refresh-only', action='store_true', help='Separate refresh control; capture only source-equal read-only module bytes')
    args = parser.parse_args()
    if not 1 <= args.steps <= 24: raise ValueError('Step bound is 1..24')
    tag = capture_tag(args.active_state.stem.rsplit('-', 1)[-1]) if args.active_state else 'e0115'
    destination = HW / (f'native-menu-activation-dependencies-{tag}.json' if args.active_state else 'native-menu-activation-dependencies-e0113.json' if args.menu_resource_header else 'native-menu-activation-dependencies-e0111.json' if args.resource_snapshot else 'native-menu-activation-dependencies.json')
    if args.refresh_only:
        if not args.active_state or args.auxiliary_usb_control or args.packed_index_usb_control:
            parser.error('Refresh capture requires active state without exploratory inputs')
        destination = HW / f'native-menu-refresh-dependencies-{tag}.json'
    records = json.loads(destination.read_text()) if destination.exists() else []
    history = []
    runner = [sys.executable, '-m', 'tools.research.menu_activation_snapshot_probe']
    if args.main_thread_control: runner.append('--main-thread-control')
    if args.resource_snapshot: runner.append('--resource-snapshot')
    if args.menu_resource_header: runner.append('--menu-resource-header')
    if args.active_state: runner += ['--active-state', str(args.active_state)]
    if args.native_row_entry: runner.append('--native-row-entry')
    if args.auxiliary_usb_control: runner.append('--auxiliary-usb-control')
    if args.packed_index_usb_control: runner.append('--packed-index-usb-control')
    if args.refresh_only: runner.append('--refresh-only')
    report_name = 'menu-activation-coupled-state-probe.json' if args.active_state else 'menu-activation-live-resource-header-probe.json' if args.menu_resource_header else 'menu-activation-resource-snapshot-probe.json' if args.resource_snapshot else 'menu-activation-main-thread-snapshot-probe.json'
    if args.auxiliary_usb_control: report_name = 'menu-activation-auxiliary-usb-control.json'
    if args.packed_index_usb_control: report_name = 'menu-activation-packed-index-usb-control.json'
    if args.refresh_only: report_name = 'menu-refresh-coupled-state-probe.json'
    try:
        with connect() as debugger:
            modules = [(0x155e6000, 0x16100000, '/usr/lib/viewUnified2.so'),
                       (0x1615f000, 0x16c00000, '/usr/lib/CautionConfig.so'),
                       (0x42c1000, 0x43ae000, '/lib/libc-2.11.2.so'),
                       (0x4079000, 0x4089000, '/lib/libpthread-2.11.2.so'),
                       (0x5d18000, 0x7144000, '/usr/lib/libObj.so')]
            elves = {}
            for step in range(args.steps):
                subprocess.run(runner, cwd=ROOT, check=True, capture_output=True)
                report = json.loads((ROOT / 'artifacts/analysis' / report_name).read_text())
                boundary = report['boundary']; history.append(dict(packed_index_usb_control=args.packed_index_usb_control, auxiliary_usb_control=args.auxiliary_usb_control, code_only=args.code_only, main_thread_control=args.main_thread_control, resource_snapshot=args.resource_snapshot, menu_resource_header=args.menu_resource_header, active_state=str(args.active_state), native_row_entry=args.native_row_entry, instructions=report['instructions'], pc=report['pc'], boundary=boundary))
                print(step, report['instructions'], boundary, flush=True)
                if report['returned'] or not boundary or boundary['kind'] in ('write', 'invariant', 'control_complete'): break
                address = int(boundary['address'], 16)
                code = boundary['kind'] == 'code' or boundary.get('access') == 21
                if args.code_only and not code: break
                if boundary.get('access') not in (None, 19, 21): break
                if 0x8300000 <= address < 0x8340000:
                    raise ValueError('Missing emulator scratch bytes must not be supplied from camera')
                if not code and not 0x14000 <= address < 0x5f000000:
                    raise ValueError('Missing read outside verified camera user limit; check architectural/thread context')
                if code or args.refresh_only:
                    module = next((m for m in modules if m[0] <= address < m[1]), None)
                    if module is None:
                        if args.refresh_only: break
                        raise ValueError('Missing code outside approved source modules')
                    base, _, path = module
                    if path not in elves: elves[path] = RemoteElf32(debugger_reader(debugger, path))
                    if args.refresh_only:
                        segment = next((s for s in elves[path].segments
                            if s[0] == 1 and s[2] <= address-base and
                            address-base+256 <= s[2]+s[4]), None)
                        if segment is None or segment[6] & 2:
                            break  # Mutable globals require a coherent capture.
                    data = debugger.memory(149, address, 256)
                    if data != elves[path].virtual(address - base, len(data)):
                        raise ValueError('Live/file original code differs')
                    source = dict(source_equal=True, module=path, linked=hex(address - base))
                    if args.refresh_only: source['immutable'] = True
                else:
                    size = boundary['size']
                    if not 1 <= size <= 16: raise ValueError('Missing data exceeds single-read bound')
                    # Preserve a small aligned observed window, including the
                    # actual read. Overlaps must still agree in the runner.
                    requested = address
                    address &= ~15
                    window_size = 32 if requested + size > address + 16 else 16
                    data = debugger.memory(149, address, window_size)
                    source = dict(source='Later retained USB data; non-atomic with MENU snapshot')
                record = dict(address=hex(address), data=data.hex(), code=code,
                              sha256=hashlib.sha256(data).hexdigest(), **source)
                records.append(record)
                destination.write_text(json.dumps(records, indent=2), encoding='utf-8')
    finally:
        history_path = ROOT / 'artifacts/analysis/menu-activation-dependency-history.json'
        previous = json.loads(history_path.read_text()) if history_path.exists() else []
        history_path.write_text(json.dumps(previous + history, indent=2), encoding='utf-8')
    subprocess.run(runner, cwd=ROOT, check=True)


if __name__ == '__main__': main()
