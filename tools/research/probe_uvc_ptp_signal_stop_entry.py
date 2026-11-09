"""Original do_signal user-mode entry guard and direct ptrace-stop references."""
import argparse, hashlib, json, struct
from pathlib import Path
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC
from tools.research.build_uvc_ptp_descriptor_candidate import ROOT, KERNEL, KERNEL_SHA


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output-dir',required=True,type=Path)
    out=p.parse_args().output_dir.resolve()
    if not out.is_relative_to(ROOT/'artifacts'):p.error('Output must be under artifacts')
    raw=KERNEL.read_bytes();assert hashlib.sha256(raw).hexdigest()==KERNEL_SHA
    symbols=json.loads((ROOT/'artifacts/analysis/uvc-portability-final-e0135/a6400-kallsyms-checked.json').read_text())['symbols']
    names={s['name']:s['address'] for s in symbols}
    targets={names[n]:n for n in ('ptrace_stop','ptrace_notify')};xrefs=[]
    for a in range(names['_stext'],names['_etext'],4):
        word=struct.unpack_from('<I',raw,a-0x60108000)[0]
        if word&0x0e000000!=0x0a000000:continue
        offset=(word&0xffffff)*4
        if offset&0x2000000:offset-=0x4000000
        target=(a+8+offset)&0xffffffff
        if target in targets:xrefs.append(dict(address=hex(a),target=targets[target],instruction=hex(word)))
    c=Uc(UC_ARCH_ARM,UC_MODE_ARM)
    c.mem_map(0x60108000,(len(raw)+4095)&~4095);c.mem_write(0x60108000,raw)
    c.mem_map(0x100000,0x10000);c.mem_map(0x400000,0x10000)
    regs,task,info,done=0x100000,0x101000,0x102000,0x103000
    state={};checks=[]
    def put(a,v):c.mem_write(a,struct.pack('<I',v))
    def hook(cpu,a,size,unused):
        if a==0x601437d8:
            assert cpu.reg_read(UC_ARM_REG_R2)==regs
            state['signal_dispatch']=True;cpu.emu_stop()
        elif a==done:state['returned']=True;cpu.emu_stop()
        elif not (0x601102e8<=a<0x601103c4 or 0x60110844<=a<0x6011084c):
            raise RuntimeError(f'Unexpected execution {a:08x}')
    c.hook_add(UC_HOOK_CODE,hook)
    for cpsr,dispatch in [(0x10,True),(0x30,True),(0x13,False),(0x12,False)]:
        c.mem_write(regs,bytes(0x3000));put(regs+0x40,cpsr)
        put(0x40e00c,task);put(task+8,info);put(info,0);put(0x40e000,0)
        state.clear()
        c.reg_write(UC_ARM_REG_R0,regs);c.reg_write(UC_ARM_REG_R1,0)
        c.reg_write(UC_ARM_REG_SP,0x40f000);c.reg_write(UC_ARM_REG_LR,done)
        c.emu_start(0x601102e8,0xffffffff,count=200)
        assert bool(state.get('signal_dispatch'))==dispatch
        assert bool(state.get('returned'))!=dispatch
        checks.append(dict(saved_cpsr=hex(cpsr),signal_dispatch_reached=dispatch))
    out.mkdir(parents=True,exist_ok=True)
    (out/'manifest.json').write_text(json.dumps(dict(status='original_signal_entry_checks_passed',
        kernel_sha256=KERNEL_SHA,checks=checks,direct_branch_xrefs=xrefs,
        limitations=['Explicit register/current/task fixtures; syscall flag zero and task flags zero.',
                     'Stops before get_signal_to_deliver; no ptrace-stop origin or VFS retirement proof.',
                     'Direct aligned ARM B/BL scan only, not indirect-call or data/code classification proof.']),indent=2)+'\n')
    print(f'{len(checks)} original signal entry checks passed')


if __name__=='__main__':main()
