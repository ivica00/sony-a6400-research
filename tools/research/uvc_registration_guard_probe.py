"""Execute original a6400 gadget registration guards on descriptor fixtures."""
import argparse
import hashlib
import json
import struct
from pathlib import Path
from unicorn import Uc,UC_ARCH_ARM,UC_MODE_ARM,UC_HOOK_CODE,UC_PROT_READ,UC_PROT_EXEC
from unicorn.arm_const import (UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3,
    UC_ARM_REG_R4,UC_ARM_REG_R5,UC_ARM_REG_R6,UC_ARM_REG_R9,UC_ARM_REG_R11,UC_ARM_REG_R12,UC_ARM_REG_PC)

ROOT=Path(__file__).resolve().parents[2]
KERNEL=ROOT/'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked/vmlinux.bin'
SHA='12eeec829407595e28265f7d0db3b88c56f63a9f0fdd725c9c53c66a49643707'


def probe():
    raw=KERNEL.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=SHA:raise ValueError('Kernel identity mismatch')
    cases=[('a6400_layout',[(0x10,0x11110000),(0x14,0x22220000)],True),
           ('reference_layout',[(0x10,0x33330000),(0x18,0x11110000),(0x1c,0x22220000)],False),
           ('missing_start',[(0x14,0x22220000)],False),
           ('missing_stop',[(0x10,0x11110000)],False)]
    rows=[]
    for name,fields,expected in cases:
        cpu=Uc(UC_ARCH_ARM,UC_MODE_ARM)
        cpu.mem_map(0x602b8000,0x1000)
        offset=0x602b8000-0x60108000
        cpu.mem_write(0x602b8000,raw[offset:offset+0x1000])
        cpu.mem_protect(0x602b8000,0x1000,UC_PROT_READ|UC_PROT_EXEC)
        cpu.mem_map(0x100000,0x1000)
        descriptor=bytearray(0x38)
        for off,value in fields:struct.pack_into('<I',descriptor,off,value)
        cpu.mem_write(0x100000,bytes(descriptor));cpu.mem_protect(0x100000,0x1000,UC_PROT_READ)
        cpu.reg_write(UC_ARM_REG_R6,0x100000);trace=[]
        def hook(machine,pc,size,context):
            trace.append(pc)
            if pc in (0x602b865c,0x602b872c):machine.emu_stop()
        cpu.hook_add(UC_HOOK_CODE,hook)
        cpu.emu_start(0x602b8644,0x602b8730,count=16)
        stop=cpu.reg_read(UC_ARM_REG_PC);passed=stop==0x602b865c
        if stop not in (0x602b865c,0x602b872c) or passed!=expected:
            raise RuntimeError('Unexpected original guard result')
        rows.append({'case':name,'guard_passed':passed,'stop':hex(stop),
            'descriptor_fixture':descriptor.hex(),'trace':[hex(a) for a in trace]})
    dispatch=[]
    reference=ROOT/'firmware/extracted_zve10_v203_linuxnames/firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked/vmlinux.bin'
    zraw=reference.read_bytes()
    if hashlib.sha256(zraw).hexdigest()!='74fbef5a7c36149cf3256623950798332f9ead0fa719bf6d61dcac69397950e2':
        raise ValueError('Reference kernel identity mismatch')
    for model,data,start,stop,callback_off,state_off in [
        ('a6400',raw,0x602b8ecc,0x602b8efc,0x10,0x0c),
        ('zve10',zraw,0x602bd380,0x602bd3b0,0x18,0x14)]:
        cpu=Uc(UC_ARCH_ARM,UC_MODE_ARM);page=start&~0xfff
        cpu.mem_map(page,0x1000);offset=page-0x60108000
        cpu.mem_write(page,data[offset:offset+0x1000]);cpu.mem_protect(page,0x1000,UC_PROT_READ|UC_PROT_EXEC)
        cpu.mem_map(0x100000,0x2000)
        record,descriptor,interface,manager,frame=0x100100,0x100200,0x100300,0x100400,0x100500
        cpu.mem_write(record,struct.pack('<I',descriptor))
        cpu.mem_write(descriptor+callback_off,struct.pack('<I',0x11110000))
        cpu.mem_write(interface+1,b'\x03');cpu.mem_write(manager+0x11,b'\x02')
        cpu.mem_write(frame+0xc,struct.pack('<I',0x12345678))
        for register,value in [(UC_ARM_REG_R0,interface),(UC_ARM_REG_R4,record),
            (UC_ARM_REG_R5,manager),(UC_ARM_REG_R9,1),(UC_ARM_REG_R11,frame)]:cpu.reg_write(register,value)
        def stop_dispatch(machine,pc,size,context):
            if pc==stop:machine.emu_stop()
        cpu.hook_add(UC_HOOK_CODE,stop_dispatch)
        cpu.emu_start(start,stop+4,count=20)
        values=[cpu.reg_read(r) for r in [UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3,UC_ARM_REG_R12]]
        if cpu.reg_read(UC_ARM_REG_PC)!=stop or values!=[descriptor,2,3,0x12345678,0x11110000]:
            raise RuntimeError('Original dispatcher ABI differs')
        if bytes(cpu.mem_read(descriptor+state_off,1))!=b'\x01':raise RuntimeError('Original state store differs')
        dispatch.append({'model':model,'r0_r1_r2_r3_ip':[hex(v) for v in values],
            'descriptor_state_offset':state_off,'callback_offset':callback_off,'stopped_before_blx':hex(stop)})
    return {'kernel_sha256':SHA,'controls':rows,'dispatch_controls':dispatch,'camera_access':False,
            'scope':'Original callback-presence guards and dispatch tails, after explicit earlier-state fixtures. '
                    'No allocation, registration, callback invocation or physical kernel execution.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    args.output.write_text(json.dumps(probe(),indent=2),encoding='utf-8')
    print('4 original callback guards and 2 original dispatch-tail controls pass; no callback invoked')


if __name__=='__main__':main()
