"""Build monitor acknowledgement helper and execute its ARM admission policy."""
import argparse,hashlib,json,os,struct,subprocess
from elftools.elf.elffile import ELFFile
from unicorn import Uc,UC_ARCH_ARM,UC_MODE_ARM,UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_SP,UC_ARM_REG_LR
from tools.research.build_uvc_ptp_descriptor_candidate import ROOT


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output-dir',required=True)
    out=(ROOT/parser.parse_args().output_dir).resolve()
    if not out.is_relative_to(ROOT/'artifacts'):parser.error('Output must remain under artifacts')
    if (out/'manifest.json').exists():parser.error('Use a new artifact directory')
    out.mkdir(parents=True,exist_ok=True)
    source=ROOT/'tools/native_camera/native_monitor_output_ack.c';target=out/'native_monitor_output_ack.elf'
    rel=lambda p:p.relative_to(ROOT).as_posix()
    cmd=['arm-linux-gnueabi-gcc',*'-std=gnu11 -march=armv7-a -mfloat-abi=softfp -O2 -Wall -Wextra -Werror -nostdlib -U_FORTIFY_SOURCE -D_FORTIFY_SOURCE=0 -U_TIME_BITS -D_TIME_BITS=32 -U_FILE_OFFSET_BITS -D_FILE_OFFSET_BITS=32 -fno-stack-protector'.split(),'-Wl,-e,_start,-z,defs,-z,max-page-size=4096,--dynamic-linker=/lib/ld-linux.so.3','-o',rel(target),'tools/native_camera/snapshot_start.S',rel(source),'tools/sony_sysroot/lib/libc.so','-lgcc']
    if os.name=='nt':cmd=['wsl.exe','--cd','/mnt/'+ROOT.drive[0].lower()+ROOT.as_posix()[2:],'--exec',*cmd]
    subprocess.run(cmd,cwd=ROOT,check=True)
    c=Uc(UC_ARCH_ARM,UC_MODE_ARM)
    with target.open('rb') as f:
        e=ELFFile(f);pages=set()
        for s in e.iter_segments():
            if s['p_type']=='PT_LOAD' and s['p_memsz']:
                for a in range(s['p_vaddr']&~4095,(s['p_vaddr']+s['p_memsz']+4095)&~4095,4096):
                    if a not in pages:c.mem_map(a,4096);pages.add(a)
                c.mem_write(s['p_vaddr'],s.data())
        symbols={s.name:s['st_value'] for s in e.get_section_by_name('.symtab').iter_symbols()};entry=symbols['a6400_mon_ack_check']
    c.mem_map(0x200000,0x10000);c.mem_map(0x300000,4096)
    reached=[]
    def hook(cpu,a,size,unused):
        if a==0x300000:reached.append(1);cpu.emu_stop()
    c.hook_add(UC_HOOK_CODE,hook)
    cases=[('valid',[0,0,0,30115],0,30115,1),('empty',[0,0,9,9],9,9,1),('wrapped',[7,7,31000,5],31000,5,1),('input-pending',[0,1,0,9],0,9,0),('read-changed',[0,0,1,9],0,9,0),('write-changed',[0,0,0,10],0,9,0),('bad-input',[1024,1024,0,9],0,9,0),('bad-output',[0,0,0,31728],0,31728,0)]
    for name,h,r,w,expected in cases:
        reached.clear();c.mem_write(0x200000,struct.pack('<4I',*h))
        for reg,value in [(UC_ARM_REG_R0,0x200000),(UC_ARM_REG_R1,r),(UC_ARM_REG_R2,w),(UC_ARM_REG_SP,0x20f000),(UC_ARM_REG_LR,0x300000)]:c.reg_write(reg,value)
        c.emu_start(entry,0xffffffff,count=200);assert reached and c.reg_read(UC_ARM_REG_R0)==expected,name
    from unicorn.arm_const import UC_ARM_REG_R3
    pump_cases=[('partial-input',[1,10,5,9],5,9,10,1),('consumed-input',[10,10,9,9],9,9,10,1),('foreign-input',[1,11,5,9],5,9,10,0),('invalid-input-end',[1,10,5,9],5,9,1024,0),('changed-output',[1,10,6,9],5,9,10,0)]
    for name,h,r,w,end,expected in pump_cases:
        reached.clear();c.mem_write(0x200000,struct.pack('<4I',*h))
        for reg,value in [(UC_ARM_REG_R0,0x200000),(UC_ARM_REG_R1,r),(UC_ARM_REG_R2,w),(UC_ARM_REG_R3,end),(UC_ARM_REG_SP,0x20f000),(UC_ARM_REG_LR,0x300000)]:c.reg_write(reg,value)
        c.emu_start(symbols['a6400_mon_probe_ack_check'],0xffffffff,count=200);assert reached and c.reg_read(UC_ARM_REG_R0)==expected,name
    prefix_cases=[('appended',[0,0,5,12],5,9,0xffffffff,1),('wrapped-appended',[0,0,31720,8],31720,3,0xffffffff,1),('short-prefix',[0,0,5,8],5,9,0xffffffff,0),('consumer-moved',[0,0,6,12],5,9,0xffffffff,0),('foreign-input',[0,1,5,12],5,9,0xffffffff,0),('query-progress',[4,20,5,12],5,9,20,1),('query-foreign',[4,21,5,12],5,9,20,0),('invalid-prefix',[0,0,5,12],5,31728,0xffffffff,0)]
    for name,h,r,w,end,expected in prefix_cases:
        reached.clear();c.mem_write(0x200000,struct.pack('<4I',*h))
        for reg,value in [(UC_ARM_REG_R0,0x200000),(UC_ARM_REG_R1,r),(UC_ARM_REG_R2,w),(UC_ARM_REG_R3,end),(UC_ARM_REG_SP,0x20f000),(UC_ARM_REG_LR,0x300000)]:c.reg_write(reg,value)
        c.emu_start(symbols['a6400_mon_prefix_ack_check'],0xffffffff,count=1000);assert reached and c.reg_read(UC_ARM_REG_R0)==expected,name
    report={'status':'built_policy_passed_not_deployed','camera_access':False,'admission_cases':[x[0] for x in cases],'probe_pump_cases':[x[0] for x in pump_cases],'prefix_cases':[x[0] for x in prefix_cases],'limitations':['Compiled admission helpers execute; command publisher, mapping checks, pwrite, ownership, races and physical acknowledgement not executed by this audit.'],'files':{rel(p):{'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in [source,target,ROOT/'tools/native_camera/snapshot_start.S',ROOT/'tools/sony_sysroot/lib/libc.so']}}
    (out/'manifest.json').write_text(json.dumps(report,indent=2)+'\n');print('Built helper; twenty-one compiled ARM admission cases pass')


if __name__=='__main__':main()
