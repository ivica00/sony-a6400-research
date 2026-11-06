"""Read current native touch code/state through the installed normal-USB debugger."""
import json
import struct
from datetime import datetime
from pathlib import Path
from tools.camera_debugger import connect,MAX_DATA
from tools.research.remote_elf import RemoteElf32

ROOT=Path(__file__).resolve().parents[2]


def main():
    destination=ROOT/'artifacts/hardware'/('native-touch-state-'+datetime.now().strftime('%Y%m%d-%H%M%S'))
    destination.mkdir(parents=True,exist_ok=False)
    report={'mode_switches':False,'memory_writes':False,'pid':149}
    with connect() as debugger:
        maps,_=debugger.read_all('/proc/149/maps')
        (destination/'maps.txt').write_bytes(maps)
        def base(name):
            matches=[int(line.split('-')[0],16) for line in maps.decode().splitlines()
                     if line.endswith('/'+name) and 'r-xp 00000000 ' in line]
            if len(matches)!=1: raise ValueError('Ambiguous mapping: '+name)
            return matches[0]
        obj=base('libObj.so'); view=base('viewUnified2.so')
        def file_reader(path):
            def read(offset,count):
                result=bytearray()
                while len(result)<count:
                    block=debugger.read(path,offset+len(result),min(MAX_DATA,count-len(result)))
                    if not block: break
                    result.extend(block)
                return bytes(result)
            return read
        elf=RemoteElf32(file_reader('/usr/lib/libObj.so'))
        report['symbols']={}
        names=['_ZN7InfraTp11GetInstanceEv','_ZN7InfraTp12SetTpEventSwEb',
               '_ZN12InputService11callback_tpEiP16_InfraInputEvent',
               '_ZN12InputService15callback_tp_rawEiP16_InfraInputEvent']
        for name in names:
            symbol=elf.resolve(name); linked=symbol['value']&~1
            code=debugger.memory(149,obj+linked,min(symbol['size'],200))
            (destination/(name+'.bin')).write_bytes(code)
            report['symbols'][name]={**symbol,'runtime_address':hex(obj+linked),'code':code.hex()}
        get=report['symbols'][names[0]]
        code=bytes.fromhex(get['code']); address=int(get['runtime_address'],16)
        load=struct.unpack_from('<H',code,0x2e)[0]
        if load&0xf800!=0x4800 or (load>>8)&7!=3 or code[0x30:0x34]!=bytes.fromhex('7b441b68'):
            raise ValueError('GetInstance singleton producer does not match verified instruction shape')
        literal=((address+0x2e+4)&~3)+(load&255)*4
        delta=struct.unpack_from('<i',code,literal-address)[0]
        slot=(address+0x34+delta)&0xffffffff
        pointer=struct.unpack('<I',debugger.memory(149,slot,4))[0]
        report['singleton_slot']=hex(slot); report['singleton_pointer']=hex(pointer)
        if pointer and not pointer&3:
            state=debugger.memory(149,pointer,0xa4)
            (destination/'InfraTp_state.bin').write_bytes(state)
            report['observed_state']={'event_switch_at_0x32':state[0x32],
                'resource_settings_at_0x38':list(struct.unpack_from('<3I',state,0x38)),
                'resource_mode_at_0x44':struct.unpack_from('<I',state,0x44)[0]}
        # Recheck the menu gate without inferring the currently displayed widget.
        report['menu_gate']=debugger.memory(149,view+0x56dcb0,26).hex()
    (destination/'manifest.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='symbols'},indent=2))
    print(destination)


if __name__=='__main__': main()
