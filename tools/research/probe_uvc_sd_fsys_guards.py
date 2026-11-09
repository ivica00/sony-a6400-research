"""Original native file API guards with explicit logging/lookup services."""
import hashlib,io,json,struct
from elftools.elf.elffile import ELFFile
from unicorn import Uc,UC_ARCH_ARM,UC_MODE_ARM,UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3,UC_ARM_REG_SP,UC_ARM_REG_LR,UC_ARM_REG_PC
from tools.research.arm_plt import resolve_arm_plt
from tools.research.build_uvc_ptp_descriptor_candidate import ROOT


def main():
    path=ROOT/'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/lib/libInfraFsys.so'
    raw=path.read_bytes();sha=hashlib.sha256(raw).hexdigest();assert sha=='75f24fd03f4a187563622d6320f0690108fa6e231ac6e84cbda9303b8dc9af2c'
    elf=ELFFile(io.BytesIO(raw));symbols={s.name:s['st_value'] for s in elf.get_section_by_name('.dynsym').iter_symbols() if s.name};plt=resolve_arm_plt(elf)
    cases=[('open-uninitialized','Fsys_Open',0,[0x200000,0x200100,6],0x80000010,False),('open-null-path','Fsys_Open',1,[0,0x200100,6],0x80000030,False),('open-null-output','Fsys_Open',1,[0x200000,0,6],0x80000030,False),('open-lookup-error','Fsys_Open',1,[0x200000,0x200100,6],0x80000041,True),('write-uninitialized','Fsys_WriteAndFlush',0,[1,0x200000,4],0x80000010,False),('write-null-buffer','Fsys_WriteAndFlush',1,[1,0,4],0x80000030,False),('write-negative-size','Fsys_WriteAndFlush',1,[1,0x200000,0xffffffff],0x80000030,False),('flush-uninitialized','Fsys_Flush',0,[1],0x80000010,False),('close-uninitialized','Fsys_Close',0,[1],0x80000010,False)]
    checks=[]
    for name,function,initialized,args,expected,lookup in cases:
        c=Uc(UC_ARCH_ARM,UC_MODE_ARM);c.mem_map(0,0x90000);c.mem_map(0x200000,0x10000);c.mem_map(0x300000,4096)
        for segment in elf.iter_segments():
            if segment['p_type']=='PT_LOAD':c.mem_write(segment['p_vaddr'],segment.data())
        for section_name in ('.rel.dyn','.rel.plt'):
            section=elf.get_section_by_name(section_name)
            for relocation in section.iter_relocations():
                if relocation['r_info_type'] in (21,22):
                    symbol=elf.get_section(section['sh_link']).get_symbol(relocation['r_info_sym'])
                    c.mem_write(relocation['r_offset'],struct.pack('<I',symbol['st_value']))
        c.mem_write(symbols['g_fsysStatus'],struct.pack('<I',initialized))
        c.mem_write(0x200000,b'X:/UVC_DIAGNOSTIC.LOG\0');c.mem_write(0x200100,struct.pack('<I',0xabcdef01))
        calls=[];returned=[]
        def hook(cpu,a,size,unused):
            if a==0x300000:returned.append(cpu.reg_read(UC_ARM_REG_R0));cpu.emu_stop();return
            if a in plt:
                target=plt[a]['name'];calls.append(target)
                if target.startswith('fsysDepTrace_') or target.startswith('fsysDepLog_'):result=0
                elif target=='fsys_GetDriveInfoFromPath':
                    assert cpu.reg_read(UC_ARM_REG_R0)==0x200000;result=0x80000041
                else:raise RuntimeError('Unexpected service '+target)
                cpu.reg_write(UC_ARM_REG_R0,result);cpu.reg_write(UC_ARM_REG_PC,cpu.reg_read(UC_ARM_REG_LR));return
            start=symbols[function]&~1
            symbol=next(s for s in elf.get_section_by_name('.dynsym').iter_symbols() if s.name==function)
            if not start<=a<start+symbol['st_size']:raise RuntimeError(f'Unexpected body {a:08x}')
        c.hook_add(UC_HOOK_CODE,hook)
        for reg,value in zip((UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3),args+[0]*4):c.reg_write(reg,value)
        c.reg_write(UC_ARM_REG_SP,0x20f000);c.reg_write(UC_ARM_REG_LR,0x300000)
        c.emu_start(symbols[function],0xffffffff,count=10000)
        assert returned==[expected],(name,returned)
        assert calls.count('fsys_GetDriveInfoFromPath')==int(lookup)
        output=struct.unpack('<I',c.mem_read(0x200100,4))[0]
        assert output==(0 if lookup else 0xabcdef01),(name,hex(output))
        checks.append(dict(name=name,result=hex(expected),output_handle=hex(output),services=calls))
    out=ROOT/'artifacts/analysis/uvc-sd-fsys-guards-e0220';out.mkdir(parents=True,exist_ok=True)
    (out/'manifest.json').write_text(json.dumps(dict(status='offline_original_fsys_guards_passed',source_sha256=sha,checks=checks,limitations=['Original API guards execute; logging and rejecting drive lookup are explicit service doubles.', 'Globals/GOT/arguments are fixtures; no actual volume, initialization, file creation, writes, locks or flush durability proven.']),indent=2)+'\n')
    print(f'{len(checks)} original filesystem guard cases passed')


if __name__=='__main__':main()
