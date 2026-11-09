"""Original SMP callback acknowledgement ordering, with explicit CPU fixtures."""
import argparse, hashlib, json, struct
from pathlib import Path
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE
from unicorn.arm_const import *
from tools.research.build_uvc_ptp_descriptor_candidate import ROOT, KERNEL, KERNEL_SHA


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output-dir',required=True,type=Path)
    out=p.parse_args().output_dir.resolve()
    if not out.is_relative_to(ROOT/'artifacts'):p.error('Output must be under artifacts')
    raw=KERNEL.read_bytes();assert hashlib.sha256(raw).hexdigest()==KERNEL_SHA
    c=Uc(UC_ARCH_ARM,UC_MODE_ARM);c.ctl_set_cpu_model(UC_CPU_ARM_CORTEX_A9)
    c.mem_map(0x60108000,(len(raw)+4095)&~4095);c.mem_write(0x60108000,raw)
    c.mem_map(0x200000,0x10000);c.mem_map(0x400000,0x10000)
    obj,mask,context,callback,done=0x200000,0x203000,0x205000,0x206000,0x207000
    head=0x604be3a0;state={};events=[];checks=[]
    def put(a,v):c.mem_write(a,struct.pack('<I',v&0xffffffff))
    def word(a):return struct.unpack('<I',c.mem_read(a,4))[0]
    def check(name,value):
        assert value,name;checks.append(name)
    def ret(value=0):c.reg_write(UC_ARM_REG_R0,value);c.reg_write(UC_ARM_REG_PC,c.reg_read(UC_ARM_REG_LR))
    def hook(cpu,a,size,unused):
        if a==done:state['returned']=True;cpu.emu_stop();return
        if a==callback:
            assert cpu.reg_read(UC_ARM_REG_R0)==context
            events.append(['callback',word(0x40e014)])
            if state.get('local'):assert cpu.reg_read(UC_ARM_REG_CPSR)&0x80
            if state.get('pause_callback'):
                state['callback_context']=cpu.context_save();state['callback_return']=cpu.reg_read(UC_ARM_REG_LR)
                cpu.emu_stop();return
            ret();return
        if a in (0x603c6ed8,0x603c6cac):
            assert word(obj+0x14)==0 and word(obj+0x10)&1
            events.append('list-lock-double' if a==0x603c6ed8 else 'list-unlock-double');ret();return
        if a==0x60160e70:
            assert state.get('local')
            state['forwarded_wait']=cpu.reg_read(UC_ARM_REG_R3)
            assert cpu.reg_read(UC_ARM_REG_R1)==callback and cpu.reg_read(UC_ARM_REG_R2)==context
            events.append('remote-dispatch-double');ret();return
        if a==0x60160a9c:
            state['spins']=state.get('spins',0)+1
            if state['spins']==4:cpu.emu_stop();return
        if not any(lo<=a<hi for lo,hi in [(0x6016114c,0x601612c0),(0x60160e30,0x60160e6c),
                (0x60160a8c,0x60160aac),(0x60259588,0x602595d0),(0x6011326c,0x601133b0)]):
            raise RuntimeError(f'Unexpected execution {a:08x}')
    c.hook_add(UC_HOOK_CODE,hook)
    put(0x603c9cec,mask);put(mask,0xf)
    put(head,obj);put(head+4,obj);put(obj,head);put(obj+4,head)
    put(obj+8,callback);put(obj+0xc,context);put(obj+0x10,1);put(obj+0x14,2);put(obj+0x18,6)
    def prepare(cpu_number):
        put(0x40e014,cpu_number);put(0x40e004,0);put(0x40e000,0)
        c.reg_write(UC_ARM_REG_CPSR,0x13);c.reg_write(UC_ARM_REG_SP,0x40f000);c.reg_write(UC_ARM_REG_LR,done)
        state.clear();state['returned']=False
    def wait_blocked(name):
        saved=c.context_save();old=dict(state)
        state.clear();state['returned']=False
        c.reg_write(UC_ARM_REG_R0,obj+0x10);c.reg_write(UC_ARM_REG_SP,0x40b000);c.reg_write(UC_ARM_REG_LR,done)
        c.emu_start(0x60160a8c,0xffffffff,count=100)
        check(name,not state['returned'] and state.get('spins')==4)
        c.context_restore(saved);state.clear();state.update(old)
    wait_blocked('wait-blocked-before-any-callback')
    prepare(0);c.emu_start(0x6016114c,0xffffffff,count=1000)
    check('non-target-cpu-does-not-ack',state['returned'] and word(obj+0x14)==2 and word(obj+0x18)==6)
    prepare(1);c.emu_start(0x6016114c,0xffffffff,count=1000)
    check('first-cpu-return-not-full-completion',state['returned'] and word(obj+0x14)==1 and word(obj+0x18)==4 and word(obj+0x10)&1)
    wait_blocked('wait-still-blocked-after-first-cpu')
    prepare(2);state['pause_callback']=True;c.emu_start(0x6016114c,0xffffffff,count=1000)
    check('last-callback-in-progress-keeps-lock',not state['returned'] and word(obj+0x14)==1 and word(obj+0x10)&1)
    wait_blocked('wait-blocked-inside-last-callback')
    c.context_restore(state['callback_context']);c.reg_write(UC_ARM_REG_PC,state['callback_return'])
    state['pause_callback']=False;c.emu_start(state['callback_return'],0xffffffff,count=1000)
    check('last-callback-return-unlocks-and-unlinks',state['returned'] and word(obj+0x14)==0 and word(obj+0x18)==0 and word(obj+0x10)&1==0 and word(head)==head)
    prepare(0);c.reg_write(UC_ARM_REG_R0,obj+0x10);c.emu_start(0x60160a8c,0xffffffff,count=100)
    check('original-wait-returns-after-last-ack',state['returned'])
    put(0x604c9280,0)
    for wait in (0,1,2):
        prepare(0);state['local']=True
        c.reg_write(UC_ARM_REG_R0,callback);c.reg_write(UC_ARM_REG_R1,context);c.reg_write(UC_ARM_REG_R2,wait)
        c.emu_start(0x60113390,0xffffffff,count=1000)
        check('on-each-cpu-wait-forward-'+str(wait),state['returned'] and state['forwarded_wait']==int(bool(wait)) and not c.reg_read(UC_ARM_REG_CPSR)&0x80)
    out.mkdir(parents=True,exist_ok=True)
    (out/'manifest.json').write_text(json.dumps(dict(status='original_smp_completion_controls_passed',kernel_sha256=KERNEL_SHA,
        count=len(checks),checks=checks,events=events,limitations=[
        'Explicit CPU/request/list objects; callback and list locks are doubles.',
        'Remote-dispatch service is a recorder in on_each_cpu controls; separate interrupt bodies execute actual acknowledgement logic.',
        'No physical IPI/cache publication or proof that unrelated old ioctl callers retired.']),indent=2)+'\n')
    print(f'{len(checks)} original SMP completion controls passed')


if __name__=='__main__':main()
