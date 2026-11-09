"""Build and execute MOD mode admission code; native interception not installed."""
import argparse,hashlib,io,json,os,struct,subprocess
from pathlib import Path
from elftools.elf.elffile import ELFFile
from unicorn import Uc,UC_ARCH_ARM,UC_MODE_ARM,UC_HOOK_MEM_WRITE,UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3,UC_ARM_REG_SP,UC_ARM_REG_LR,UC_ARM_REG_PC
from tools.research.build_uvc_ptp_descriptor_candidate import ROOT,KERNEL,KERNEL_SHA


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output-dir',type=Path,required=True)
    p.add_argument('--ioctl-guard',action='store_true',help='Also build the MOD wrapper and execute original native ioctl bodies')
    args=p.parse_args();out=args.output_dir.resolve()
    if not out.is_relative_to(ROOT/'artifacts'):p.error('Output must be under artifacts')
    out.mkdir(parents=True,exist_ok=True);target=out/'mode-gate.elf'
    source=ROOT/'tools/native_camera/uvc_ptp_mode_gate.c';header=source.with_suffix('.h')
    command=['arm-linux-gnueabi-gcc','-marm','-march=armv7-a','-mfloat-abi=softfp','-ffreestanding',
        '-fno-builtin','-fno-pic','-fno-pie','-fno-stack-protector','-nostdlib','-static','-O2',
        '-Wall','-Wextra','-Werror','-Wl,--build-id=none,-Ttext=0x10000,-e,a6400_uvc_mode_claim',
        '-o',target.relative_to(ROOT).as_posix(),source.relative_to(ROOT).as_posix()]
    extra=ROOT/'tools/native_camera/uvc_ptp_ioctl_guard.c'
    if args.ioctl_guard:command.append(extra.relative_to(ROOT).as_posix())
    if os.name=='nt':command=['wsl.exe','--cd','/mnt/'+ROOT.drive[0].lower()+ROOT.as_posix()[2:],'--exec',*command]
    subprocess.run(command,cwd=ROOT,check=True)
    raw=target.read_bytes();elf=ELFFile(io.BytesIO(raw));symbols=elf.get_section_by_name('.symtab')
    assert not [s.name for s in symbols.iter_symbols() if s.name and s['st_shndx']=='SHN_UNDEF']
    names={s.name:s['st_value'] for s in symbols.iter_symbols() if s['st_value']}
    cpu=Uc(UC_ARCH_ARM,UC_MODE_ARM);cpu.mem_map(0,0x20000)
    for seg in elf.iter_segments():
        if seg['p_type']=='PT_LOAD':cpu.mem_write(seg['p_vaddr'],seg.data())
    cpu.mem_map(0x200000,4096);cpu.mem_map(0x400000,0x10000);gate=0x200000;checks=[]
    def guard(c,access,a,size,value,_):
        if not (gate<=a and a+size<=gate+(0x10c if args.ioctl_guard else 4) or
                args.ioctl_guard and 0x205000<=a and a+size<=0x205100 or
                0x400000<=a and a+size<=0x410000):raise RuntimeError('Unexpected write '+hex(a))
    cpu.hook_add(UC_HOOK_MEM_WRITE,guard)
    def call(name,pointer=gate):
        cpu.reg_write(UC_ARM_REG_R0,pointer);cpu.reg_write(UC_ARM_REG_SP,0x40f000);cpu.reg_write(UC_ARM_REG_LR,0x18000)
        cpu.emu_start(names['a6400_uvc_mode_'+name],0x18000,count=10000)
        assert cpu.reg_read(UC_ARM_REG_PC)==0x18000
        return cpu.reg_read(UC_ARM_REG_R0)
    def word():return struct.unpack('<I',cpu.mem_read(gate,4))[0]
    def check(n,v):
        if not v:raise AssertionError(n)
        checks.append(n)
    kernel=KERNEL.read_bytes();assert hashlib.sha256(kernel).hexdigest()==KERNEL_SHA
    kw=lambda address:struct.unpack_from('<I',kernel,address-0x60108000)[0]
    check('native-cdev-init-loads-fops-argument',kw(0x604a590c)==0xe59f107c)
    check('native-cdev-init-target',kw(0x604a5910)&0xff000000==0xeb000000 and
        (0x604a5918+(((kw(0x604a5910)&0xffffff)^0x800000)-0x800000)*4)&0xffffffff==0x601c241c)
    check('native-fops-address',kw(0x604a5990)==0x604e5078)
    check('native-fops-ioctl-entry',kw(0x604e5098)==0x602b8844)
    check('native-fops-open-entry',kw(0x604e50a4)==0x602b8814)
    check('native-fops-release-entry',kw(0x604e50ac)==0x602b8284)
    for name in ('enter','leave','claim','release'):check('null-'+name,call(name,0)==0xffffffea)
    check('idle-leave-rejected',call('leave')==0xffffffea and word()==0)
    check('idle-release-rejected',call('release')==0xffffffea and word()==0)
    check('native-enter-one',call('enter')==0 and word()==1)
    check('native-enter-two',call('enter')==0 and word()==2)
    check('mod-claim-blocked-by-native',call('claim')==0xfffffff0 and word()==2)
    check('native-leave-one',call('leave')==0 and word()==1)
    check('release-cannot-clear-native-count',call('release')==0xffffffea and word()==1)
    check('native-leave-two',call('leave')==0 and word()==0)
    check('mod-claim-idle',call('claim')==0 and word()==0x80000000)
    check('native-blocked-during-mod',call('enter')==0xfffffff0 and word()==0x80000000)
    check('nested-mod-claim-rejected',call('claim')==0xfffffff0 and word()==0x80000000)
    check('native-leave-cannot-clear-mod',call('leave')==0xffffffea and word()==0x80000000)
    check('mod-release',call('release')==0 and word()==0)
    check('double-release-rejected',call('release')==0xffffffea and word()==0)
    cpu.mem_write(gate,struct.pack('<I',0x7fffffff))
    check('count-overflow-rejected',call('enter')==0xfffffff0 and word()==0x7fffffff)
    check('max-count-leave',call('leave')==0 and word()==0x7ffffffe)
    cpu.mem_write(gate,struct.pack('<I',0x80000001))
    check('invalid-held-count-enter-rejected',call('enter')==0xfffffff0 and word()==0x80000001)
    check('invalid-held-count-release-rejected',call('release')==0xffffffea and word()==0x80000001)
    if args.ioctl_guard:
        native=0x602b8844;g=gate+0x100;gc=0x205000;events=[];state=dict(pause=False,corrupt=False)
        cpu.mem_map(0x60108000,(len(kernel)+4095)&~4095);cpu.mem_write(0x60108000,kernel)
        cpu.mem_map(0x6051b000,4096);cpu.mem_map(gc,4096)
        def put(a,v):cpu.mem_write(a,struct.pack('<I',v&0xffffffff))
        def read(a):return struct.unpack('<I',cpu.mem_read(a,4))[0]
        put(0x6051b17c,gc);put(gc+0x68,4);put(g,0);put(g+4,native);put(g+8,0)
        executable=[(s['sh_addr'],s['sh_addr']+s['sh_size']) for s in elf.iter_sections() if s['sh_flags']&4]
        def observe(c,a,size,_):
            if a==native:
                assert read(g)==1;events.append('original-native-entry')
                if state['corrupt']:put(g,0)
                if state['pause']:state['saved']=c.context_save();c.emu_stop()
            if not any(x<=a<y for x,y in [*executable,(native,0x602b8ab0),(0x60259588,0x60259618)]):
                raise RuntimeError('Unexpected execution '+hex(a))
        cpu.hook_add(UC_HOOK_CODE,observe)
        def guard_call(name,command=0x12345678,pointer=g,stack=0x40f000):
            for r,v in zip((UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3),(pointer,0,command,0)):cpu.reg_write(r,v)
            cpu.reg_write(UC_ARM_REG_SP,stack);cpu.reg_write(UC_ARM_REG_LR,0x18000)
            cpu.emu_start(names['a6400_uvc_guard_'+name],0x18000,count=10000)
            return cpu.reg_read(UC_ARM_REG_R0)
        check('guard-preserves-native-unknown-command-result',guard_call('dispatch')==0xffffffe7 and read(g)==0)
        check('guard-preserves-native-active-commit-busy',guard_call('dispatch',0x400ce203)==0xfffffff0 and read(g)==0 and read(gc+0x68)==4)
        check('guard-claim-idle',guard_call('claim')==0)
        before=len(events)
        check('guard-held-rejects-before-original',guard_call('dispatch')==0xfffffff0 and len(events)==before)
        check('guard-release',guard_call('release')==0)
        state['pause']=True;guard_call('dispatch');saved=state['saved'];state['pause']=False
        check('guard-admission-held-across-original',read(g)==1)
        check('guard-claim-rejected-during-original',guard_call('claim',stack=0x40d000)==0xfffffff0)
        cpu.context_restore(saved);cpu.emu_start(native,0x18000,count=10000)
        check('guard-native-return-releases-admission',cpu.reg_read(UC_ARM_REG_R0)==0xffffffe7 and read(g)==0)
        state['corrupt']=True
        check('guard-latches-leave-failure',guard_call('dispatch')==0xffffffea and read(g+8)==0xffffffea)
        state['corrupt']=False;before=len(events)
        check('guard-fault-blocks-native',guard_call('dispatch')==0xffffffea and len(events)==before)
        check('guard-fault-blocks-claim',guard_call('claim')==0xffffffea)
        check('guard-fault-blocks-release',guard_call('release')==0xffffffea)
        check('guard-null-rejected',guard_call('dispatch',pointer=0)==0xffffffea)
        put(g+8,0);put(g+4,0)
        check('guard-null-original-rejected',guard_call('dispatch')==0xffffffea)
    inputs=[source,header,target]+([extra,extra.with_suffix('.h')] if args.ioctl_guard else [])
    report=dict(status='offline_mod_ioctl_guard_passed' if args.ioctl_guard else 'offline_mod_gate_passed',count=len(checks),checks=checks,
        files={str(f.relative_to(ROOT)):hashlib.sha256(f.read_bytes()).hexdigest() for f in inputs},
        build_command=command,camera_access=False,integrated=False,kernel_sha256=KERNEL_SHA,
        native_ioctl_slot='0x604e5098',native_original_ioctl='0x602b8844',ioctl_guard=args.ioctl_guard,
        limitations=['MOD code only; no native file_operations pointer changed.',
            'Sequential ARM atomic executions, not a multicore scheduling proof.',
            'With ioctl-guard, selected original Sony ioctl/atomic bodies execute; selected cases invoke no hardware services.',
            'All native entries must be routed through the gate; current enumeration module is unchanged.',
            'Hook publication/lifetime and native callback drain remain separate blockers.'])
    (out/'manifest.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))


if __name__=='__main__':main()
