"""Execute Sony's original parameter-packing function on explicit fixture data."""
import io
import json
import hashlib
import struct
from pathlib import Path
from elftools.elf.elffile import ELFFile
from unicorn import Uc,UC_ARCH_ARM,UC_MODE_THUMB
from unicorn.arm_const import UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_SP,UC_ARM_REG_LR

ROOT=Path(__file__).resolve().parents[2]


def main():
    path=ROOT/'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/lib/libusbcmd.so'
    raw=path.read_bytes(); elf=ELFFile(io.BytesIO(raw))
    symbols=[s for s in elf.get_section_by_name('.dynsym').iter_symbols() if 'PackParamDriver' in s.name]
    if len(symbols)!=1: raise ValueError('Ambiguous original function')
    symbol=symbols[0]; address=symbol['st_value']&~1
    section=elf.get_section(symbol['st_shndx']); offset=address-section['sh_addr']
    code=section.data()[offset:offset+symbol['st_size']]
    cpu=Uc(UC_ARCH_ARM,UC_MODE_THUMB)
    for base in (address&~4095,0x10000,0x20000,0x30000,0x40000,0x50000): cpu.mem_map(base,4096)
    cpu.mem_write(address,code)
    public=struct.pack('<IIIHHII',0x12340000,4096,17,0x42,0,1000,0xfeedbeef)
    cpu.mem_write(0x30000,public); cpu.mem_write(0x20000,b'\xa5'*20)
    for register,value in ((UC_ARM_REG_R0,0x40000),(UC_ARM_REG_R1,0x20000),
                           (UC_ARM_REG_R2,0x30000),(UC_ARM_REG_SP,0x50ff0),(UC_ARM_REG_LR,0x10001)):
        cpu.reg_write(register,value)
    cpu.emu_start(address|1,0x10000,count=100)
    actual=bytes(cpu.mem_read(0x20000,20))
    expected=struct.pack('<IIIIH',0x12340000,4096,17,1000,0x42)+b'\xa5\xa5'
    if actual!=expected: raise AssertionError('Original driver packing differs from documented layout')
    report={'scope':'Original code with constructed buffers; no USB registration or kernel reply supplied',
            'source_sha256':hashlib.sha256(raw).hexdigest(),'symbol':symbol.name,'linked_address':hex(address),
            'code_hex':code.hex(),'public_24_bytes':public.hex(),'driver_20_bytes':actual.hex(),
            'reserved_bytes_untouched':True,'verified':True}
    destination=ROOT/'artifacts/analysis/usb-debug-abi-trace-20261105.json'
    destination.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(destination)


if __name__=='__main__': main()
