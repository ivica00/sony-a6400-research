"""Execute source-equal JPEG path packet construction up to its first call.

Explicit fixtures, no helper substitution, IPC, encoder or camera execution.
"""
import argparse
import hashlib
import json
import struct
from pathlib import Path
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE, UC_PROT_READ, UC_PROT_EXEC
from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
    UC_ARM_REG_R3, UC_ARM_REG_R7, UC_ARM_REG_PC, UC_ARM_REG_SP)

SOURCE_SHA256='c244a17c7676df916dfb4350d536547f1da466649618b958ed489e355394284a'


def probe(data):
    if hashlib.sha256(data).hexdigest()!=SOURCE_SHA256:
        raise ValueError('Expected exact source-equal E0132 path function')
    rows=[]
    for width in (640,1024,1280,1920):
        cpu=Uc(UC_ARCH_ARM,UC_MODE_THUMB)
        cpu.mem_map(0x11000,0x1000)
        cpu.mem_write(0x111a0,data)
        cpu.mem_protect(0x11000,0x1000,UC_PROT_READ|UC_PROT_EXEC)
        cpu.mem_map(0x20000,0x4000)
        sp=0x23000
        cpu.mem_write(sp,struct.pack('<III',0x1e00,11,50))
        cpu.reg_write(UC_ARM_REG_SP,sp)
        for register,value in [(UC_ARM_REG_R0,0x22000),(UC_ARM_REG_R1,0x20),
                               (UC_ARM_REG_R2,6),(UC_ARM_REG_R3,width)]:
            cpu.reg_write(register,value)

        def stop(machine,pc,size,context):
            if pc==0x111fa:
                machine.emu_stop()

        cpu.hook_add(UC_HOOK_CODE,stop)
        cpu.emu_start(0x111a1,0x11200,count=100)
        pc=cpu.reg_read(UC_ARM_REG_PC)
        if pc!=0x111fa:
            raise RuntimeError('Unexpected original-code stop')
        packet=bytes(cpu.mem_read(cpu.reg_read(UC_ARM_REG_R7),32))
        row={'width_fixture':width,'stop_pc':hex(pc),'prefix_fixture_bytes':packet.hex(),
             'rate_encoded':struct.unpack_from('<H',packet,0x10)[0],
             'compression':packet[0x13],
             'width_field':struct.unpack_from('<H',packet,0x14)[0],
             'reserved_zero_field':struct.unpack_from('<H',packet,0x16)[0],
             'size_limit_raw':struct.unpack_from('<I',packet,0x18)[0]}
        if (row['width_field'],row['rate_encoded'],row['compression'],row['size_limit_raw'])!=(width,0x1e00,11,50):
            raise RuntimeError('Original packet fields differ')
        rows.append(row)
    return {'source_sha256':SOURCE_SHA256,'controls':rows,
        'scope':'Original construction prefix, stops before memset. Explicit stack/register '
                'fixtures. Not a complete initialized packet; no IPC, receiver or encoder executed.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    args.output.write_text(json.dumps(probe(args.source.read_bytes()),indent=2),encoding='utf-8')
    print('4 original packet-prefix controls passed; no receiver/encoder success claimed')


if __name__=='__main__':main()
