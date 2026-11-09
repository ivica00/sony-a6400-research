"""Original DWC endpoint command polling with explicit MMIO/delay fixtures."""
import hashlib,json,struct
from unicorn import Uc,UC_ARCH_ARM,UC_MODE_ARM,UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3,UC_ARM_REG_SP,UC_ARM_REG_LR,UC_ARM_REG_PC
from tools.research.build_uvc_ptp_descriptor_candidate import ROOT,KERNEL,KERNEL_SHA


def main():
    raw=KERNEL.read_bytes();assert hashlib.sha256(raw).hexdigest()==KERNEL_SHA
    checks=[]
    cases=[('immediate',1,4,0,False,7),('three-polls',3,0,0,False,7),('timeout',0,4,0,False,7),('status-bits',1,4,0xf000,False,7),('stop-idle',0,4,0,True,0),('stop-completed',1,4,0,True,7),('stop-command-timeout',0,4,0,True,7)]
    for name,clear_after,mode,completion_status,wrapper,resource in cases:
        c=Uc(UC_ARCH_ARM,UC_MODE_ARM);c.mem_map(0x60108000,(len(raw)+4095)&~4095);c.mem_write(0x60108000,raw)
        c.mem_map(0x100000,0x10000);c.mem_map(0x200000,0x10000)
        dwc,ep,mmio,params,done=0x100000,0x101000,0x102000,0x103000,0x104000
        def put(a,v):c.mem_write(a,struct.pack('<I',v&0xffffffff))
        def word(a):return struct.unpack('<I',c.mem_read(a,4))[0]
        warning_cell=struct.unpack_from('<I',raw,0x602b0478-0x60108000)[0]
        if not any(lo<=warning_cell<=hi for lo,hi,_ in c.mem_regions()):c.mem_map(warning_cell&~4095,4096)
        put(warning_cell,0)
        post_delay=struct.unpack_from('<I',raw,0x602b0480-0x60108000)[0]
        put(0x604c92d0+0x1c,0)  # Explicit absent optional MMIO barrier callback.
        put(dwc+(8+0x34)*4,ep);c.mem_write(ep+0x55,b'\x08');c.mem_write(dwc+0x2f0,bytes([mode]))
        c.mem_write(ep+0x54,b'\x08');c.mem_write(ep+0x57,bytes([resource]));put(ep+0x4c,0x10)
        put(dwc+0x2b4,mmio);put(mmio+0x100,0x140)
        for i,v in enumerate((0x11111111,0x22222222,0x33333333)):put(params+i*4,v)
        polls=[];delays=[];restores=[];returned=[];warnings=[];command_returns=[]
        def hook(cpu,a,size,unused):
            r0,r1=[cpu.reg_read(r) for r in (UC_ARM_REG_R0,UC_ARM_REG_R1)]
            if a==done:returned.append(r0);cpu.emu_stop();return
            if a==0x602b0378:
                polls.append(1)
                if clear_after and len(polls)==clear_after:put(mmio+0x78c,completion_status)
                return
            if a==0x602b0428:
                command_returns.append(r0);return
            if a==0x60257f04:
                assert r0 in (0x1a36e,post_delay);delays.append(r0);result=0
            elif a==0x602592e0:
                assert r1==12;c.mem_write(r0,bytes(r1));result=r0
            elif a==0x60133e5c:
                warnings.append(1);result=0
            elif a==0x602aeb2c:
                assert r0==dwc and r1==(0x140 if mode==0 else 0);restores.append(r1);result=0
            elif 0x602b0220<=a<0x602b03d0 or (wrapper and 0x602b03d8<=a<0x602b0478):return
            else:raise RuntimeError(f'Unexpected execution {a:08x}')
            cpu.reg_write(UC_ARM_REG_R0,result);cpu.reg_write(UC_ARM_REG_PC,cpu.reg_read(UC_ARM_REG_LR))
        c.hook_add(UC_HOOK_CODE,hook)
        command=(7<<16)|0x908
        for reg,value in [(UC_ARM_REG_R0,dwc),(UC_ARM_REG_R1,8),(UC_ARM_REG_R2,command),(UC_ARM_REG_R3,params),(UC_ARM_REG_SP,0x20f000),(UC_ARM_REG_LR,done)]:c.reg_write(reg,value)
        c.emu_start(0x602b03d8 if wrapper else 0x602b0220,0xffffffff,count=30000)
        result=-110 if not clear_after else 0
        if wrapper:
            assert len(returned)==1
            assert c.mem_read(ep+0x57,1)==b'\0'
            assert word(ep+0x4c)==(0 if resource else 0x10)
            assert command_returns==([result&0xffffffff] if resource else [])
            assert len(warnings)==int(bool(resource) and not clear_after)
            if not resource:
                assert not polls and not restores and not delays
                checks.append(dict(name=name,polls=0,command_called=False));continue
        else:assert returned==[result&0xffffffff]
        assert len(restores)==1
        assert len(polls)==(clear_after or 500) and len(delays)==len(polls)-1+int(wrapper)
        assert [word(mmio+0x780+i*4) for i in range(3)]==([0,0,0] if wrapper else [0x11111111,0x22222222,0x33333333])
        assert word(mmio+0x78c)==(command|0x400 if not clear_after else completion_status)
        if mode==0:assert word(mmio+0x100)==0
        checks.append(dict(name=name,result=result,polls=len(polls),delay_calls=len(delays),restore_argument=restores[0]))
    out=ROOT/'artifacts/analysis/uvc-ptp-endpoint-command-e0218';out.mkdir(parents=True,exist_ok=True)
    (out/'manifest.json').write_text(json.dumps(dict(status='offline_original_endpoint_command_passed',kernel_sha256=KERNEL_SHA,checks=checks,limitations=['Original command body executes against emulated MMIO with scripted completion timing.', 'Delay and PHY-state restore are explicit recorders; no real hardware timing, elapsed deadline, DMA termination or physical teardown proof.']),indent=2)+'\n')
    print(f'{len(checks)} original endpoint command cases passed')


if __name__=='__main__':main()
