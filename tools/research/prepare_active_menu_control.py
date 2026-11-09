"""Prepare an actual coupled menu/model/cache input, preserving provenance.

Covered bytes come from one CPU-thread-consistent native capture. Additional
older dependencies outside its coverage remain explicitly non-atomic inputs.
"""
import hashlib
import argparse
import json
import re
import struct
from pathlib import Path
from tools.research.active_menu_snapshot_probe import HW
from tools.research.prepare_resource_snapshot_control import refresh_records


def model_path(capture, menu):
    known = {}
    for record in capture['records']:
        base = int(record['address'], 16)
        for i, value in enumerate(bytes.fromhex(record['data'])):
            if base+i in known and known[base+i] != value: raise ValueError('Conflicting capture')
            known[base+i] = value
    def read(address, size):
        if not all(address+i in known for i in range(size)): raise ValueError('Uncaptured model bytes '+hex(address))
        return bytes(known[address+i] for i in range(size))
    address = struct.unpack('<I', read(menu+0x186ac,4))[0]
    path, seen = [], set()
    for _ in range(6):
        if address in seen: raise ValueError('Model cycle')
        seen.add(address);raw=read(address,64)
        if struct.unpack_from('<I',raw)[0] != 0x16c183e8: raise ValueError('Unexpected model type')
        array,count=struct.unpack_from('<2I',raw,4);selected=struct.unpack_from('<I',raw,0x18)[0]
        if count>128: raise ValueError('Model count bound')
        data=read(array,count*4) if count else b''
        children=[dict(object=hex(child),data=read(child,64).hex()) for child in struct.unpack('<'+'I'*count,data)]
        path.append(dict(object=hex(address),data=raw.hex(),array_address=hex(array),array=data.hex(),count=count,selected=selected,children=children))
        if not count:return path
        if not 1<=selected<=count:raise ValueError('Invalid captured selection')
        address=int(children[selected-1]['object'],16)
    raise ValueError('Model depth bound')


def capture_tag(pid):
    if pid == 'pid2991': return 'e0115'
    if pid == 'pid3119': return 'e0115b'
    if not re.fullmatch(r'pid[0-9]+', pid): raise ValueError('Invalid capture PID')
    return pid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pid', nargs='?', default='pid2991')
    parser.add_argument('--code-dependencies', type=Path, action='append', default=[])
    args = parser.parse_args()
    pid = args.pid
    tag = capture_tag(pid)
    capture=json.loads((HW/f'native-layout-resource-snapshot-{pid}.json').read_text())
    log=(HW/f'native-layout-resource-snapshot-{pid}.log').read_text()
    freezes = re.findall(r'FREEZE threads=(\d+) attached=(\d+) resumed=(\d+) result=(-?\d+)', log)
    if not freezes or not (int(freezes[-1][0]) > 0 and freezes[-1][0] == freezes[-1][1] == freezes[-1][2] and freezes[-1][3] == '0'): raise ValueError('All captured CPU threads must have resumed')
    required=['SNAPSHOT result=0','BINARY result=0','END result=0']
    if not capture['complete_binary'] or any(part not in log for part in required) or not re.search(r'RESOURCE_LIST nodes=\d+ nonzero_references=0 active_present=0', log):raise ValueError('Complete coupled capture required')
    menus=[row for row in capture['records'] if row['size']==0x186bc and bytes.fromhex(row['data'])[:4]==struct.pack('<I',0x15f1f1d0)]
    if len(menus)!=1:raise ValueError('Ambiguous actual menu')
    menu=int(menus[0]['address'],16);path=model_path(capture,menu)
    source_path=HW/'native-menu-activation-dependencies-e0113.json'
    original=source_path.read_bytes();source=json.loads(original)
    # Retain only verified additional original code, never V5 heap data.
    additional_code = HW/'native-menu-activation-dependencies-e0115b.json'
    if pid not in ('pid2991', 'pid3119') and additional_code.exists():
        source += [row for row in json.loads(additional_code.read_text()) if row.get('code') and row.get('source_equal')]
    code_sources = []
    for dependency_path in args.code_dependencies:
        raw = dependency_path.read_bytes()
        rows = json.loads(raw)
        selected = [row for row in rows if row.get('code') is True and row.get('source_equal') is True]
        if not selected: raise ValueError('No original source-equal code in dependency input')
        for row in selected:
            if row.get('sha256') and hashlib.sha256(bytes.fromhex(row['data'])).hexdigest() != row['sha256']:
                raise ValueError('Original code dependency hash differs')
        source.extend(selected)
        code_sources.append(dict(path=str(dependency_path), sha256=hashlib.sha256(raw).hexdigest(), code_records=len(selected)))
    regions=[(int(row['address'],16),bytes.fromhex(row['data'])) for row in capture['records']]
    refreshed,differences=refresh_records(source,regions,allow_identical_code=True)
    refreshed += [dict(**row,code=False,source='Coupled active CPU subset; uncovered older dependencies remain non-atomic') for row in capture['records']]
    destination=HW/f'native-menu-activation-dependencies-{tag}.json'
    destination.write_text(json.dumps(refreshed,indent=2),encoding='utf-8')
    manifest=dict(source_capture_sha256=capture['sha256'],older_dependency_sha256=hashlib.sha256(original).hexdigest(),
                  additional_code_sources=code_sources,menu=hex(menu),model_path=[row['object'] for row in path],covered_records=len(capture['records']),
                  refreshed_differences=differences,whole_input_atomic=False,scope=__doc__)
    (HW/f'native-active-menu-{tag}-control.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print('Actual menu',hex(menu),'model path',manifest['model_path'],'refreshed byte differences',len(differences))


if __name__=='__main__':main()
