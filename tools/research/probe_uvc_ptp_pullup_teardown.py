"""Original Sony pullup/GCW stop ordering; hardware operations are doubles."""
import argparse,hashlib,json,struct
from pathlib import Path
from unicorn import Uc,UC_ARCH_ARM,UC_MODE_ARM,UC_HOOK_CODE,UC_HOOK_MEM_WRITE
from unicorn.arm_const import UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_SP,UC_ARM_REG_LR,UC_ARM_REG_PC
from tools.research.build_uvc_ptp_descriptor_candidate import ROOT,KERNEL,KERNEL_SHA


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output-dir',required=True,type=Path)
    out=p.parse_args().output_dir.resolve()
    if not out.is_relative_to(ROOT/'artifacts'):p.error('Output must be under artifacts')
    raw=KERNEL.read_bytes();assert hashlib.sha256(raw).hexdigest()==KERNEL_SHA
    cpu=Uc(UC_ARCH_ARM,UC_MODE_ARM);base=0x60108000
    cpu.mem_map(base,(len(raw)+4095)&~4095);cpu.mem_write(base,raw)
    cpu.mem_map(0x6051b000,4096);cpu.mem_map(0x200000,0x10000);cpu.mem_map(0x300000,4096);cpu.mem_map(0x400000,0x10000)
    dw,busy,done=0x200000,0x200500,0x300000
    def word(a):return struct.unpack('<I',cpu.mem_read(a,4))[0]
    def put(a,v):cpu.mem_write(a,struct.pack('<I',v&0xffffffff))
    gcw=word(0x602bd44c);checks=[];events=[];runs={};state={}
    def check(n,v):
        if not v:raise AssertionError(n)
        checks.append(n)
    def ret(v=0):cpu.reg_write(UC_ARM_REG_R0,v&0xffffffff);cpu.reg_write(UC_ARM_REG_PC,cpu.reg_read(UC_ARM_REG_LR))
    services={0x6012c0ac:'migrate-disable-double',0x6012bee0:'migrate-enable-double',
        0x603c68f4:'lock-double',0x603c691c:'unlock-double',0x602b04f4:'stop-transfers-double',
        0x602b1a3c:'disable-ep0-double',0x602af150:'disconnect-notify-double',0x602aeffc:'run-stop-double'}
    def hook(c,a,size,_):
        if a==done:c.emu_stop();return
        if a==0x603c4e68:
            events.append('reschedule-boundary')
            if state['busy']=='hold':c.emu_stop();return
            put(busy+0x10,0);ret();return  # explicit external completion fixture
        if a in services:
            name=services[a];events.append([name,c.reg_read(UC_ARM_REG_R0),c.reg_read(UC_ARM_REG_R1)])
            ret(state['run_result'] if name=='run-stop-double' else 0);return
        if not any(x<=a<y for x,y in [(0x602b1d3c,0x602b1df8),(0x602bd834,0x602bd850),(0x602bd414,0x602bd44c)]):
            raise RuntimeError('Unexpected execution '+hex(a))
    def guard(c,access,a,size,value,_):
        if not any(x<=a and a+size<=y for x,y in [(dw,dw+0x1000),(gcw+0x60,gcw+0x64),(0x400000,0x410000)]):
            raise RuntimeError('Unexpected write '+hex(a))
    cpu.hook_add(UC_HOOK_CODE,hook);cpu.hook_add(UC_HOOK_MEM_WRITE,guard)
    def reset(mode='clear',old=0,result=0):
        events.clear();state.update(busy=mode,run_result=result)
        cpu.mem_write(dw,bytes(0x1000));put(dw+0xcc,dw+0x400);put(dw+0x400,busy)
        put(dw+0xd0,dw+0x600);put(dw+0xd4,dw+0x700);put(dw+0x170,old)
        put(busy+0x10,1 if mode!='clear' else 0)
    def call(a,r0,r1=0):
        cpu.reg_write(UC_ARM_REG_R0,r0);cpu.reg_write(UC_ARM_REG_R1,r1);cpu.reg_write(UC_ARM_REG_SP,0x40f000);cpu.reg_write(UC_ARM_REG_LR,done)
        cpu.emu_start(a,0xffffffff,count=10000);return cpu.reg_read(UC_ARM_REG_R0)
    reset();put(gcw+0x58,0x200900);put(gcw+0x60,2)
    check('gcw-stop-returns-zero',call(0x602bd834,0)==0)
    check('gcw-stop-changes-state-to-one',word(gcw+0x60)==1)
    check('gcw-stop-invokes-no-hardware-path',not any(isinstance(e,list) and e[0] in ('stop-transfers-double','run-stop-double','disable-ep0-double') for e in events))
    runs['gcw-stop']=list(events)
    reset();check('pullup-down-returns-native-run-result',call(0x602b1d3c,dw+0x150)==0)
    selected=[e for e in events if isinstance(e,list) and e[0] in ('stop-transfers-double','disable-ep0-double','run-stop-double')]
    check('pullup-down-teardown-order',[e[0] for e in selected]==['stop-transfers-double','disable-ep0-double','disable-ep0-double','run-stop-double'])
    check('pullup-down-native-endpoint-arguments',[e[1] for e in selected[:3]]==[dw,dw+0x600,dw+0x700])
    check('pullup-down-native-run-stop-argument',selected[-1][1:]==[dw,0]);runs['down-clear']=list(events)
    reset(result=-110);check('pullup-down-propagates-run-stop-error',call(0x602b1d3c,dw+0x150)==0xffffff92)
    reset(mode='hold',old=3);call(0x602b1d3c,dw+0x150)
    check('busy-pauses-at-reschedule',cpu.reg_read(UC_ARM_REG_PC)==0x603c4e68)
    check('busy-no-transfer-stop-before-completion',not any(isinstance(e,list) and e[0]=='stop-transfers-double' for e in events))
    check('busy-clears-native-field-before-wait',word(dw+0x170)==0)
    runs['busy-pending']=list(events)
    reset(mode='complete',old=3);check('busy-external-completion-allows-return',call(0x602b1d3c,dw+0x150)==0)
    check('busy-completion-before-transfer-stop',events.index('reschedule-boundary')<next(i for i,e in enumerate(events) if isinstance(e,list) and e[0]=='stop-transfers-double'))
    check('old-nonzero-field-triggers-native-notify',any(isinstance(e,list) and e[0]=='disconnect-notify-double' for e in events))
    runs['busy-completed-fixture']=list(events)
    report=dict(status='original_pullup_boundaries_passed',count=len(checks),checks=checks,runs=runs,kernel_sha256=KERNEL_SHA,
        probe_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),camera_access=False,
        limitations=['DWC/endpoint/GCW objects and busy state are explicit fixtures.',
            'Locks, scheduling, endpoint disable, transfer stop, notification and MMIO run-stop are service doubles.',
            'Original busy loop and ordering execute; external completion is explicitly supplied, not inferred.',
            'No live hardware stop, callback drain, timeout guarantee or USB mode change is proven.'])
    out.mkdir(parents=True,exist_ok=True);(out/'manifest.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))


if __name__=='__main__':main()
