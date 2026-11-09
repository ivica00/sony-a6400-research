"""Original row geometry/hit on the SAME frozen held-touch/menu capture.

CPU threads were stopped together; DMA was not. This verifies a captured point,
not physical event dispatch, popup exclusion, selection, or visible refresh.
"""
import json
import struct
from tools.research.active_menu_snapshot_probe import HW, ROOT, geometry
from tools.research.prepare_active_menu_control import model_path
from tools.research.setting_node_snapshot_probe import run


def main():
    capture = json.loads((HW/'native-touch-geometry-pid1673.json').read_text())
    if not capture['complete_binary']:
        raise ValueError('Complete coupled capture required')
    known = {}
    for record in capture['records']:
        for offset, value in enumerate(bytes.fromhex(record['data'])):
            address = int(record['address'], 16)+offset
            if address in known and known[address] != value:
                raise ValueError('Conflicting captured bytes')
            known[address] = value
    def raw(address, size):
        return bytes(known[address+i] for i in range(size))
    menu, = [int(r['address'], 16) for r in capture['records']
             if r['size'] == 0x186bc]
    if struct.unpack('<I', raw(menu, 4))[0] != 0x15f1f1d0:
        raise ValueError('Unexpected menu type')
    point = struct.unpack('<2h', raw(0x956f0+0x4a8, 4))
    raw_point = struct.unpack('<2h', raw(0x956f0+0x4ac, 4))
    buttons = struct.unpack('<I', raw(0x956f0+0x4b0, 4))[0]
    if point != raw_point or 32767 in raw_point or not buttons & 1:
        raise ValueError('No coupled held touch')
    log = (HW/'native-touch-geometry-pid1673.log').read_text()
    import re
    tls_match = re.search(r'UI_TLS tid=380 value=([0-9a-f]{8})', log)
    if tls_match is None:
        raise ValueError('Missing UI TLS provenance')
    tls = int(tls_match[1], 16)
    thread_words = struct.unpack('<4I', raw(tls-0x4c0+0x60, 16))
    if thread_words[2:] != (380, 149):
        raise ValueError('Captured UI thread identity differs')
    world = json.loads((HW/'native-widget-worldpos-contracts.json').read_text())
    hit = json.loads((HW/'native-hit-visibility-contracts.json').read_text())
    for r in world['additional'] + [r for r in hit if r['name'] == 'menu_hit_vtable']:
        for i, value in enumerate(bytes.fromhex(r['data'])):
            address = int(r['address'], 16)+i
            if address in known and known[address] != value:
                raise ValueError('Older helper conflicts with coupled capture')
    path = model_path(capture, menu)
    results, writes, fixes = geometry(capture['records'],
        [menu+0x9350+i*0x1118 for i in range(6)], [point])
    hits = [i+1 for i, r in enumerate(results)
            if r['returned'] and r['hit_results'][0]['hit']]
    selection = None
    if len(hits) == 1:
        selection = run('22setItemSelectedByIndex', hits[0], snapshot=path[2])
        if selection['status'] != 1 or selection['selected_after'] != hits[0]:
            raise ValueError('Original selection did not match coupled hit')
    report = dict(scope=__doc__, capture_sha256=capture['sha256'], menu=hex(menu),
        point=point, raw_point=raw_point, buttons=buttons, model_path=path,
        original_geometry=results, hits=hits, emulator_cache_writes=writes,
        stale_it_workarounds=fixes,
        captured_refresh_slot=hex(struct.unpack('<I', raw(0x15f1f1d0+0x1ac, 4))[0]),
        physical_selection_enabled=False, visible_refresh_proven=False)
    report['separate_original_selection_control'] = selection
    report['captured_ui_thread'] = dict(tls=hex(tls), tid=380, pid=149)
    (ROOT/'artifacts/analysis/coupled-touch-geometry-e0130.json').write_text(json.dumps(report, indent=2))
    for r in results:
        if not r['returned']:
            raise ValueError(r)
    if len(hits) != 1:
        raise ValueError('Expected one unambiguous original row hit')
    print('Captured point', point, 'original hit rows', hits)
    print('Original row bounds:', [r['world_corners'] for r in results])
    print('Actual refresh slot:', report['captured_refresh_slot'])


if __name__ == '__main__':
    main()
