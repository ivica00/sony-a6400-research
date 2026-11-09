"""Original USB event producer, context lookup and ring writer offline."""
import hashlib
import json
import struct
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC
from tools.research.build_uvc_ptp_descriptor_candidate import ROOT, KERNEL, KERNEL_SHA


def main():
    raw=KERNEL.read_bytes()
    assert hashlib.sha256(raw).hexdigest()==KERNEL_SHA
    checks=[]
    for name in ('normal','payload-wrap','full','unknown-context','disabled','invalid-callback'):
        c=Uc(UC_ARCH_ARM,UC_MODE_ARM)
        c.mem_map(0x60108000,(len(raw)+4095)&~4095);c.mem_write(0x60108000,raw)
        c.mem_map(0x6051b000,4096);c.mem_map(0x100000,0x10000);c.mem_map(0x200000,0x10000)
        g,ring,registry,data,done=0x6051b05c,0x100000,0x101000,0x102000,0x103000
        events=[];returned=[];lock=[]
        def put(a,v):c.mem_write(a,struct.pack('<I',v&0xffffffff))
        def word(a):return struct.unpack('<I',c.mem_read(a,4))[0]
        put(g+0x84,0 if name=='disabled' else 1)
        put(g+0x44,ring);put(g+0x48,64);put(g+0x4c,60 if name=='full' else 0)
        put(g+0x50,58 if name=='payload-wrap' else 0)
        put(g+0x58,registry);c.mem_write(g+0x5c,b'\x01');put(registry,0x12345678)
        c.mem_write(data,b'PAYLOAD!')
        sp=0x20f000
        put(sp,8 if name=='payload-wrap' else 0);put(sp+4,data)
        def hook(cpu,a,size,unused):
            r0,r1,r2=[cpu.reg_read(r) for r in (UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2)]
            if a==done:
                returned.append(r0);cpu.emu_stop();return
            if a in (0x6012c0ac,0x6012bee0):result=0
            elif a==0x603c68f4:
                assert r0==0x604c8be0 and not lock;lock.append(r0);events.append('lock');result=0
            elif a==0x603c691c:
                assert lock==[r0];lock.clear();events.append('unlock');result=0
            elif a==0x60258ac0:
                assert r1==64;cpu.reg_write(UC_ARM_REG_R1,r0%r1);result=r0//r1
            elif a==0x60258b80:
                assert lock;c.mem_write(r0,bytes(c.mem_read(r1,r2)));events.append(['copy',r2]);result=r0
            elif a==0x6012c4a4:
                assert not lock and r0==0x6051b0bc;events.append('wake');result=0
            elif any(lo<=a<hi for lo,hi in [(0x602b5c14,0x602b5d70),(0x602b5b10,0x602b5c10),(0x602b57b0,0x602b5810)]):return
            else:raise RuntimeError(f'Unexpected execution {a:08x}')
            cpu.reg_write(UC_ARM_REG_R0,result&0xffffffff);cpu.reg_write(UC_ARM_REG_PC,cpu.reg_read(UC_ARM_REG_LR))
        c.hook_add(UC_HOOK_CODE,hook)
        for reg,value in [(UC_ARM_REG_R0,0),(UC_ARM_REG_R1,0 if name=='invalid-callback' else 0x76543210),(UC_ARM_REG_R2,0x99999999 if name=='unknown-context' else 0x12345678),(UC_ARM_REG_R3,2),(UC_ARM_REG_SP,sp),(UC_ARM_REG_LR,done)]:c.reg_write(reg,value)
        c.emu_start(0x602b5c14,0xffffffff,count=4000)
        result=-105 if name=='full' else -22 if name=='invalid-callback' else 0
        assert returned==[result&0xffffffff] and not lock
        if name in ('normal','payload-wrap'):
            length=20 if name=='payload-wrap' else 12
            assert word(g+0x4c)==length and word(g+0x3c)==1 and events[-1]=='wake'
            start=58 if name=='payload-wrap' else 0
            b=bytes(c.mem_read(ring,64));record=bytes(b[(start+i)%64] for i in range(length))
            assert record[:10]==struct.pack('<IIBB',0x12345678,0x76543210,2,8 if name=='payload-wrap' else 0)
            if name=='payload-wrap':assert record[12:20]==b'PAYLOAD!'
        elif name=='full':
            assert word(g+0x4c)==60 and word(g+0x40)==1 and 'wake' not in events
        elif name=='unknown-context':
            assert word(g+0x4c)==0 and word(g+0x3c)==1 and events==['lock','unlock','wake']
        else:assert not events and word(g+0x4c)==0
        checks.append(dict(name=name,result=result,used=word(g+0x4c),notifications=word(g+0x3c),overflow=word(g+0x40),events=events))
    out=ROOT/'artifacts/analysis/uvc-ptp-event-queue-e0217';out.mkdir(parents=True,exist_ok=True)
    (out/'manifest.json').write_text(json.dumps(dict(status='offline_original_event_queue_passed',kernel_sha256=KERNEL_SHA,checks=checks,limitations=['Original producer/context lookup/ring writer execute; globals/registry/ring are fixtures.', 'Division, memcpy, spinlock/migration and waitqueue wake are explicit services; no real locking, consumer scheduling, callback execution or physical proof.']),indent=2)+'\n')
    print(f'{len(checks)} original event queue cases passed')


if __name__=='__main__':main()
