"""Locate candidate native Sony menu objects in the primary heap, read-only."""
import json
import struct
import hashlib
from pathlib import Path
from datetime import datetime
from tools.camera_debugger import connect,MAX_DATA
from tools.research.remote_elf import RemoteElf32,debugger_reader

ROOT=Path(__file__).resolve().parents[2]


def main():
    destination=ROOT/'artifacts/hardware'/('native-menu-objects-'+datetime.now().strftime('%Y%m%d-%H%M%S'))
    destination.mkdir(parents=True,exist_ok=False)
    report={'mode_switches':False,'memory_writes':False,'scope':'candidate objects in primary heap only'}
    with connect() as debugger:
        maps,_=debugger.read_all('/proc/149/maps'); text=maps.decode()
        (destination/'maps.txt').write_bytes(maps)
        lines=[line for line in text.splitlines() if line.endswith('/viewUnified2.so') and 'r-xp 00000000 ' in line]
        if len(lines)!=1: raise ValueError('Ambiguous view library')
        base=int(lines[0].split('-')[0],16)
        elf=RemoteElf32(debugger_reader(debugger,'/usr/lib/viewUnified2.so'))
        fn=0x56c92c
        code=elf.virtual(fn,0x144)
        if code[0x12:0x14]!=bytes.fromhex('7c44') or code[0x1c:0x1e]!=bytes.fromhex('e358'):
            raise ValueError('Menu constructor producer does not match verified anchors')
        def literal(instruction_offset,register):
            op=struct.unpack_from('<H',code,instruction_offset)[0]
            if op&0xf800!=0x4800 or (op>>8)&7!=register: raise ValueError('Unexpected literal load')
            address=((fn+instruction_offset+4)&~3)+(op&255)*4
            return struct.unpack('<I',elf.virtual(address,4))[0]
        slot=fn+0x16+literal(6,4)+literal(0x10,3)
        vtable=struct.unpack('<I',debugger.memory(149,base+slot,4))[0]+8
        report.update(constructor_linked=hex(fn),got_slot_linked=hex(slot),vtable_runtime=hex(vtable))
        table=debugger.memory(149,vtable,0x1ac)
        (destination/'vtable.bin').write_bytes(table)
        report['mouse_method']=hex(struct.unpack_from('<I',table,0x68)[0])
        report['mouse_hook_method']=hex(struct.unpack_from('<I',table,0x6c)[0])
        report['set_default_mode_method']=hex(struct.unpack_from('<I',table,0x108)[0])
        heap=[line for line in text.splitlines() if line.endswith('[heap]') and 'rw-p' in line]
        if len(heap)!=1: raise ValueError('Ambiguous primary heap')
        start,end=[int(x,16) for x in heap[0].split()[0].split('-')]
        if end-start>8*1024*1024: raise ValueError('Primary heap exceeds scan bound')
        needle=struct.pack('<I',vtable); tail=b''; candidates=[]; digest=hashlib.sha256()
        for address in range(start,end,MAX_DATA):
            data=debugger.memory(149,address,min(MAX_DATA,end-address)); digest.update(data)
            window=tail+data; offset=0
            while True:
                found=window.find(needle,offset)
                if found<0: break
                location=address-len(tail)+found
                if not location&3: candidates.append(location)
                offset=found+1
            tail=data[-3:]
            if (address-start)//MAX_DATA%128==0: print('heap scan bytes:',address-start,flush=True)
        report['heap_scan']={'start':hex(start),'end':hex(end),'bytes':end-start,'observed_stream_sha256':digest.hexdigest(),
                             'atomic_snapshot':False}
        report['candidates']=[]
        for address in candidates[:32]:
            size=min(0xb94,end-address)
            data=debugger.memory(149,address,size)
            (destination/(f'candidate-{address:08x}.bin')).write_bytes(data)
            row={'address':hex(address),'bytes':size,'confirmed_live_widget':False}
            if size>=0x22c:
                row.update(default_mode_at_0x180=struct.unpack_from('<I',data,0x180)[0],
                           child_list_vtable_at_0x228=hex(struct.unpack_from('<I',data,0x228)[0]),
                           menu_data_at_0x1d8=hex(struct.unpack_from('<I',data,0x1d8)[0]))
            report['candidates'].append(row)
        report['candidate_count']=len(candidates)
    (destination/'manifest.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2)); print(destination)


if __name__=='__main__': main()
