"""Original UsbControl entry/Main/ProcessMsg with explicit message services."""
import argparse,hashlib,io,json,struct
from pathlib import Path
from elftools.elf.elffile import ELFFile
from unicorn import Uc,UC_ARCH_ARM,UC_MODE_ARM,UC_HOOK_CODE,UC_HOOK_MEM_WRITE
from unicorn.arm_const import UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3,UC_ARM_REG_SP,UC_ARM_REG_LR,UC_ARM_REG_PC
from tools.research.arm_plt import resolve_arm_plt
from tools.research.build_uvc_ptp_descriptor_candidate import ROOT


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output-dir',required=True,type=Path)
    out=p.parse_args().output_dir.resolve()
    if not out.is_relative_to(ROOT/'artifacts'):p.error('Output must be under artifacts')
    source=ROOT/'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/lib/libUsbControl.so'
    raw=source.read_bytes();sha='70cd5742fde9eea78c60905e4015531b4c3ab2668d2cb85c934531f451f1211f';assert hashlib.sha256(raw).hexdigest()==sha
    elf=ELFFile(io.BytesIO(raw));plt=resolve_arm_plt(elf);cpu=Uc(UC_ARCH_ARM,UC_MODE_ARM)
    cpu.mem_map(0,0x20000)
    for seg in elf.iter_segments():
        if seg['p_type']=='PT_LOAD':cpu.mem_write(seg['p_vaddr'],seg.data())
    cpu.mem_map(0x200000,0x10000);cpu.mem_map(0x300000,4096);cpu.mem_map(0x400000,0x10000)
    obj,wrapper,msg,done=0x200000,0x201000,0x202000,0x300000
    checks=[];events=[];state=dict(index=0,registration=False)
    def check(n,v):
        if not v:raise AssertionError(n)
        checks.append(n)
    expected={0x979c:'_ZN10UsbControl4MainEv',0x9808:'_ZN3UFW9MsgSender7SendEvtEPN3MWF6ObjMsgE',
        0x98dc:'_ZN12UsbIfWrapper12doInitializeEv',0x9830:'_ZN10UsbControl10ProcessMsgEjPN3MWF6ObjMsgE',
        0x991c:'osal_reg_msg_queue_cb'}
    for a,n in expected.items():check('plt-'+hex(a),plt[a]['name']==n)
    check('thumb-tail-veneer',plt[0x979c]['arm_stub']==0x97a0)
    def put(a,v):cpu.mem_write(a,struct.pack('<I',v&0xffffffff))
    def ret(v=0):cpu.reg_write(UC_ARM_REG_R0,v&0xffffffff);cpu.reg_write(UC_ARM_REG_PC,cpu.reg_read(UC_ARM_REG_LR))
    def hook(c,a,size,_):
        r=[c.reg_read(x) for x in (UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3)]
        if a==done:c.emu_stop();return
        if a==0x13054:state['forwarded_completion']=r[:2];c.emu_stop();return
        if a==0x9808:state['event_send_args']=r[:2];c.emu_stop();return
        if state['registration'] and a==0x131d8:c.emu_stop();return
        if a==0x991c:state['registration_args']=r;ret();return
        if a==0x97e0:check('entry-passes-object-to-init',r[0]==obj);events.append('init-double');ret();return
        if a==0x979c:check('entry-passes-object-to-main',r[0]==obj);c.reg_write(UC_ARM_REG_PC,0x112c5);return
        if a==0xa2e8:
            assert r[0]==obj+0x70;state['index']+=1;n=state['index'];assert n<=3
            put(r[1],0xca);put(r[2],msg);events.append('receive-'+str(n));ret();return
        if a==0x9830:
            assert r[:3]==[obj,0xca,msg];c.reg_write(UC_ARM_REG_PC,0x10ed5);return
        if a==0x9dc4:assert r[0]==msg;ret(0x6103);return
        if a==0xa0e0:assert r[0]==msg;ret(0xa2000 if state['index']<3 else 0xffff0000);return
        if a==0x9a90:assert r[:3]==[obj,msg,0xca];events.append('target-'+str(state['index']));ret();return
        if a==0x94d0:assert r[:2]==[obj,msg];events.append('dispatch-double-'+str(state['index']));ret();return
        if a in (0x9f58,0x9508):
            assert r[0]==msg;events.append(('destruct-' if a==0x9f58 else 'delete-')+str(state['index']));ret();return
        if not any(x<=a<y for x,y in [(0x10174,0x10188),(0x112c4,0x11316),(0x10ed4,0x11294),
                                     (0x131c0,0x131d8),(0x131a4,0x131bc),(0x12d28,0x12d36)]):
            raise RuntimeError(f'Unexpected execution {a:08x}')
    def guard(c,access,a,size,value,_):
        if not (0x400000<=a and a+size<=0x410000):raise RuntimeError(f'Unexpected write {a:08x}')
    cpu.hook_add(UC_HOOK_CODE,hook);cpu.hook_add(UC_HOOK_MEM_WRITE,guard)
    def call(a,value):
        cpu.reg_write(UC_ARM_REG_R0,value);cpu.reg_write(UC_ARM_REG_SP,0x40f000);cpu.reg_write(UC_ARM_REG_LR,done)
        cpu.emu_start(a|1,0xffffffff,count=30000)
    call(0x10175,obj)
    check('main-returns-on-exit-message',cpu.reg_read(UC_ARM_REG_PC)==done)
    expected_events=['init-double']
    for n in (1,2):expected_events += [f'receive-{n}',f'target-{n}',f'dispatch-double-{n}',f'destruct-{n}',f'delete-{n}']
    expected_events += ['receive-3','destruct-3','delete-3']
    check('main-processes-before-next-receive',events==expected_events)
    check('main-three-receives',state['index']==3)
    # Original registration prefix captures callback ABI, stopping before init.
    state['registration']=True;call(0x131c1,wrapper)
    args=state['registration_args']
    check('registration-passes-wrapper-member',args[1]==wrapper+0x20)
    check('registration-original-callback',args[2]==0x131a5 and args[3]==0)
    check('registration-stops-before-initialization',cpu.reg_read(UC_ARM_REG_PC)==0x131d8)
    put(msg,1);put(msg+4,0xfffffffb)
    call(0x131a5,msg)
    check('registered-callback-forwards-operation-status',state['forwarded_completion']==[1,0xfffffffb])
    check('registered-callback-stops-before-object-message-builder',cpu.reg_read(UC_ARM_REG_PC)==0x13054)
    cpu.reg_write(UC_ARM_REG_R1,msg)
    call(0x12d29,wrapper)
    check('event-listener-uses-msg-sender-member',state['event_send_args']==[wrapper+8,msg])
    check('event-listener-stops-before-send-service',cpu.reg_read(UC_ARM_REG_PC)==0x9808)
    report=dict(status='original_worker_boundaries_passed',count=len(checks),checks=checks,events=events,
        registration_args=[hex(x) for x in args],library_sha256=sha,
        probe_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),camera_access=False,
        limitations=['Message receive/getters, target/dispatch, destructor/delete and Init are explicit doubles.',
            'Original Main and ProcessMsg control flow execute; FSM and scheduling are not executed.',
            'Registration stops before service initialization; OSAL callback threading is not proven.',
            'Registered callback stops before ObjMsg builder; EventListner stops before MsgSender service.',
            'One loop is sequential; uniqueness of workers and external API exclusion remain unproven.'])
    out.mkdir(parents=True,exist_ok=True);(out/'manifest.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))


if __name__=='__main__':main()
