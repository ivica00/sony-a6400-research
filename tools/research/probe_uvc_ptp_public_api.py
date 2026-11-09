"""Execute original USB API table initialization and stop chain offline."""
import argparse
import hashlib
import io
import json
import struct
from pathlib import Path
from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE, UC_HOOK_MEM_WRITE
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC
from tools.research.arm_plt import resolve_arm_plt
from tools.research.probe_uvc_ptp_service_queue import LIB, SHA
from tools.research.build_uvc_ptp_descriptor_candidate import ROOT


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output-dir',required=True,type=Path)
    args=p.parse_args();out=args.output_dir.resolve()
    if not out.is_relative_to(ROOT/'artifacts'):p.error('Output must be under artifacts')
    raw=LIB.read_bytes();assert hashlib.sha256(raw).hexdigest()==SHA
    elf=ELFFile(io.BytesIO(raw));plt=resolve_arm_plt(elf)
    checks=[];events=[];state=dict(prefix=True)
    def check(n,v):
        if not v:raise AssertionError(n)
        checks.append(n)
    for a,n in {0x7d7c:'_Znwj',0x7740:'usb_trace_init',0x7bb8:'_ZN7CUsbSvcC1Ev',
        0x7984:'memset',0x7b38:'_ZN7CUsbSvc4stopE11__USBIF_DIDPvhPFS1_S1_S1_hiE',
        0x81ac:'_ZN7CUsbSvc11stop_gadgetEPvhPFS0_S0_S0_hiE'}.items():
        check('actual-plt-'+hex(a),plt[a]['name']==n)
    cpu=Uc(UC_ARCH_ARM,UC_MODE_ARM);cpu.mem_map(0,0x20000)
    for seg in elf.iter_segments():
        if seg['p_type']=='PT_LOAD':cpu.mem_write(seg['p_vaddr'],seg.data())
    control_path=LIB.with_name('libUsbControl.so');control_raw=control_path.read_bytes()
    control_sha='70cd5742fde9eea78c60905e4015531b4c3ab2668d2cb85c934531f451f1211f'
    assert hashlib.sha256(control_raw).hexdigest()==control_sha
    control=ELFFile(io.BytesIO(control_raw));control_base=0x1000000
    cpu.mem_map(control_base,0x20000)
    for seg in control.iter_segments():
        if seg['p_type']=='PT_LOAD':cpu.mem_write(control_base+seg['p_vaddr'],seg.data())
    cpu.mem_map(0x200000,0x10000);cpu.mem_map(0x300000,4096);cpu.mem_map(0x400000,0x10000)
    output,context,svc,payload,done=0x200000,0x201000,0x202000,0x203000,0x300000
    def word(a):return struct.unpack('<I',cpu.mem_read(a,4))[0]
    def put(a,v):cpu.mem_write(a,struct.pack('<I',v))
    def ret(v=0):cpu.reg_write(UC_ARM_REG_R0,v);cpu.reg_write(UC_ARM_REG_PC,cpu.reg_read(UC_ARM_REG_LR))
    def hook(c,a,size,_):
        if a==done:c.emu_stop();return
        if state['prefix'] and a==0xd86c:events.append('initialized-table-prefix-boundary');c.emu_stop();return
        if a==0x7d7c:
            n=c.reg_read(UC_ARM_REG_R0);assert n in (0xc4,0x128,12)
            events.append('allocator-double-'+str(n));ret({0xc4:context,0x128:svc,12:payload}[n]);return
        if a in (0x7740,0x7bb8,0x792c):ret();return
        if a==0x7984:
            dst=c.reg_read(UC_ARM_REG_R0);n=c.reg_read(UC_ARM_REG_R2)
            assert dst==context and n==0xc4 and c.reg_read(UC_ARM_REG_R1)==0
            c.mem_write(dst,bytes(n));ret(dst);return
        if a==0x7b38:c.reg_write(UC_ARM_REG_PC,0x9e01);return
        if a==0x81ac:
            state['arguments']=[c.reg_read(r) for r in (UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3)]
            events.append('native-stop-gadget-boundary');c.emu_stop();return
        if not any(x<=a<y for x,y in [(0xd7d8,0xd86c),(0xd37c,0xd466),(0xcddc,0xcdf0),(0x9e00,0x9ed6),
                                     (control_base+0x13324,control_base+0x13338)]):
            raise RuntimeError(f'Unexpected execution {a:08x}')
    def guard(c,access,a,size,value,_):
        if not any(x<=a and a+size<=y for x,y in [(output,output+4),(context,context+0xc4),(svc,svc+0x128),(payload,payload+12),(0x400000,0x410000)]):
            raise RuntimeError(f'Unexpected write {a:08x}')
    cpu.hook_add(UC_HOOK_CODE,hook);cpu.hook_add(UC_HOOK_MEM_WRITE,guard)
    def call(a,*values):
        for r,v in zip((UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3),values):cpu.reg_write(r,v)
        cpu.reg_write(UC_ARM_REG_SP,0x40f000);cpu.reg_write(UC_ARM_REG_LR,done)
        cpu.emu_start(a|1,0xffffffff,count=20000)
        return cpu.reg_read(UC_ARM_REG_R0)
    call(0xd7d9,output,0)
    check('prefix-reaches-table-boundary',events[-1]=='initialized-table-prefix-boundary')
    check('initializer-publishes-context',word(output)==context)
    check('initializer-links-service',word(context+0x3c)==svc)
    table={hex(n):hex(word(context+n)) for n in range(0,0x3c,4)}
    check('public-start-slot',word(context+8)==0xd551)
    check('public-stop-slot',word(context+12)==0xd37d)
    state['prefix']=False
    put(svc+0x9c,13);put(svc+0xa0,100);put(svc+0x98,3)
    before=len(events)
    call(word(context+12),context,13,0x300101)
    check('public-stop-reaches-native-stop',events[-1]=='native-stop-gadget-boundary')
    check('public-stop-payload',bytes(cpu.mem_read(payload,12))==struct.pack('<III',svc,0x300101,13))
    check('public-stop-native-arguments',state['arguments']==[svc,payload,12,0xd471])
    check('public-stop-state-four',word(svc+0x98)==4)
    check('public-stop-no-queue-or-lock-service',events[before:]==['allocator-double-12','native-stop-gadget-boundary'])
    before=len(events)
    check('public-stop-null-context',call(word(context+12),0,13,0)==0xfffffffe and len(events)==before)
    check('public-stop-invalid-device',call(word(context+12),context,60,0)==0xfffffffd and len(events)==before)
    # Actual application's doStop uses the initialized interface's +0xc slot.
    # Only its PIC-relative singleton cell is supplied as explicit fixture.
    put(control_base+0x1eac4,context);put(svc+0x98,3)
    before=len(events)
    call(control_base+0x13325,0x204000,13,0)
    check('application-stop-reaches-native-stop',events[-1]=='native-stop-gadget-boundary')
    check('application-stop-completion-address',word(payload+4)==control_base+0x12de5)
    check('application-stop-same-service',word(payload)==svc and word(payload+8)==13)
    check('application-stop-no-lock-service',events[before:]==['allocator-double-12','native-stop-gadget-boundary'])
    report=dict(status='original_public_api_boundary_checks_passed',count=len(checks),checks=checks,
        table=table,events=events,library_sha256=SHA,control_library_sha256=control_sha,
        probe_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        camera_access=False,limitations=['Only initialization prefix through table publication executes; overall initialization is not proven.',
            'Allocator, constructor, memset, trace and log services are explicit doubles.',
            'Object/service state and handle are explicit fixtures; no live address is inferred.',
            'Application singleton cell is an explicit fixture; only doStop runs in the application library.',
            'Stops before stop_gadget; callback completion/lifetime and caller scheduling remain unproven.'])
    out.mkdir(parents=True,exist_ok=True);(out/'manifest.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
