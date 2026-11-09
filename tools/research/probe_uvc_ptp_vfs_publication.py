"""Original VFS pointer-load/call boundary, no live hook or scheduling claim."""
import argparse,hashlib,json,struct
from pathlib import Path
from unicorn import Uc,UC_ARCH_ARM,UC_MODE_ARM,UC_HOOK_CODE,UC_HOOK_MEM_WRITE
from unicorn.arm_const import UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3,UC_ARM_REG_SP,UC_ARM_REG_LR,UC_ARM_REG_PC
from tools.research.build_uvc_ptp_descriptor_candidate import ROOT,KERNEL,KERNEL_SHA


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output-dir',type=Path,required=True)
    out=p.parse_args().output_dir.resolve()
    if not out.is_relative_to(ROOT/'artifacts'):p.error('Output must be under artifacts')
    raw=KERNEL.read_bytes();assert hashlib.sha256(raw).hexdigest()==KERNEL_SHA
    c=Uc(UC_ARCH_ARM,UC_MODE_ARM);base=0x60108000
    c.mem_map(base,(len(raw)+4095)&~4095);c.mem_write(base,raw)
    c.mem_map(0x200000,4096);c.mem_map(0x300000,4096);c.mem_map(0x400000,0x10000)
    file,fops,old,new,done=0x200000,0x200100,0x300000,0x300004,0x300008
    state=dict(pause=True);checks=[];events=[]
    def put(a,v):c.mem_write(a,struct.pack('<I',v&0xffffffff))
    def check(n,v):
        if not v:raise AssertionError(n)
        checks.append(n)
    def word(a):return struct.unpack('<I',c.mem_read(a,4))[0]
    def hook(cpu,a,size,_):
        if a==0x601ce2d8 and state['pause']:cpu.emu_stop();return
        if a in (old,new):
            events.append(dict(target='old-recorder' if a==old else 'new-recorder',
                arguments=[cpu.reg_read(r) for r in (UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2)]))
            cpu.reg_write(UC_ARM_REG_R0,17 if a==old else 19)
            cpu.reg_write(UC_ARM_REG_PC,cpu.reg_read(UC_ARM_REG_LR));return
        if a==done:cpu.emu_stop();return
        if not 0x601ce2b0<=a<0x601ce2f4:raise RuntimeError('Unexpected execution '+hex(a))
    def guard(cpu,access,a,size,value,_):
        if not (0x400000<=a and a+size<=0x410000):raise RuntimeError('Unexpected write '+hex(a))
    c.hook_add(UC_HOOK_CODE,hook);c.hook_add(UC_HOOK_MEM_WRITE,guard)
    def invoke():
        for r,v in zip((UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2),(file,0xe204,0x12345678)):c.reg_write(r,v)
        c.reg_write(UC_ARM_REG_SP,0x40f000);c.reg_write(UC_ARM_REG_LR,done)
        c.emu_start(0x601ce2b0,0xffffffff,count=1000)
    put(file+0x10,fops);put(fops+0x20,old)
    invoke();check('original-vfs-paused-before-call',c.reg_read(UC_ARM_REG_PC)==0x601ce2d8)
    check('original-vfs-cached-old-target',c.reg_read(UC_ARM_REG_R3)==old)
    put(fops+0x20,new);state['pause']=False
    c.emu_start(0x601ce2d8,0xffffffff,count=1000)
    check('published-slot-is-new',word(fops+0x20)==new)
    check('already-loaded-call-uses-old-target',events[0]['target']=='old-recorder')
    check('old-call-preserves-arguments',events[0]['arguments']==[file,0xe204,0x12345678])
    check('old-call-result-returned',c.reg_read(UC_ARM_REG_R0)==17)
    invoke();check('next-call-uses-new-target',events[-1]['target']=='new-recorder')
    check('new-call-result-returned',c.reg_read(UC_ARM_REG_R0)==19)
    # Tie native device identity to the original init's devnode table.
    kw=lambda a:struct.unpack_from('<I',raw,a-base)[0]
    node=kw(0x604a5988);name=kw(node+0x18)
    major,minor,count=struct.unpack_from('<HHH',raw,node-base+0x1e)
    check('native-gadgetcore-node-name',raw[name-base:].split(b'\0',1)[0]==b'usb/gadgetcore')
    check('native-gadgetcore-node-device-number',(major,minor,count)==(242,1,1))
    report=dict(status='original_vfs_publication_boundaries_passed',count=len(checks),checks=checks,events=events,
        device=dict(name='usb/gadgetcore',major=major,minor=minor,count=count),kernel_sha256=KERNEL_SHA,
        probe_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),camera_access=False,
        limitations=['File/fops and replacement are explicit fixtures; targets are explicit return recorders.',
            'Original VFS load/call/return instructions execute; no native mode change or hook installation.',
            'Interleaving is deliberately supplied; physical scheduling and a publication solution remain unproven.'])
    out.mkdir(parents=True,exist_ok=True);(out/'manifest.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))


if __name__=='__main__':main()
