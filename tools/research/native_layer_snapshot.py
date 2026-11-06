"""Bounded read-only traversal of the verified WidgetSystem layer-list contract."""
import json
import struct
from datetime import datetime
from pathlib import Path
from tools.camera_debugger import connect

ROOT=Path(__file__).resolve().parents[2]

def main():
    result={'read_only':True,'atomic':False,'layers':[]}
    with connect() as debugger:
        def read(address,size):
            if not 0x15000 <= address < 0x5f000000 or size>4096:
                raise ValueError('Read outside bounded user memory')
            return debugger.memory(149,address,size)
        def word(address): return struct.unpack('<I',read(address,4))[0]
        system=word(0x7108058)
        container=system+0x484
        sentinel=container+0x10
        node=word(container+0xc)
        seen=set()
        while node!=sentinel and node:
            if node in seen or len(seen)>=64: raise ValueError('Layer list cycle/limit')
            seen.add(node)
            data=read(node,32)
            layer=struct.unpack_from('<I',data)[0]
            state=read(layer,128)
            result['layers'].append({'node':hex(node),'node_data':data.hex(),
                                     'layer':hex(layer),'state':state.hex(),
                                     'vtable':hex(struct.unpack_from('<I',state)[0])})
            if word(node+4)!=container: raise ValueError('Unexpected list owner')
            node=word(node+0xc)
        result['system']=hex(system)
        result['mouse_records']=read(system+0x4a8,80).hex()
    destination=ROOT/'artifacts/hardware'/('native-layer-snapshot-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'.json')
    destination.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2)); print(destination)

if __name__=='__main__': main()
