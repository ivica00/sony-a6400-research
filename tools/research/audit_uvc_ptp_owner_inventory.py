"""Execute read-only ARM inventory on explicit proc/stat syscall fixtures."""
import argparse,hashlib,io,json,struct
from pathlib import Path
from elftools.elf.elffile import ELFFile
from unicorn import Uc,UC_ARCH_ARM,UC_MODE_ARM,UC_HOOK_INTR
from unicorn.arm_const import UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R7,UC_ARM_REG_SP
from tools.research.build_uvc_ptp_descriptor_candidate import ROOT


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--elf',required=True,type=Path);p.add_argument('--output-dir',required=True,type=Path)
    args=p.parse_args();out=args.output_dir.resolve()
    if not out.is_relative_to(ROOT/'artifacts'):p.error('Output must be under artifacts')
    raw=args.elf.read_bytes();e=ELFFile(io.BytesIO(raw));checks=[];runs={}
    assert not any(s['p_type']=='PT_INTERP' for s in e.iter_segments())
    def check(n,v):
        if not v:raise AssertionError(n)
        checks.append(n)
    def directory(names):
        data=b''
        for name in names:
            name=name.encode()+b'\0';size=(19+len(name)+7)&~7
            data+=struct.pack('<QqHB',1,0,size,4)+name+bytes(size-19-len(name))
        return data
    for case in ('normal','wrong_node','no_proc','bad_directory','missing_fd'):
        cpu=Uc(UC_ARCH_ARM,UC_MODE_ARM);cpu.mem_map(0,0x200000);cpu.mem_map(0x400000,0x10000)
        for seg in e.iter_segments():
            if seg['p_type']=='PT_LOAD':cpu.mem_write(seg['p_vaddr'],seg.data())
        state=dict(output=b'',calls=[],consumed=set(),closed=[])
        paths={'/proc':3,'/proc/149/fd/':4,'/proc/149/task':5,'/proc/703/fd/':6}
        directories={3:directory(['.','..','149','703']),4:directory(['0','5']),5:directory(['149','380']),6:directory(['1'])}
        def string(a):
            b=bytearray()
            for i in range(256):
                n=cpu.mem_read(a+i,1)[0]
                if n==0:return b.decode()
                b.append(n)
            raise RuntimeError('Unterminated path')
        def syscall(c,number,_):
            assert number==2
            n=c.reg_read(UC_ARM_REG_R7);a=c.reg_read(UC_ARM_REG_R0);b=c.reg_read(UC_ARM_REG_R1);z=c.reg_read(UC_ARM_REG_R2)
            state['calls'].append(n)
            if n==1:state['exit']=a;c.emu_stop();return
            if n==4:
                assert a==1 and z<1024;state['output']+=bytes(c.mem_read(b,z));result=z
            elif n==5:
                path=string(a);assert b==0x4000 and z==0
                result=-2 if case=='no_proc' and path=='/proc' else paths[path]
            elif n==6:state['closed'].append(a);result=0
            elif n==217:
                assert z==4096
                data=b'' if a in state['consumed'] else directories[a];state['consumed'].add(a)
                if case=='bad_directory' and a==3:data=bytes(24)
                c.mem_write(b,data);result=len(data)
            elif n==195:
                path=string(a);assert path in ('/dev/usb/gadgetcore','/proc/149/fd/0','/proc/149/fd/5','/proc/703/fd/1')
                if case=='missing_fd' and path=='/proc/149/fd/5':result=-2
                else:
                    owner=path in ('/dev/usb/gadgetcore','/proc/149/fd/5')
                    data=bytearray(104);struct.pack_into('<I',data,16,0x2000 if owner else 0x8000)
                    struct.pack_into('<Q',data,32,0 if case=='wrong_node' else (0xf201 if owner else 0))
                    c.mem_write(b,bytes(data));result=0
            else:raise RuntimeError('Unexpected syscall '+str(n))
            c.reg_write(UC_ARM_REG_R0,result&0xffffffff)
        cpu.hook_add(UC_HOOK_INTR,syscall);cpu.reg_write(UC_ARM_REG_SP,0x40f000)
        cpu.emu_start(e.header['e_entry'],0xffffffff,count=2000000)
        text=state['output'].decode();check(case+'-bounded-exit','exit' in state)
        check(case+'-only-read-only-syscalls',set(state['calls'])<={1,4,5,6,195,217})
        check(case+'-labels-observational','observational=1 freeze=0 writes=0' in text)
        if case=='normal':
            check('normal-owner-by-device-number','OWNER pid=149 fd=5 major=242 minor=1' in text)
            check('normal-owner-thread-list','TASK pid=149 tid=149' in text and 'TASK pid=149 tid=380' in text)
            check('normal-summary',text.endswith('END owners=1 threads=2 errors=0 observational=1\n') and state['exit']==0)
            check('normal-closes-directories',sorted(state['closed'])==[3,4,5,6])
        elif case=='wrong_node':check('wrong-node-fails-before-proc',state['exit']==2 and 'node_mismatch' in text and 5 not in state['calls'])
        elif case=='no_proc':check('missing-proc-fails',state['exit']==3 and 'proc_unavailable' in text)
        elif case=='bad_directory':check('malformed-directory-fails',state['exit']==1 and 'errors=1' in text)
        elif case=='missing_fd':check('fd-race-reported-incomplete',state['exit']==1 and 'errors=1' in text and 'OWNER' not in text.split('\n',1)[1])
        runs[case]=dict(output=text,exit=state['exit'],syscalls=state['calls'])
    report=dict(status='offline_read_only_inventory_passed',count=len(checks),checks=checks,runs=runs,
        elf_sha256=hashlib.sha256(raw).hexdigest(),elf_bytes=len(raw),camera_access=False,
        limitations=['Proc contents and stat64 syscall results are explicit ARM ABI fixtures.',
            'No actual proc enumeration on camera, stopping of threads or proof of quiescence.'])
    out.mkdir(parents=True,exist_ok=True);(out/'manifest.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))


if __name__=='__main__':main()
