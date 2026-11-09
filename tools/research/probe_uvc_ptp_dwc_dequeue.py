"""Original DWC dequeue and giveback with hardware/completion recorders."""
import hashlib,json,struct
from unicorn import Uc,UC_ARCH_ARM,UC_MODE_ARM,UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_SP,UC_ARM_REG_LR,UC_ARM_REG_PC
from tools.research.build_uvc_ptp_descriptor_candidate import ROOT,KERNEL,KERNEL_SHA


def main():
    raw=KERNEL.read_bytes();assert hashlib.sha256(raw).hexdigest()==KERNEL_SHA
    checks=[]
    for name,queue,initial in [('missing',None,-115),('pending',0x24,-115),('active',0x2c,-115),('preserve-error',0x24,-5)]:
        c=Uc(UC_ARCH_ARM,UC_MODE_ARM);c.mem_map(0x60108000,(len(raw)+4095)&~4095);c.mem_write(0x60108000,raw)
        c.mem_map(0x100000,0x10000);c.mem_map(0x200000,0x10000)
        dwc,ep,req,callback,done=0x100000,0x101000,0x102000,0x103000,0x104000
        events=[];returned=[];lock=[]
        def put(a,v):c.mem_write(a,struct.pack('<I',v&0xffffffff))
        def word(a):return struct.unpack('<I',c.mem_read(a,4))[0]
        put(ep+0x48,dwc);c.mem_write(ep+0x54,b'\x08')
        for offset in (0x24,0x2c):
            head=ep+offset;put(head,head);put(head+4,head)
        if queue:
            head=ep+queue;put(head,req+0x34);put(head+4,req+0x34);put(req+0x34,head);put(req+0x38,head)
        put(req+0x1c,callback);put(req+0x2c,initial);put(req+0x48,0x1234)
        def hook(cpu,a,size,unused):
            r0,r1=[cpu.reg_read(r) for r in (UC_ARM_REG_R0,UC_ARM_REG_R1)]
            if a==done:returned.append(r0);cpu.emu_stop();return
            if a in (0x6012c0ac,0x6012bee0):result=0
            elif a==0x603c68f4:
                assert r0==dwc+0x70 and not lock;lock.append(r0);events.append('lock');result=0
            elif a==0x603c691c:
                assert lock==[r0];lock.clear();events.append('unlock');result=0
            elif a==0x602b03d8:
                assert lock and r0==dwc and r1==8;events.append('hardware-stop');result=0
            elif a==0x602b529c:events.append('unmap');result=0
            elif a==callback:
                assert not lock and [r0,r1]==[ep,req] and word(req+0x48)==0
                events.append('completion');result=0
            elif 0x602b053c<=a<0x602b05fc or 0x602affb8<=a<0x602b00f8:return
            else:raise RuntimeError(f'Unexpected execution {a:08x}')
            cpu.reg_write(UC_ARM_REG_R0,result);cpu.reg_write(UC_ARM_REG_PC,cpu.reg_read(UC_ARM_REG_LR))
        c.hook_add(UC_HOOK_CODE,hook)
        for reg,value in [(UC_ARM_REG_R0,ep),(UC_ARM_REG_R1,req),(UC_ARM_REG_SP,0x20f000),(UC_ARM_REG_LR,done)]:c.reg_write(reg,value)
        c.emu_start(0x602b053c,0xffffffff,count=2000)
        expected=-22 if queue is None else 0
        assert returned==[expected&0xffffffff] and not lock
        assert events.count('completion')==int(queue is not None)
        assert events.count('hardware-stop')==int(queue==0x2c)
        if queue:
            assert word(ep+queue)==ep+queue
            assert word(req+0x2c)==((-104 if initial==-115 else initial)&0xffffffff)
            assert events.index('unlock')<events.index('completion')<len(events)-1
        checks.append(dict(name=name,result=expected,request_status=word(req+0x2c),events=events))
    out=ROOT/'artifacts/analysis/uvc-ptp-dwc-dequeue-e0217';out.mkdir(parents=True,exist_ok=True)
    (out/'manifest.json').write_text(json.dumps(dict(status='offline_original_dwc_dequeue_passed',kernel_sha256=KERNEL_SHA,checks=checks,limitations=['Original dequeue and giveback execute; endpoint/list/request are fixtures.', 'Hardware stop, unmap, locking/migration and final completion are explicit recorders; no DMA stop, physical callback or concurrent list mutation proof.']),indent=2)+'\n')
    print(f'{len(checks)} original DWC dequeue cases passed')


if __name__=='__main__':main()
