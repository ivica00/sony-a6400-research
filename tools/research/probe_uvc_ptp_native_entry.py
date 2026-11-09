"""Offline entry-hook/bypass controls; original VFS/native ioctl bodies."""
import argparse, hashlib, io, json, os, struct, subprocess
from pathlib import Path
from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE
from unicorn.arm_const import *
from tools.research.build_uvc_ptp_descriptor_candidate import ROOT, KERNEL, KERNEL_SHA


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output-dir',required=True,type=Path)
    out=p.parse_args().output_dir.resolve()
    if not out.is_relative_to(ROOT/'artifacts'):p.error('Output must be under artifacts')
    out.mkdir(parents=True,exist_ok=True)
    fixture=out/'entry-fixture.c'
    fixture.write_text('#include "uvc_ptp_ioctl_guard.h"\nextern long a6400_uvc_native_ioctl_tail(void*,unsigned int,unsigned long);\nstruct a6400_uvc_ioctl_guard entry_guard={.original=a6400_uvc_native_ioctl_tail};\nlong entry_wrapper(void*f,unsigned int c,unsigned long a){return a6400_uvc_guard_dispatch(&entry_guard,f,c,a);}\n')
    target=out/'entry-bridge.elf'
    command=['arm-linux-gnueabi-gcc','-marm','-march=armv7-a','-mfloat-abi=softfp','-ffreestanding','-fno-builtin','-fno-pic','-fno-pie','-fno-stack-protector','-nostdlib','-static','-O2','-Wall','-Wextra','-Werror',
             '-Itools/native_camera','-Wl,--build-id=none,-Ttext=0x5f800000,-e,entry_wrapper',
             fixture.relative_to(ROOT).as_posix(),'tools/native_camera/uvc_ptp_mode_gate.c','tools/native_camera/uvc_ptp_ioctl_guard.c','tools/native_camera/uvc_ptp_native_ioctl_entry.S','-o',target.relative_to(ROOT).as_posix()]
    if os.name=='nt':command=['wsl.exe','--cd','/mnt/'+ROOT.drive[0].lower()+ROOT.as_posix()[2:],'--exec',*command]
    subprocess.run(command,cwd=ROOT,check=True)
    raw=KERNEL.read_bytes();assert hashlib.sha256(raw).hexdigest()==KERNEL_SHA
    native,vfs,checkpoint=0x602b8844,0x601ce2b0,0x602b884c
    assert struct.unpack_from('<II',raw,native-0x60108000)==(0xe1a0c00d,0xe92dd8f0)
    image=ELFFile(io.BytesIO(target.read_bytes()))
    names={s.name:s['st_value'] for s in image.get_section_by_name('.symtab').iter_symbols()}
    cpu=Uc(UC_ARCH_ARM,UC_MODE_ARM);cpu.ctl_set_cpu_model(UC_CPU_ARM_CORTEX_A9);pages=set()
    def mapping(a,n):
        for page in range(a&~4095,(a+n+4095)&~4095,4096):
            if page not in pages:cpu.mem_map(page,4096);pages.add(page)
    mapping(0x60108000,len(raw));cpu.mem_write(0x60108000,raw)
    for segment in image.iter_segments():
        if segment['p_type']=='PT_LOAD':mapping(segment['p_vaddr'],segment['p_memsz']);cpu.mem_write(segment['p_vaddr'],segment.data())
    for a,n in [(0x200000,0x10000),(0x400000,0x10000),(0x500000,4096),(0x6051b000,4096)]:mapping(a,n)
    file,fops,gc,done=0x200100,0x200200,0x201000,0x500000
    def put(a,v):cpu.mem_write(a,struct.pack('<I',v&0xffffffff))
    def word(a):return struct.unpack('<I',cpu.mem_read(a,4))[0]
    put(file+0x10,fops);put(fops+0x20,native);put(0x6051b17c,gc);put(gc+0x68,4)
    state={};checks=[]
    executable=[(s['sh_addr'],s['sh_addr']+s['sh_size']) for s in image.iter_sections() if s['sh_flags']&4]
    def hook(c,a,size,unused):
        if a==done:state['returned']=True;c.emu_stop();return
        if a==checkpoint:
            state['body_entries']+=1
            if state.get('pause_prologue'):c.emu_stop();return
        if a==names['entry_wrapper']:
            state['wrappers']+=1
            assert state['wrappers']<=1,'Recursive original dispatch'
        if a==0x601ce2d8 and state.get('pause_vfs'):
            state['pause_vfs']=False;state['vfs_pc']=a;c.emu_stop();return
        if not any(lo<=a<hi for lo,hi in [*executable,(native,0x602b8ab0),(vfs,0x601ce328),(0x60259588,0x60259618)]):
            raise RuntimeError(f'Unexpected execution {a:08x}')
    cpu.hook_add(UC_HOOK_CODE,hook)
    regs=[UC_ARM_REG_R4,UC_ARM_REG_R5,UC_ARM_REG_R6,UC_ARM_REG_R7,UC_ARM_REG_R8,UC_ARM_REG_R9,UC_ARM_REG_R10,UC_ARM_REG_R11]
    def prepare(command):
        state.clear();state.update(returned=False,wrappers=0,body_entries=0)
        for index,reg in enumerate(regs):cpu.reg_write(reg,0x11110000+index)
        cpu.reg_write(UC_ARM_REG_R0,file);cpu.reg_write(UC_ARM_REG_R1,command);cpu.reg_write(UC_ARM_REG_R2,0)
        cpu.reg_write(UC_ARM_REG_SP,0x40f000);cpu.reg_write(UC_ARM_REG_LR,done)
    def run(a):cpu.emu_start(a,0xffffffff,count=10000)
    def check(name,value):
        assert value,name;checks.append(name)
    prepare(0x12345678);state['pause_prologue']=True;run(native)
    original_frame=bytes(cpu.mem_read(0x40efe0,32));original_ip=cpu.reg_read(UC_ARM_REG_R12)
    prepare(0x12345678);state['pause_prologue']=True;run(names['a6400_uvc_native_ioctl_tail'])
    check('exact-native-prologue-frame-including-saved-pc',bytes(cpu.mem_read(0x40efe0,32))==original_frame and cpu.reg_read(UC_ARM_REG_R12)==original_ip)
    delta=names['entry_wrapper']-(native+8);assert delta%4==0 and -(1<<25)<=delta<(1<<25)
    branch=0xea000000|((delta>>2)&0xffffff)
    for command,result in [(0x12345678,-25),(0x400ce203,-16)]:
        prepare(command);state['pause_vfs']=True;run(vfs)
        check('vfs-cached-original-target-'+hex(command),cpu.reg_read(UC_ARM_REG_R3)==native)
        put(native,branch);cpu.ctl_remove_cache(native,native+8)
        run(state['vfs_pc'])
        check('cached-target-enters-wrapper-'+hex(command),state['returned'] and state['wrappers']==1 and state['body_entries']==1)
        check('native-result-and-count-restored-'+hex(command),cpu.reg_read(UC_ARM_REG_R0)==(result&0xffffffff) and word(names['entry_guard'])==0)
        check('callee-saved-preserved-'+hex(command),all(cpu.reg_read(reg)==0x11110000+index for index,reg in enumerate(regs)))
        put(native,0xe1a0c00d);cpu.ctl_remove_cache(native,native+8)
    put(names['entry_guard'],0x80000000);put(native,branch);cpu.ctl_remove_cache(native,native+8)
    prepare(0x12345678);run(vfs)
    check('held-entry-rejects-before-native-body',state['returned'] and state['wrappers']==1 and state['body_entries']==0 and cpu.reg_read(UC_ARM_REG_R0)==0xfffffff0)
    put(names['entry_guard'],0);put(native,0xe1a0c00d);cpu.ctl_remove_cache(native,native+8)
    prepare(0x12345678);run(vfs)
    check('restored-entry-bypasses-wrapper',state['returned'] and state['wrappers']==0 and state['body_entries']==1 and cpu.reg_read(UC_ARM_REG_R0)==0xffffffe7)
    (out/'manifest.json').write_text(json.dumps(dict(status='offline_original_entry_bridge_passed',count=len(checks),checks=checks,kernel_sha256=KERNEL_SHA,
        limitations=['File/fops/gc and register objects are explicit fixtures; no camera access.',
                     'Unicorn cache invalidation is not physical SMP instruction publication.',
                     'Does not drain calls already past native entry or prove safe install/removal.']),indent=2)+'\n')
    print(f'{len(checks)} original entry/bypass controls passed; NOT installed')


if __name__=='__main__':main()
