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
from tools.camera_debugger import connect
from tools.research.remote_elf import RemoteElf32, debugger_reader
from tools.research.active_menu_snapshot_probe import HW, ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--steps', type=int, default=8)
    parser.add_argument('--main-thread-control', action='store_true')
    args = parser.parse_args()
    if not 1 <= args.steps <= 24: raise ValueError('Step bound is 1..24')
    destination = HW / 'native-menu-activation-dependencies.json'
    records = json.loads(destination.read_text()) if destination.exists() else []
    history = []
    runner = [sys.executable, '-m', 'tools.research.menu_activation_snapshot_probe']
    if args.main_thread_control: runner.append('--main-thread-control')
    report_name = 'menu-activation-main-thread-snapshot-probe.json' if args.main_thread_control else 'menu-activation-snapshot-probe.json'
    try:
        with connect() as debugger:
            modules = [(0x155e6000, 0x16100000, '/usr/lib/viewUnified2.so'),
                       (0x1615f000, 0x16c00000, '/usr/lib/CautionConfig.so'),
                       (0x42c1000, 0x43ae000, '/lib/libc-2.11.2.so'),
                       (0x4079000, 0x4089000, '/lib/libpthread-2.11.2.so'),
                       (0x5d18000, 0x7000000, '/usr/lib/libObj.so')]
            elves = {}
            for step in range(args.steps):
                subprocess.run(runner, cwd=ROOT, check=True, capture_output=True)
                report = json.loads((ROOT / 'artifacts/analysis' / report_name).read_text())
                boundary = report['boundary']; history.append(dict(main_thread_control=args.main_thread_control, instructions=report['instructions'], pc=report['pc'], boundary=boundary))
                print(step, report['instructions'], boundary, flush=True)
                if report['returned'] or not boundary or boundary['kind'] == 'write': break
                address = int(boundary['address'], 16)
                code = boundary['kind'] == 'code' or boundary.get('access') == 21
                if boundary.get('access') not in (None, 19, 21): break
                if 0x8300000 <= address < 0x8340000:
                    raise ValueError('Missing emulator scratch bytes must not be supplied from camera')
                if not code and not 0x14000 <= address < 0x5f000000:
                    raise ValueError('Missing read outside verified camera user limit; check architectural/thread context')
                if code:
                    module = next((m for m in modules if m[0] <= address < m[1]), None)
                    if module is None: raise ValueError('Missing code outside approved source modules')
                    base, _, path = module
                    if path not in elves: elves[path] = RemoteElf32(debugger_reader(debugger, path))
                    data = debugger.memory(149, address, 256)
                    if data != elves[path].virtual(address - base, len(data)):
                        raise ValueError('Live/file original code differs')
                    source = dict(source_equal=True, module=path, linked=hex(address - base))
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
