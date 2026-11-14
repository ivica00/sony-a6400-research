"""Execute Sony's original parameter-packing function on explicit fixture data."""
import argparse
import io
import json
import hashlib
import struct
from pathlib import Path
from elftools.elf.elffile import ELFFile
from unicorn import Uc,UC_ARCH_ARM,UC_MODE_ARM,UC_MODE_THUMB
from unicorn.arm_const import UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_SP,UC_ARM_REG_LR

ROOT=Path(__file__).resolve().parents[2]


def trace(path, *, expected_sha256=None):
    raw=path.read_bytes(); sha=hashlib.sha256(raw).hexdigest()
    if expected_sha256 is not None and sha!=expected_sha256:
        raise ValueError('Library input identity mismatch')
    elf=ELFFile(io.BytesIO(raw))
    if (elf.elfclass!=32 or not elf.little_endian
            or elf['e_machine']!='EM_ARM' or elf['e_type']!='ET_DYN'):
        raise ValueError('Expected ELF32 little-endian ARM shared library')
    table=elf.get_section_by_name('.dynsym')
    if table is None: raise ValueError('Missing dynamic symbol table')
    symbols=[s for s in table.iter_symbols() if 'PackParamDriver' in s.name]
    if len(symbols)!=1: raise ValueError('Ambiguous original function')
    symbol=symbols[0]; address=symbol['st_value']&~1
    if not isinstance(symbol['st_shndx'],int) or not 0<symbol['st_size']<=256:
        raise ValueError('Packing function outside bounded profile')
    section=elf.get_section(symbol['st_shndx']); offset=address-section['sh_addr']
    code=section.data()[offset:offset+symbol['st_size']]
    if offset<0 or len(code)!=symbol['st_size']: raise ValueError('Truncated packing function')
    thumb=bool(symbol['st_value']&1)
    cpu=Uc(UC_ARCH_ARM,UC_MODE_THUMB if thumb else UC_MODE_ARM)
    code_base=address&~4095; code_end=(address+len(code)+4095)&~4095
    fixtures=(0x10000,0x20000,0x30000,0x40000,0x50000)
    if any(code_base<base+4096 and base<code_end for base in fixtures):
        raise ValueError('Packing function overlaps fixture pages')
    cpu.mem_map(code_base,code_end-code_base)
    for base in fixtures: cpu.mem_map(base,4096)
    cpu.mem_write(address,code)
    public=struct.pack('<IIIHHII',0x12340000,4096,17,0x42,0,1000,0xfeedbeef)
    cpu.mem_write(0x30000,public); cpu.mem_write(0x20000,b'\xa5'*20)
    for register,value in ((UC_ARM_REG_R0,0x40000),(UC_ARM_REG_R1,0x20000),
                           (UC_ARM_REG_R2,0x30000),(UC_ARM_REG_SP,0x50ff0),(UC_ARM_REG_LR,0x10001)):
        cpu.reg_write(register,value)
    cpu.emu_start(address|1 if thumb else address,0x10000,count=100)
    actual=bytes(cpu.mem_read(0x20000,20))
    expected=struct.pack('<IIIIH',0x12340000,4096,17,1000,0x42)+b'\xa5\xa5'
    if actual!=expected: raise AssertionError('Original driver packing differs from documented layout')
    report={'scope':'Original code with constructed buffers; no USB registration or kernel reply supplied',
            'source_sha256':sha,'symbol':symbol.name,'linked_address':hex(address),'thumb':thumb,
            'code_hex':code.hex(),'public_24_bytes':public.hex(),'driver_20_bytes':actual.hex(),
            'reserved_bytes_untouched':True,'verified':True}
    return report


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--library',type=Path,default=ROOT/'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/lib/libusbcmd.so')
    parser.add_argument('--sha256',help='Expected source-library SHA-256')
    parser.add_argument('--output',type=Path,default=ROOT/'artifacts/analysis/usb-debug-abi-trace-20261105.json')
    args=parser.parse_args(argv)
    report=trace(args.library,expected_sha256=args.sha256)
    args.output.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(args.output)


if __name__=='__main__': main()
