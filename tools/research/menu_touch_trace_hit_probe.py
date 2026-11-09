"""Replay observed framebuffer points against a RETAINED menu, not the live UI.

This does not establish that the retained geometry was present during the taps,
nor that framebuffer coordinates need no native transform before hit testing.
"""
import hashlib
import json
from tools.research.active_menu_snapshot_probe import HW, ROOT, geometry


def main():
    trace_path = HW / 'menu-touch-trace-read-20261106-195941.json'
    trace = json.loads(trace_path.read_text())
    events = trace['committed_events']
    if trace['header'][3] != len(events) or len(events) != 6:
        raise ValueError('Incomplete physical trace')
    if any(e['tid'] != 380 or e['system'] != '0x956f0' or
           e['transport_type'] != 2 or e['mouse'] != 0 or e['button'] != 0
           for e in events):
        raise ValueError('Unexpected physical release identity')
    capture = json.loads((HW / 'native-layout-resource-snapshot-pid1175.json').read_text())
    menu = next(int(r['address'], 16) for r in capture['records'] if r['size'] == 0x186bc)
    # Reject conflicting imports rather than silently mixing geometry phases.
    known = {}
    for r in capture['records']:
        a = int(r['address'], 16)
        known.update({a+i: v for i, v in enumerate(bytes.fromhex(r['data']))})
    world = json.loads((HW / 'native-widget-worldpos-contracts.json').read_text())
    for r in world['additional']:
        a = int(r['address'], 16)
        for i, v in enumerate(bytes.fromhex(r['data'])):
            if a+i in known and known[a+i] != v:
                raise ValueError('Geometry import conflicts with retained capture')
    points = [tuple(e['framebuffer_xy']) for e in events]
    results, writes, fixes = geometry(capture['records'],
        [menu+0x9350+i*0x1118 for i in range(6)], points)
    if any(not r['returned'] for r in results):
        raise ValueError('Original hit did not return')
    hits = [[i+1 for i, r in enumerate(results)
             if r['hit_results'][j]['hit']] for j in range(len(points))]
    report = dict(scope=__doc__, trace=str(trace_path.relative_to(ROOT)),
        trace_sha256=hashlib.sha256(trace_path.read_bytes()).hexdigest(),
        retained_capture_sha256=capture['sha256'], observed_ui_tid=380,
        points=points, retained_geometry_hits=hits, original_hit_results=results,
        emulator_cache_writes=writes, stale_it_workarounds=fixes,
        contemporaneous_geometry_proven=False, live_selection_enabled=False)
    output = ROOT / 'artifacts/analysis/menu-touch-trace-hit-e0128.json'
    output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print('36 original hit checks on retained geometry:', hits)
    print('Contemporaneous geometry/transform not proven; no live selection')


if __name__ == '__main__':
    main()
