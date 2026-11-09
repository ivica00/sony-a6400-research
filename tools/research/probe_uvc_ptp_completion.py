"""Original UsbIfWrapper completion/wait bodies; OSAL services are doubles."""
import argparse, hashlib, io, json, struct
from pathlib import Path
from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE, UC_HOOK_MEM_WRITE
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC
from tools.research.arm_plt import resolve_arm_plt
from tools.research.build_uvc_ptp_descriptor_candidate import ROOT


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output-dir',type=Path,required=True)
    out=p.parse_args().output_dir.resolve()
    if not out.is_relative_to(ROOT/'artifacts'):p.error('Output must be under artifacts')
    source=ROOT/'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/lib/libUsbControl.so'
    raw=source.read_bytes();sha='70cd5742fde9eea78c60905e4015531b4c3ab2668d2cb85c934531f451f1211f'
    assert hashlib.sha256(raw).hexdigest()==sha
    elf=ELFFile(io.BytesIO(raw));plt=resolve_arm_plt(elf);checks=[]
    def check(n,v):
        if not v:raise AssertionError(n)
        checks.append(n)
    for a,n in {0x9fac:'osal_dynamic_id',0x9904:'osal_rcv_msg_tmo',0x9a10:'osal_valloc_msg_wait',
        0x9af4:'osal_snd_msg',0xa2f8:'osal_free_msg',0xa1ac:'_ZN12UsbIfWrapper6doStopEii'}.items():
        check('plt-'+hex(a),plt[a]['name']==n)
    cpu=Uc(UC_ARCH_ARM,UC_MODE_ARM);cpu.mem_map(0,0x20000)
    for seg in elf.iter_segments():
        if seg['p_type']=='PT_LOAD':cpu.mem_write(seg['p_vaddr'],seg.data())
    cpu.mem_map(0x200000,0x10000);cpu.mem_map(0x300000,4096);cpu.mem_map(0x400000,0x10000)
    done,msg=0x300000,0x200000;events=[];state=dict(next_q=0x111,pause=False,recv_error=0,alloc_error=0,stop_error=0)
    def word(a):return struct.unpack('<I',cpu.mem_read(a,4))[0]
    def put(a,v):cpu.mem_write(a,struct.pack('<I',v&0xffffffff))
    def ret(v=0):cpu.reg_write(UC_ARM_REG_R0,v&0xffffffff);cpu.reg_write(UC_ARM_REG_PC,cpu.reg_read(UC_ARM_REG_LR))
    def hook(c,a,size,_):
        r=[c.reg_read(x) for x in (UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3)]
        if a==done:c.emu_stop();return
        if a==0x9fac:
            if r[0]==0x29:
                assert r[1]==0xca;state['cell']=r[2];put(r[2],state['next_q']);events.append(['create',state['next_q']])
            else:assert r[0]==0x49;events.append(['destroy',r[2]])
            ret();return
        if a==0xa1ac:
            events.append(['stop-double',word(state['cell'])])
            if state['pause']:c.emu_stop()
            else:ret(state['stop_error'])
            return
        if a==0x9904:
            assert r[2]==0xffffffff;events.append(['receive',r[0]])
            if not state['recv_error']:put(r[1],msg)
            ret(state['recv_error']);return
        if a==0xa2f8:events.append(['free',r[0],r[1]]);ret();return
        if a==0x9a10:
            assert r[2:]==[4,1];events.append(['allocate',r[0]])
            if not state['alloc_error']:put(r[1],msg)
            ret(state['alloc_error']);return
        if a==0x9af4:events.append(['send',r[0],word(r[1])]);ret();return
        if not any(x<=a<y for x,y in [(0x13340,0x133e4),(0x12de4,0x12e44)]):raise RuntimeError(f'Unexpected execution {a:08x}')
    def guard(c,access,a,size,value,_):
        if not any(x<=a and a+size<=y for x,y in [(0x1ea00,0x1ec00),(msg,msg+4),(0x400000,0x410000)]):raise RuntimeError(f'Unexpected write {a:08x}')
    cpu.hook_add(UC_HOOK_CODE,hook);cpu.hook_add(UC_HOOK_MEM_WRITE,guard)
    def call(a,*values,stack=0x40f000):
        for r,v in zip((UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3),values):cpu.reg_write(r,v)
        cpu.reg_write(UC_ARM_REG_SP,stack);cpu.reg_write(UC_ARM_REG_LR,done)
        cpu.emu_start(a|1,0xffffffff,count=10000);return cpu.reg_read(UC_ARM_REG_R0)
    put(msg,-5)
    check('normal-wait-returns-response',call(0x13341,0x201000,1,13,3)==0xfffffffb)
    check('normal-service-order',events==[['create',0x111],['stop-double',0x111],['receive',0x111],['free',0x111,msg],['destroy',0x111]])
    check('normal-clears-global-queue',word(state['cell'])==0)
    events.clear();state['next_q']=0x222;state['recv_error']=7
    check('receive-error-returned',call(0x13341,0x201000,1,13,3)==7)
    check('receive-error-destroys-without-free',events==[['create',0x222],['stop-double',0x222],['receive',0x222],['destroy',0x222]])
    check('receive-error-clears-global',word(state['cell'])==0)
    events.clear();state.update(recv_error=0,stop_error=6,next_q=0x234)
    check('immediate-stop-error-returned',call(0x13341,0x201000,1,13,3)==6)
    check('immediate-error-does-not-wait',events==[['create',0x234],['stop-double',0x234],['destroy',0x234]])
    check('immediate-error-clears-global',word(state['cell'])==0)
    events.clear();call(0x12de5,0x10001,0,19)
    check('late-completion-has-no-zero-queue-guard',events==[['allocate',0],['send',0,19]])
    events.clear();put(state['cell'],0x333)
    call(0x12de5,0x10001,0,0xfffffffb)
    check('stop-completion-sends-status',events==[['allocate',0x333],['send',0x333,0xfffffffb]])
    events.clear();call(0x12de5,0x12345,0,9)
    check('unknown-completion-ignored',not events)
    state['alloc_error']=8;call(0x12de5,0x10001,0,9)
    check('allocation-error-does-not-send',events==[['allocate',0x333]])
    # Explicit two-stack interleaving; no claim that native callers schedule it.
    state.update(pause=True,next_q=0x444,alloc_error=0,stop_error=0);events.clear()
    call(0x13341,0x201000,1,13,3)
    check('first-call-paused-before-stop',cpu.reg_read(UC_ARM_REG_PC)==0xa1ac)
    state['next_q']=0x555
    call(0x13341,0x201000,1,13,3,stack=0x40d000)
    check('second-call-overwrites-shared-queue',word(state['cell'])==0x555)
    events.clear();call(0x12de5,0x10001,0,17,stack=0x40b000)
    check('completion-uses-current-global-queue',events==[['allocate',0x555],['send',0x555,17]])
    report=dict(status='original_completion_boundaries_passed',count=len(checks),checks=checks,
        queue_cell=hex(state['cell']),library_sha256=sha,probe_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        camera_access=False,limitations=['OSAL allocation/queue/wait/free and doStop are explicit service doubles.',
            'Original callback and synchronous wait control flow execute; no physical stop or scheduler executes.',
            'Two-stack interleaving is explicit fixture evidence, not an observed camera race.',
            'Start-completion cleanup and external caller exclusion remain unproven.'])
    out.mkdir(parents=True,exist_ok=True);(out/'manifest.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))


if __name__=='__main__':main()
