"""Original camera-file PTP gate slices; explicit prior-call result fixtures."""
import argparse
import hashlib
import io
import json
from pathlib import Path
from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE, UC_PROT_READ, UC_PROT_EXEC
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R3, UC_ARM_REG_R4, UC_ARM_REG_PC

SOURCE_SHA256='3aafb56f32214cc3bbbd9ec3c326b22bbb36a177d6967361f2539a7cd2e25cd9'


def probe(raw):
    if hashlib.sha256(raw).hexdigest()!=SOURCE_SHA256:
        raise ValueError('Expected exact captured camera libInfraRemote.so')
    elf=ELFFile(io.BytesIO(raw))
    segments=[s for s in elf.iter_segments() if s['p_type']=='PT_LOAD'
              and s['p_vaddr']<=0xf000 and 0x10000<=s['p_vaddr']+s['p_filesz']]
    if len(segments)!=1:raise ValueError('Ambiguous code source mapping')
    seg=segments[0];offset=0xf000-seg['p_vaddr']+seg['p_offset']
    rows=[]

    def execute(start,stop,registers):
        cpu=Uc(UC_ARCH_ARM,UC_MODE_THUMB)
        cpu.mem_map(0xf000,0x1000)
        cpu.mem_write(0xf000,raw[offset:offset+0x1000])
        cpu.mem_protect(0xf000,0x1000,UC_PROT_READ|UC_PROT_EXEC)
        for r,v in registers:cpu.reg_write(r,v)
        def hook(machine,pc,size,context):
            if pc==stop:machine.emu_stop()
        cpu.hook_add(UC_HOOK_CODE,hook)
        cpu.emu_start(start|1,0xf900,count=12)
        if cpu.reg_read(UC_ARM_REG_PC)!=stop:raise RuntimeError('Unexpected boundary')
        return cpu.reg_read(UC_ARM_REG_R0)

    for status in (0,1):
        result=execute(0xf792,0xf79e,[(UC_ARM_REG_R0,status)])
        if result!=(0x2009 if status==0 else 0):raise RuntimeError('Status result differs')
        rows.append({'gate':'GetObjectInfo post-getter tail','status_fixture':status,'return':hex(result)})
    for handle in (0xffffc001,0xffffc002):
        result=execute(0xf83a,0xf848,[(UC_ARM_REG_R4,handle),(UC_ARM_REG_R3,0x2001)])
        if result!=(0 if handle==0xffffc001 else 0x2009):raise RuntimeError('Handle result differs')
        rows.append({'gate':'GetObject post-header handle filter','handle_fixture':hex(handle),'return':hex(result)})
    return {'camera_file_sha256':SOURCE_SHA256,'controls':rows,
            'scope':'Original instruction slices on explicit prior-call result/register fixtures; '
                    'no PTP exchange, live application calls or frame delivery.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    args.output.write_text(json.dumps(probe(args.source.read_bytes()),indent=2),encoding='utf-8')
    print('4 original PTP gate controls passed; no PTP transaction executed')


if __name__=='__main__':main()
