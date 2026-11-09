"""Execute compiled SD query identity guard with explicit pread fixtures."""
import argparse, hashlib, json, struct
from pathlib import Path
from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('binary',type=Path);p.add_argument('--report',type=Path,required=True);a=p.parse_args()
    with a.binary.open('rb') as f:
        e=ELFFile(f)
        segments=[(s['p_vaddr'],s['p_memsz'],s.data()) for s in e.iter_segments() if s['p_type']=='PT_LOAD']
        entry=next(s['st_value'] for s in e.get_section_by_name('.symtab').iter_symbols() if s.name=='a6400_mon_sd_identity')
        plt=e.get_section_by_name('.plt');lo,hi=plt['sh_addr'],plt['sh_addr']+plt['sh_size']
        rel=e.get_section_by_name('.rel.plt');symbols=e.get_section(rel['sh_link'])
        imports={lo+20+12*i:symbols.get_symbol(r['r_info_sym']).name for i,r in enumerate(rel.iter_relocations())}
    cases=['valid','missing-volume','internal-flash','bad-source-prefix','inactive-service','wrong-subcommand','wrong-dispatcher','duplicate-registration','foreign-prefix','main-first','short-read']
    passed=[]
    for case in cases:
        c=Uc(UC_ARCH_ARM,UC_MODE_ARM);pages=set()
        for address,size,data in segments:
            for page in range(address&~4095,(address+size+4095)&~4095,4096):
                if page not in pages:c.mem_map(page,4096);pages.add(page)
            c.mem_write(address,data)
        c.mem_map(0x200000,0x10000);c.mem_map(0x300000,4096)
        mwf,fs=0x4000000,0x5000000;memory={}
        def put(address,data):
            if isinstance(data,int):data=struct.pack('<I',data)
            memory.update({address+i:b for i,b in enumerate(data)})
        put(fs+0x1583c,bytes.fromhex('2de9f04f01284a4c99b00aaf7c4440f3'))
        for address,value in [(fs+0x6bff0,0x6000000),(0x6000000,0x6001000),(fs+0x6c034,0x6002000),(fs+0x6bfe8,0x6003000),(mwf+0x418d8,0x6004000),(mwf+0x419f0,0x6004010),(mwf+0x41940,0x6005000)]:put(address,value)
        put(0x6001954,b'/dev/mmca\0');put(0x6002000,b'\1\0');put(0x6004000,b'\0'*8);put(0x6004010,b'\0')
        put(0x600303c,struct.pack('<3I',0x6006000,fs+0x1583d,0));put(0x6006000,b'getdriveinfo\0')
        put(0x6005000,b'\0'*(129*12));put(0x6005000,struct.pack('<3I',0x6006100,fs+0x15c61,0));put(0x6006100,b'IFSYS\0')
        changes={'missing-volume':(0x6000000,0),'internal-flash':(0x6001954,b'/dev/nfla\0'),'bad-source-prefix':(fs+0x1583c,b'\0'),'inactive-service':(0x6002000,b'\0\0'),'wrong-subcommand':(0x6003040,fs+0x1583f),'wrong-dispatcher':(0x6005004,fs+0x15c63),'duplicate-registration':(0x600500c,struct.pack('<3I',0x6006100,fs+0x15c61,0)),'foreign-prefix':(0x6004000,b'X'),'main-first':(0x6004010,b'\1')}
        if case in changes:put(*changes[case])
        returned=[];reads=[]
        def hook(cpu,address,size,unused):
            if address==0x300000:returned.append(cpu.reg_read(UC_ARM_REG_R0));cpu.emu_stop();return
            if lo<=address<hi:
                if imports.get(address)=='memcmp':
                    left,right,count=[cpu.reg_read(r) for r in (UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2)]
                    x,y=bytes(cpu.mem_read(left,count)),bytes(cpu.mem_read(right,count))
                    cpu.reg_write(UC_ARM_REG_R0,0 if x==y else 1)
                    cpu.reg_write(UC_ARM_REG_PC,cpu.reg_read(UC_ARM_REG_LR));return
                assert imports.get(address)=='pread',imports.get(address)
                assert cpu.reg_read(UC_ARM_REG_R0)==9,'unexpected external call'
                dest,count,source=[cpu.reg_read(r) for r in (UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3)]
                reads.append([source,count])
                data=bytes(memory.get(source+i,0) for i in range(count))
                if case=='short-read':cpu.reg_write(UC_ARM_REG_R0,0)
                else:
                    assert all(source+i in memory for i in range(count)),hex(source)
                    cpu.mem_write(dest,data);cpu.reg_write(UC_ARM_REG_R0,count)
                cpu.reg_write(UC_ARM_REG_PC,cpu.reg_read(UC_ARM_REG_LR))
        c.hook_add(UC_HOOK_CODE,hook)
        for reg,value in [(UC_ARM_REG_R0,9),(UC_ARM_REG_R1,mwf),(UC_ARM_REG_R2,fs),(UC_ARM_REG_SP,0x20f000),(UC_ARM_REG_LR,0x300000)]:c.reg_write(reg,value)
        c.emu_start(entry,0xffffffff,count=30000)
        assert returned==[int(case=='valid')],(case,returned)
        passed.append({'case':case,'reads':len(reads)})
    report={'status':'compiled_guard_fixture_passed_not_hardware','binary_sha256':hashlib.sha256(a.binary.read_bytes()).hexdigest(),'cases':passed,'limitations':['pread and memcmp are explicit fixtures; no camera, command publisher, mapping lookup, concurrency or storage operation executed.']}
    a.report.write_text(json.dumps(report,indent=2)+'\n');print(f'{len(passed)} compiled SD identity cases passed')


if __name__=='__main__':main()
