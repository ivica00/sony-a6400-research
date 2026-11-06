"""Verify original geometric hit checks and separate original selection controls.

Coordinates are explicit offline controls. This does not implement or prove the
camera's event-to-selection adapter, visibility routing, clipping, or activation.
"""
import json
from tools.research.active_menu_snapshot_probe import geometry, HW, ROOT
from tools.research.setting_node_snapshot_probe import run


def main():
    capture = json.loads((HW / 'native-layout-snapshot-pid2491.json').read_text())
    if not capture['complete_binary']: raise ValueError('Complete snapshot required')
    associations = json.loads((ROOT / 'artifacts/analysis/menu-row-snapshot-probe.json').read_text())
    page = json.loads((HW / 'native-setting-node-after-layout-pid2491.json').read_text())['path'][2]
    widgets = [int(row['widget'], 16) for row in associations['rows']]
    points = [(320, 150 + 50 * i) for i in range(6)]
    # Include all row edges and the two-pixel separator after each row.
    for i in range(6):
        y = 126 + 50 * i
        points += [(16, y + 24), (17, y), (622, y + 47), (623, y + 24), (320, y + 48), (320, y + 49)]
    results, writes, fixes = geometry(capture['records'], widgets, points)
    for row_index, result in enumerate(results):
        if not result['returned']: raise ValueError(result)
        for i, hit in enumerate(result['hit_results'][:6]):
            if hit['hit'] != int(i == row_index): raise ValueError('Original hit matrix differs')
        own = result['hit_results'][6 + row_index * 6:12 + row_index * 6]
        if [hit['hit'] for hit in own] != [0, 1, 1, 0, 0, 0]:
            raise ValueError('Original row edge controls differ')
    selections = [run('22setItemSelectedByIndex', i, snapshot=page) for i in range(1, 7)]
    invalid = [run('22setItemSelectedByIndex', i, snapshot=page) for i in (0, 7)]
    if any(row['status'] != 1 or row['selected_after'] != row['argument'] for row in selections):
        raise ValueError('Original page selection control failed')
    if selections[0]['writes']: raise ValueError('Current row selection was not a no-op')
    if any(row['status'] or row['selected_after'] != 1 or row['writes'] for row in invalid):
        raise ValueError('Invalid page selection mutated model')
    report = dict(scope=__doc__, geometric_hit_checks=results, emulator_cache_writes=writes,
                  stale_it_workarounds=fixes, separate_selection_controls=selections,
                  invalid_selection_controls=invalid, camera_input_routing_proven=False,
                  activation_proven=False)
    destination = ROOT / 'artifacts/analysis/menu-row-hit-snapshot-probe.json'
    destination.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(destination)
    print('252 original hit checks; six separate selection controls; invalid 0/7 rejected')


if __name__ == '__main__': main()
