"""Decode retained read-only widget traces without contacting the camera."""
import argparse
import json
import re
import struct
from pathlib import Path


def decode(text, menu_vtable):
    snapshots, touches, errors = [], [], []
    current = None
    ending = None
    for line in text.splitlines():
        if line.startswith('TREE '):
            match = re.fullmatch(r'TREE sample=(\d+) ms=(\d+) result=(-?\d+) count=(\d+) read_ms=(\d+)', line)
            if not match:
                raise ValueError('Malformed tree header')
            sample, ms, result, count, read_ms = map(int, match.groups())
            current = dict(sample=sample, ms=ms, result=result, count=count,
                           read_ms=read_ms, widgets=[])
            snapshots.append(current)
            if result:
                errors.append(dict(sample=sample, result=result))
        elif line.startswith('widget '):
            match = re.fullmatch(r'widget object=([0-9a-f]{8}) parent=([0-9a-f]{8}) depth=(\d+) data=([0-9a-f]{96})', line)
            if current is None or not match:
                raise ValueError('Malformed or orphan widget record')
            obj, parent, depth, raw = match.groups()
            data = bytes.fromhex(raw)
            current['widgets'].append(dict(object=int(obj, 16), parent=int(parent, 16),
                depth=int(depth), vtable=struct.unpack_from('<I', data)[0],
                flags=data[32], mode=data[33]))
        elif line.startswith('change '):
            match = re.fullmatch(r'change sample=(\d+) ms=(\d+) read_ms=(\d+) data=([0-9a-f]{160})', line)
            if not match:
                raise ValueError('Malformed mouse record')
            data = bytes.fromhex(match[4])
            x, y = struct.unpack_from('<2h', data)
            state = struct.unpack_from('<I', data, 8)[0]
            if state:
                menus = [w for w in current['widgets'] if w['vtable'] == menu_vtable] if current else []
                touches.append(dict(sample=int(match[1]), ms=int(match[2]), x=x, y=y,
                    state=state, preceding_tree_sample=current['sample'] if current else None,
                    preceding_tree_result=current['result'] if current else None,
                    preceding_menu_widgets=menus))
        elif line.startswith('END '):
            ending = line
    for snapshot in snapshots:
        if len(snapshot['widgets']) != snapshot['count']:
            raise ValueError('Incomplete tree records at sample ' + str(snapshot['sample']))
    return dict(atomic=False, menu_vtable=hex(menu_vtable), snapshots=snapshots,
                active_mouse_samples=touches, tree_errors=errors, end=ending,
                limitation='Mouse state and preceding changed tree are observations, not callback or action proof.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log', type=Path)
    parser.add_argument('--menu-vtable', required=True, type=lambda value: int(value, 0))
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    report = decode(args.log.read_text(encoding='utf-8'), args.menu_vtable)
    args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(dict(snapshots=len(report['snapshots']),
        active_mouse_samples=len(report['active_mouse_samples']), tree_errors=report['tree_errors'],
        end=report['end']), indent=2))


if __name__ == '__main__':
    main()
