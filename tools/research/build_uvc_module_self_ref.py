"""Test MOD inline self-get against the original native module_put body."""
import argparse,hashlib,io,json,os,struct,subprocess
from pathlib import Path
from elftools.elf.elffile import ELFFile
from unicorn import Uc,UC_ARCH_ARM,UC_MODE_ARM,UC_HOOK_CODE,UC_HOOK_MEM_WRITE
from unicorn.arm_const import UC_ARM_REG_R0,UC_ARM_REG_SP,UC_ARM_REG_LR,UC_ARM_REG_PC
from tools.research.build_uvc_ptp_descriptor_candidate import ROOT,KERNEL,KERNEL_SHA
from tools.research.kernel_export_contract import kernel_exports


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output-dir',required=True,type=Path)
    out=p.parse_args().output_dir.resolve()
    if not out.is_relative_to(ROOT/'artifacts'):p.error('Output must be under artifacts')
    out.mkdir(parents=True,exist_ok=True);source=ROOT/'tools/native_camera/uvc_module_self_ref.c';obj=out/'self-ref.o';target=out/'self-ref.elf'
    exports=kernel_exports();needed=['__per_cpu_offset','nr_cpu_ids','module_put','preempt_schedule']
    assert all(exports[n]['kind']=='normal' for n in needed)
    def run(cmd):
        if os.name=='nt':cmd=['wsl.exe','--cd','/mnt/'+ROOT.drive[0].lower()+ROOT.as_posix()[2:],'--exec',*cmd]
        subprocess.run(cmd,cwd=ROOT,check=True)
    rel=lambda p:p.relative_to(ROOT).as_posix()
    run(['arm-linux-gnueabi-gcc','-marm','-march=armv7-a','-mfloat-abi=softfp','-O2','-ffreestanding','-fno-builtin','-fno-pic','-fno-pie','-fno-stack-protector','-Wall','-Wextra','-Werror','-c',rel(source),'-o',rel(obj)])
    run(['arm-linux-gnueabi-ld','--no-undefined','-Ttext=0x5f800000','-e','a6400_module_self_get','-o',rel(target),rel(obj),
        '--defsym=__this_module=0x200000',*['--defsym='+n+'='+exports[n]['address'] for n in needed]])
    raw=target.read_bytes();elf=ELFFile(io.BytesIO(raw));symbols={s.name:s['st_value'] for s in elf.get_section_by_name('.symtab').iter_symbols()}
    cpu=Uc(UC_ARCH_ARM,UC_MODE_ARM);cpu.mem_map(0x5f7f0000,0x20000)
    for s in elf.iter_segments():
        if s['p_type']=='PT_LOAD':cpu.mem_write(s['p_vaddr'],s.data())
    kernel=KERNEL.read_bytes();assert hashlib.sha256(kernel).hexdigest()==KERNEL_SHA
    cpu.mem_map(0x60108000,(len(kernel)+4095)&~4095);cpu.mem_write(0x60108000,kernel)
    cpu.mem_map(0x200000,0x2000);cpu.mem_map(0x400000,0x10000);cpu.mem_map(0x500000,4096)
    mod,refs,ti=0x200000,0x201000,0x40e000;percpu=int(exports['__per_cpu_offset']['address'],16);nr=int(exports['nr_cpu_ids']['address'],16)
    checks=[];events=[]
    def put(a,n):cpu.mem_write(a,struct.pack('<I',n&0xffffffff))
    def word(a):return struct.unpack('<I',cpu.mem_read(a,4))[0]
    def check(n,v):
        if not v:raise AssertionError(n)
        checks.append(n)
    def hook(c,a,size,_):
        if a==0x500000:c.emu_stop();return
        if a==int(exports['preempt_schedule']['address'],16):
            events.append(word(ti+4));c.reg_write(UC_ARM_REG_PC,c.reg_read(UC_ARM_REG_LR));return
        if not (0x5f800000<=a<0x5f801000 or 0x601629f4<=a<0x60162a78):raise RuntimeError('Unexpected execution '+hex(a))
    def guard(c,access,a,size,v,_):
        if not (refs<=a and a+size<=refs+32 or 0x400000<=a and a+size<=0x410000):raise RuntimeError('Unexpected write '+hex(a))
    cpu.hook_add(UC_HOOK_CODE,hook);cpu.hook_add(UC_HOOK_MEM_WRITE,guard)
    def reset(state=0,cpu_id=0):
        cpu.mem_write(mod,bytes(0x200));cpu.mem_write(refs,bytes(32));put(mod,state);put(mod+0x138,refs)
        put(nr,2);put(percpu,0);put(percpu+4,16);put(ti,0);put(ti+4,0);put(ti+0x14,cpu_id);events.clear()
    def call(name):
        cpu.reg_write(UC_ARM_REG_SP,0x40f000);cpu.reg_write(UC_ARM_REG_LR,0x500000)
        cpu.emu_start(symbols['a6400_module_self_'+name],0xffffffff,count=10000);assert cpu.reg_read(UC_ARM_REG_PC)==0x500000
        return cpu.reg_read(UC_ARM_REG_R0)
    reset();check('get-live-cpu0',call('get')==0 and word(refs)==1 and word(ti+4)==0)
    call('put');check('original-put-balances-cpu0',word(refs+4)==1 and word(ti+4)==0)
    reset(cpu_id=1);check('get-live-cpu1',call('get')==0 and word(refs+16)==1 and word(refs)==0)
    call('put');check('original-put-balances-cpu1',word(refs+20)==1 and word(ti+4)==0)
    reset();check('cross-cpu-get',call('get')==0);put(ti+0x14,1);call('put')
    check('original-cross-cpu-put-balance',word(refs)==1 and word(refs+20)==1)
    for state in (1,2):
        reset(state);check('reject-module-state-'+str(state),call('get')==0xfffffff0 and word(refs)==0 and word(ti+4)==0)
    reset(cpu_id=2);check('reject-out-of-range-cpu',call('get')==0xffffffea and word(ti+4)==0)
    reset();put(mod+0x138,0);check('reject-null-ref-storage',call('get')==0xffffffea and word(ti+4)==0)
    reset();put(refs,0xffffffff);check('reject-reference-overflow',call('get')==0xffffffb5 and word(refs)==0xffffffff and word(ti+4)==0)
    reset();put(ti+4,0xffffffff);check('reject-preempt-overflow',call('get')==0xffffffb5 and word(ti+4)==0xffffffff)
    reset();put(ti+4,3);check('nested-preempt-count-restored',call('get')==0 and word(ti+4)==3)
    reset();put(ti,2);check('reschedule-after-get-restores-count',call('get')==0 and events==[0]);call('put')
    check('original-put-reschedule-after-count-restored',events==[0,0])
    check('all-imports-normal-export',all(exports[n]['kind']=='normal' for n in needed))
    check('legacy-symbol-get-is-gpl-only',exports['__symbol_get']['kind']=='gpl')
    report=dict(status='offline_module_reference_abi_passed',count=len(checks),checks=checks,exports={n:exports[n] for n in needed},kernel_sha256=KERNEL_SHA,
        files={rel(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in [source,source.with_suffix('.h'),target]},camera_access=False,
        limitations=['Module/thread-info/per-CPU state is explicit fixture data; current file-operation ownership is a caller precondition.',
            'Original module_put executes; preempt_schedule is an explicit recorder, not a scheduler proof.',
            'No module load, callback drain or USB activation performed by this test.'])
    (out/'manifest.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))


if __name__=='__main__':main()
