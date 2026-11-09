"""Original OSAL user callback dispatcher and USB callback, offline only."""
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
    root=ROOT/'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/lib'
    specs=[('libosal_uipc.so',0,'b6ded35add9582413b401cf4db78ec2c9a201b632e78c2731d6bbb379249b3eb'),
        ('libUsbControl.so',0x1000000,'70cd5742fde9eea78c60905e4015531b4c3ab2668d2cb85c934531f451f1211f')]
    cpu=Uc(UC_ARCH_ARM,UC_MODE_ARM);images=[]
    for name,base,sha in specs:
        raw=(root/name).read_bytes();assert hashlib.sha256(raw).hexdigest()==sha
        e=ELFFile(io.BytesIO(raw));images.append(e);cpu.mem_map(base,0x20000)
        for seg in e.iter_segments():
            if seg['p_type']=='PT_LOAD':cpu.mem_write(base+seg['p_vaddr'],seg.data())
        for sec in e.iter_sections():
            if sec['sh_type']=='SHT_REL':
                sy=e.get_section(sec['sh_link'])
                for r in sec.iter_relocations():
                    target=base+r['r_offset'];kind=r['r_info_type']
                    if kind==23:
                        old=struct.unpack('<I',cpu.mem_read(target,4))[0];cpu.mem_write(target,struct.pack('<I',(old+base)&0xffffffff))
                    elif kind in (21,22):
                        s=sy.get_symbol(r['r_info_sym'])
                        if s['st_value']:cpu.mem_write(target,struct.pack('<I',base+s['st_value']))
    cpu.mem_map(0x200000,0x10000);cpu.mem_map(0x300000,4096);cpu.mem_map(0x400000,0x10000)
    checks=[];events=[];state=dict(mode='register',receives=0,retry=False)
    def check(n,v):
        if not v:raise AssertionError(n)
        checks.append(n)
    def word(a):return struct.unpack('<I',cpu.mem_read(a,4))[0]
    def put(a,v):cpu.mem_write(a,struct.pack('<I',v&0xffffffff))
    def ret(v=0):cpu.reg_write(UC_ARM_REG_R0,v&0xffffffff);cpu.reg_write(UC_ARM_REG_PC,cpu.reg_read(UC_ARM_REG_LR))
    osal,control=images;plt=resolve_arm_plt(osal)
    for a,n in {0x1758:'u_osal_reg_msg_queue_cb',0x17f8:'ioctl',0x181c:'pthread_create'}.items():check('plt-'+hex(a),plt[a]['name']==n)
    entry=0x1c68+word(0x1ce0)
    check('pthread-start-literal',entry&0xffffffff==0x2031)
    def hook(c,a,size,_):
        r=[c.reg_read(x) for x in (UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3)]
        if a==0x300000:c.emu_stop();return
        if a==0x1758:c.reg_write(UC_ARM_REG_PC,0x2749);return
        if a==0x17f8:
            if state['mode']=='register':
                state['registration']=[r[0],r[1],word(r[2]),[word(word(r[2]+4)+i*4) for i in range(4)]]
                c.emu_stop();return
            assert r[:2]==[17,0x8000000d]
            descriptor=word(r[2]+4);assert word(r[2])==0 and word(descriptor+12)==3
            state['receives']+=1;events.append('receive-'+str(state['receives']))
            if state['retry'] and state['receives']==1:ret(0xfffffc03);return
            if state['receives']==(3 if state['retry'] else 2):c.emu_stop();return
            for i,v in enumerate([0x10131a5,0x55,0x200100,3]):put(descriptor+i*4,v)
            ret();return
        if a in (0x199c,0x1940,0x19e8):ret();return  # naming/cancel service doubles
        if a==0x16e8:
            assert r[1:3]==[0,16];c.mem_write(r[0],bytes(16));ret(r[0]);return
        if a==0x1013054:events.append(['builder-double',r[0],r[1]]);ret();return
        if a==0x10131a4:state['callback_args']=r[:2]
        if a==0x100a2f4:events.append(['free-double',r[0],r[1]]);ret();return
        if not any(x<=a<y for x,y in [(0x4300,0x43ca),(0x2748,0x27a4),(0x2030,0x20f2),(0x10131a4,0x10131bc)]):
            raise RuntimeError(f'Unexpected execution {a:08x}')
    def guard(c,access,a,size,value,_):
        if not (0x400000<=a and a+size<=0x410000):raise RuntimeError(f'Unexpected write {a:08x}')
    cpu.hook_add(UC_HOOK_CODE,hook);cpu.hook_add(UC_HOOK_MEM_WRITE,guard)
    def call(a,*values):
        for r,v in zip((UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3),values):cpu.reg_write(r,v)
        cpu.reg_write(UC_ARM_REG_SP,0x40f000);cpu.reg_write(UC_ARM_REG_LR,0x300000)
        cpu.emu_start(a|1,0xffffffff,count=20000)
    put(0xef80,17)
    call(0x4301,0xe942cd,0x200000,0x10131a5,0)
    check('sony-id-takes-user-ioctl-route',cpu.reg_read(UC_ARM_REG_PC)==0x17f8)
    fd,cmd,qid,fields=state['registration']
    check('registration-ioctl-header',[fd,cmd,qid]==[17,0x80000008,0xe942cd])
    check('registration-callback-wire-fields',fields==[0x200000,0x10131a5,0,0])
    call(0x4301,0xffff8001,0x200000,0x10131a5,0)
    check('negative-local-id-rejected',cpu.reg_read(UC_ARM_REG_R0)==0xfffffc00)
    call(0x4301,0x8001,0x200000,0,0)
    check('null-local-callback-rejected',cpu.reg_read(UC_ARM_REG_R0)==0xfffffc00)
    state['mode']='dispatch';put(0x200100,1);put(0x200104,0xfffffffb)
    call(0x2031,3)
    check('dispatcher-loads-callback-arguments',state['callback_args']==[0x200100,0x55])
    check('usb-callback-builds-from-operation-status',events[1]==['builder-double',1,0xfffffffb])
    check('usb-callback-frees-message-after-builder',events[2][0]=='free-double' and events[2][2]==0x200100)
    check('dispatcher-next-receive-after-callback',events[-1]=='receive-2' and len(events)==4)
    check('dispatcher-paused-at-second-ioctl',cpu.reg_read(UC_ARM_REG_PC)==0x17f8)
    state.update(receives=0,retry=True);events.clear();call(0x2031,3)
    check('dispatcher-retries-transient-error-before-callback',events[:3]==['receive-1','receive-2',['builder-double',1,0xfffffffb]])
    check('dispatcher-retry-preserves-worker-and-returns-to-wait',state['receives']==3 and events[-1]=='receive-3')
    report=dict(status='original_osal_dispatch_boundaries_passed',count=len(checks),checks=checks,events=events,
        libraries=[dict(name=n,sha256=s) for n,b,s in specs],camera_access=False,
        probe_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        limitations=['Registration stops before kernel ioctl; pthread creation is identified statically, not executed.',
            'Kernel ioctl output, file descriptor and worker index are explicit fixtures.',
            'Naming/cancel/memset, ObjMsg builder and message free services are explicit doubles.',
            'Original dispatcher and registered USB callback execute, but native scheduling and unregister quiescence remain unproven.'])
    out.mkdir(parents=True,exist_ok=True);(out/'manifest.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))


if __name__=='__main__':main()
