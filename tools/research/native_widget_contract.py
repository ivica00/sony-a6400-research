"""Read actual widget-system and tree-accessor instructions, without calling them."""
import json
import struct
from pathlib import Path
from datetime import datetime
from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB
from tools.camera_debugger import connect
from tools.research.remote_elf import RemoteElf32,debugger_reader

ROOT=Path(__file__).resolve().parents[2]
NAMES=['_ZN2ux6wgtsys12WidgetSystem15sys_getInstanceEv',
       '_ZNK2ux6wgtsys12WidgetSystem8getLayerERKNS_4core2IDE',
       '_ZNK2ux6wgtsys12WidgetSystem9getWidgetERKNS_4core2IDE',
       '_ZNK2ux6wgtsys6Widget9getParentEv','_ZNK2ux6wgtsys6Widget13getFirstChildEv',
       '_ZNK2ux6wgtsys6Widget14getNextSiblingEv','_ZNK2ux6wgtsys6Widget14getPrevSiblingEv',
       '_ZNK2ux6wgtsys6Widget7getModeEv','_ZN2ux6wgtsys12WidgetSystem18getGestureAnalyzerEv']
NAMES += ['_ZNK2ux6wgtsys12WidgetSystem13getMouseStateEhh',
          '_ZNK2ux6wgtsys12WidgetSystem24getMousePosInFramebufferEhRsS2_']


def main():
    destination=ROOT/'artifacts/hardware'/('native-widget-contract-'+datetime.now().strftime('%Y%m%d-%H%M%S'))
    destination.mkdir(parents=True,exist_ok=False)
    report={'memory_writes':False,'mode_switches':False,'functions':{}}
    with connect() as debugger:
        maps,_=debugger.read_all('/proc/149/maps')
        rows=[s for s in maps.decode().splitlines() if s.endswith('/libObj.so') and 'r-xp 00000000 ' in s]
        if len(rows)!=1: raise ValueError('Ambiguous library')
        base=int(rows[0].split('-')[0],16)
        elf=RemoteElf32(debugger_reader(debugger,'/usr/lib/libObj.so'))
        disassembler=Cs(CS_ARCH_ARM,CS_MODE_THUMB)
        for name in NAMES:
            try:
                symbol=elf.resolve(name); linked=symbol['value']&~1; size=min(symbol['size'],512)
                code=debugger.memory(149,base+linked,size)
                if code!=elf.virtual(linked,size): raise ValueError('Live/file code mismatch')
                decoded=[{'address':hex(i.address),'bytes':i.bytes.hex(),'instruction':i.mnemonic+' '+i.op_str}
                         for i in disassembler.disasm(code,base+linked)]
                report['functions'][name]={**symbol,'address':hex(base+linked),'code':code.hex(),'instructions':decoded}
                print(name,hex(base+linked),flush=True)
                print('\n'.join(i['address']+' '+i['instruction'] for i in decoded),flush=True)
            except Exception as error: report['functions'][name]={'error':str(error)}
        report['referenced_windows']={}
        for address,size in [(0x631e7b8,128),(0x64c692e,96),(0x63158e4,32),(0x6309938,72),(0x630aa00,80),
                             (0x6309640,56),(0x630a9d0,48),(0x64cee78,48),(0x64cea84,64)]:
            code=debugger.memory(149,address,size)
            if code!=elf.virtual(address-base,size): raise ValueError('Referenced window source mismatch')
            decoded=[{'address':hex(i.address),'bytes':i.bytes.hex(),'instruction':i.mnemonic+' '+i.op_str}
                     for i in disassembler.disasm(code,address)]
            report['referenced_windows'][hex(address)]={'code':code.hex(),'instructions':decoded}
            print('REFERENCED',hex(address)); print('\n'.join(i['address']+' '+i['instruction'] for i in decoded))
        instance=report['functions'][NAMES[0]]
        code=bytes.fromhex(instance['code']); address=int(instance['address'],16)
        if code[:16]!=bytes.fromhex('034b044a7b4480b500af9b58186880bd'):
            raise ValueError('WidgetSystem singleton producer differs')
        slot=(address+8+struct.unpack_from('<I',code,16)[0]+struct.unpack_from('<I',code,20)[0])&0xffffffff
        storage=struct.unpack('<I',debugger.memory(149,slot,4))[0]
        pointer=struct.unpack('<I',debugger.memory(149,storage,4))[0]
        report['singleton']={'got_slot':hex(slot),'storage':hex(storage),'pointer':hex(pointer)}
        if pointer:
            state=debugger.memory(149,pointer,0x500)
            (destination/'WidgetSystem.bin').write_bytes(state)
            report['singleton']['state']=state.hex()
        print('SINGLETON',report['singleton'])
    (destination/'manifest.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(destination)


if __name__=='__main__': main()
