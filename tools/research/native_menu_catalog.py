"""Derive menu class vtables from verified type getters; verify on-camera code."""
import io
import json
import struct
from pathlib import Path
from datetime import datetime
from elftools.elf.elffile import ELFFile
from elftools.elf.relocation import RelocationSection
from tools.camera_debugger import connect
from tools.research.remote_elf import RemoteElf32,debugger_reader

ROOT=Path(__file__).resolve().parents[2]
CLASSES=['PAS_MenuTab','PAS_MenuListTab','PAS_MyMenuListTab','PAS_MenuSelectBelt',
         'PAS_MenuTable','PAS_MenuPopup','PAS_MenuSelectMode','PAS_MenuListPopup','PAS_MenuDataSelectBelt']


def main():
    destination=ROOT/'artifacts/hardware'/('native-menu-catalog-'+datetime.now().strftime('%Y%m%d-%H%M%S'))
    destination.mkdir(parents=True,exist_ok=False)
    raw=(ROOT/'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/lib/viewUnified2.so').read_bytes()
    source=ELFFile(io.BytesIO(raw))
    def original(address,count):
        p=next(p for p in source.iter_segments() if p['p_type']=='PT_LOAD' and p['p_vaddr']<=address and address+count<=p['p_vaddr']+p['p_filesz'])
        offset=p['p_offset']+address-p['p_vaddr']
        return raw[offset:offset+count]
    symbols={s.name:s for s in source.get_section_by_name('.dynsym').iter_symbols()}
    relative={}
    for section in source.iter_sections():
        if isinstance(section,RelocationSection):
            for rel in section.iter_relocations():
                if rel['r_info_type']==23:
                    address=rel['r_offset']; value=struct.unpack('<I',original(address,4))[0]
                    relative.setdefault(value,[]).append(address)
    report={'memory_writes':False,'mode_switches':False,'classes':[]}
    template_cast=original(0x56c7e4,0x24)
    template_getter=original(0x56c7cc,16)
    with connect() as debugger:
        maps,_=debugger.read_all('/proc/149/maps')
        lines=[l for l in maps.decode().splitlines() if l.endswith('/viewUnified2.so') and 'r-xp 00000000 ' in l]
        if len(lines)!=1: raise ValueError('Ambiguous view library')
        base=int(lines[0].split('-')[0],16)
        remote=RemoteElf32(debugger_reader(debugger,'/usr/lib/viewUnified2.so'))
        for name in CLASSES:
            row={'class':name}
            mangled=f'_ZN{len(name)}{name}4castEPN2ux6wgtsys6WidgetE'
            try:
                linked=symbols[mangled]['st_value']&~1
                cast=original(linked,44); getter=original(linked-24,24)
                if cast[:36]!=template_cast or getter[:16]!=template_getter: raise ValueError('Different type getter/cast shape')
                getter_slot=linked-24+8+struct.unpack_from('<I',getter,16)[0]+struct.unpack_from('<I',getter,20)[0]
                cast_slot=linked+12+struct.unpack_from('<I',cast,36)[0]+struct.unpack_from('<I',cast,40)[0]
                if getter_slot!=cast_slot: raise ValueError('Getter and cast compare different type IDs')
                candidates=[]
                for slot in relative.get((linked-24)|1,[]):
                    table=slot-0x190
                    # Itanium primary-vtable offset-to-top is zero; the RTTI
                    # word may be nonzero and must not be mistaken for it.
                    if original(table-8,4)==b'\0'*4:
                        dtor1,dtor2=struct.unpack('<2I',original(table,8))
                        if dtor1&1 and dtor2&1 and abs((dtor1&~1)-linked)<65536 and abs((dtor2&~1)-linked)<65536:
                            candidates.append(table)
                if len(candidates)!=1: raise ValueError('Absent or ambiguous vtable')
                table=candidates[0]
                actual=remote.resolve(mangled)['value']&~1
                if actual!=linked or remote.virtual(linked-24,68)!=getter+cast:
                    raise ValueError('Camera file differs from verified type code')
                if debugger.memory(149,base+linked-24,68)!=getter+cast:
                    raise ValueError('Live type code differs')
                live=debugger.memory(149,base+table,0x1ac)
                if struct.unpack_from('<I',live,0x190)[0]!=(base+linked-24)|1:
                    raise ValueError('Live vtable type slot differs')
                row.update(verified=True,cast_linked=hex(linked),type_id_got=hex(getter_slot),
                           vtable_linked=hex(table),vtable_runtime=hex(base+table),
                           mouse_method=hex(struct.unpack_from('<I',live,0x68)[0]),
                           mouse_hook_method=hex(struct.unpack_from('<I',live,0x6c)[0]),
                           mode_setter=hex(struct.unpack_from('<I',live,0x108)[0]))
            except Exception as error: row.update(verified=False,error=str(error))
            report['classes'].append(row)
            print(name,row,flush=True)
        targets=''.join(f"{int(row['vtable_runtime'],16):08x} {row['class']}\n" for row in report['classes'] if row.get('verified'))
        if not targets:
            report['status']='failed: no verified targets'
            (destination/'manifest.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
            raise RuntimeError('No verified menu targets')
        report['config_upload']=debugger.push('/tmp_bt/native_menu_targets.txt',targets.encode())
    (destination/'manifest.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    (destination/'targets.txt').write_text(targets,encoding='ascii')
    print(destination)


if __name__=='__main__': main()
