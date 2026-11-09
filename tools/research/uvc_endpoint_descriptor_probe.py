"""Execute original endpoint descriptor construction on reference USB2 profiles.

Stops before the actual UDC enable call. Prior endpoint matching is an explicit
fixture, not a live endpoint allocation or successful controller operation.
"""
import argparse
import hashlib
import io
import json
import struct
from pathlib import Path
from elftools.elf.elffile import ELFFile
from unicorn import Uc,UC_ARCH_ARM,UC_MODE_ARM,UC_HOOK_CODE,UC_HOOK_MEM_WRITE,UC_PROT_READ,UC_PROT_EXEC
from unicorn.arm_const import (UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3,
    UC_ARM_REG_R4,UC_ARM_REG_R5,UC_ARM_REG_R6,UC_ARM_REG_R7,UC_ARM_REG_R9,UC_ARM_REG_R12)
from tools.research.uvc_request_abi_probe import PROFILES

ROOT=Path(__file__).resolve().parents[2]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report-dir',type=Path,required=True)
    args=parser.parse_args();out=args.report_dir.resolve()
    if not out.is_relative_to(ROOT/'artifacts'):parser.error('Report must remain under artifacts')
    out.mkdir(parents=True,exist_ok=False)
    inventory=json.loads((ROOT/'artifacts/analysis/zve10-uvc-bound-e0134/reference-inventory.json').read_text())['entries']
    entry=next(e for e in inventory if e['path'].endswith('/libInfraUsbCmn.so'))
    library=(ROOT/entry['path']).read_bytes()
    if hashlib.sha256(library).hexdigest()!=entry['sha256']:raise ValueError('Reference library identity mismatch')
    elf=ELFFile(io.BytesIO(library))
    def original_profile(address):
        segments=[s for s in elf.iter_segments() if s['p_type']=='PT_LOAD'
                  and s['p_vaddr']<=address and address+20<=s['p_vaddr']+s['p_filesz']]
        if len(segments)!=1:raise ValueError('Ambiguous endpoint profile mapping')
        s=segments[0];off=address-s['p_vaddr']+s['p_offset'];return library[off:off+20]
    rows=[];checks=[]
    def check(name,value):
        if not value:raise AssertionError(name)
        checks.append(name)
    for model,folder,sha in PROFILES:
        raw=(ROOT/'firmware'/folder/'firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked/vmlinux.bin').read_bytes()
        if hashlib.sha256(raw).hexdigest()!=sha:raise ValueError('Kernel identity mismatch')
        symbols=json.loads((ROOT/'artifacts/analysis/uvc-portability-final-e0135'/(model+'-kallsyms-checked.json')).read_text())
        if symbols['source_sha256']!=sha:raise ValueError('Symbol identity mismatch')
        entry_pc=next(s['address'] for s in symbols['symbols'] if s['name']=='ep_ctrl_enable_ep')
        literal=entry_pc+(0x16c if model=='a6400' else 0x17c)
        pool=struct.unpack_from('<I',raw,literal-0x60108000)[0]
        if not 0x60400000<=pool<0x61000000:raise ValueError('Unexpected static descriptor pool')
        for label,address in [('hs',0x1ccc0),('fs',0x1ccd4)]:
            info=original_profile(address);cpu=Uc(UC_ARCH_ARM,UC_MODE_ARM)
            page=entry_pc&~4095;cpu.mem_map(page,4096);off=page-0x60108000
            cpu.mem_write(page,raw[off:off+4096]);cpu.mem_protect(page,4096,UC_PROT_READ|UC_PROT_EXEC)
            cpu.mem_map(pool&~4095,4096);cpu.mem_map(0x200000,4096)
            context,manager,endpoint,ops,profile=0x200000,0x200100,0x200200,0x200300,0x200400
            cpu.mem_write(context,struct.pack('<I',manager));cpu.mem_write(manager+0x20,struct.pack('<I',3))
            cpu.mem_write(endpoint+8,struct.pack('<I',ops));cpu.mem_write(ops,struct.pack('<I',0x500000))
            cpu.mem_write(endpoint+0x1a,b'\x80');cpu.mem_write(profile,info)
            registers=[(UC_ARM_REG_R2,info[0]),(UC_ARM_REG_R3,context),(UC_ARM_REG_R4,endpoint),
                (UC_ARM_REG_R5,profile),(UC_ARM_REG_R6,0),(UC_ARM_REG_R7,info[1]),
                (UC_ARM_REG_R9,info[4]),(UC_ARM_REG_R12,struct.unpack_from('<H',info,2)[0])]
            for r,v in registers:cpu.reg_write(r,v)
            stop=entry_pc+(0x120 if model=='a6400' else 0x130);stopped=[False];writes=[]
            def hook(machine,pc,size,context):
                if pc==stop:stopped[0]=True;machine.emu_stop()
            def write(machine,access,a,size,value,context):
                if not (pool<=a and a+size<=pool+9 or endpoint+0x14<=a and a+size<=endpoint+0x20):
                    raise RuntimeError('Original endpoint write outside explicit fixture')
                writes.append({'address':hex(a),'bytes':size})
            cpu.hook_add(UC_HOOK_CODE,hook);cpu.hook_add(UC_HOOK_MEM_WRITE,write)
            cpu.emu_start(entry_pc+0xa0,stop+4,count=100)
            descriptor=bytes(cpu.mem_read(pool,9));name=model+'-'+label
            expected=bytes([7,5,info[0],info[1],info[2],info[3],info[4],0,0])
            check(name+'-stop-before-udc',stopped[0])
            check(name+'-wire-descriptor',descriptor==expected)
            check(name+'-bulk-transfer-type',descriptor[3]&3==2)
            check(name+'-maxpacket',struct.unpack('<H',cpu.mem_read(endpoint+0x14,2))[0]==struct.unpack_from('<H',info,2)[0])
            check(name+'-enable-arguments',[cpu.reg_read(r) for r in (UC_ARM_REG_R0,UC_ARM_REG_R1)]==[endpoint,pool])
            rows.append({'case':name,'reference_profile_linked':hex(address),'reference_profile':info.hex(),
                'constructed_usb_descriptor':descriptor.hex(),'endpoint_flag_1a':bytes(cpu.mem_read(endpoint+0x1a,1)).hex(),
                'stop_before_udc_enable':hex(stop),'writes':writes})
    report={'status':'passed','count':len(checks),'checks':checks,'controls':rows,'camera_access':False,
        'reference_library_sha256':entry['sha256'],'limitations':[
            'Endpoint matching and static output pool memory are EXPLICIT offline fixtures.',
            'Original constructor stops BEFORE USB controller enable; no endpoint is activated.',
            'Reference profile bmAttributes=2 proves BULK descriptor construction, not throughput.',
            'Kernel endpoint flag byte+1a differs; semantics and any required translation remain unresolved.']}
    (out/'manifest.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(len(checks),'original endpoint-construction controls passed; reference UVC USB2 profiles are BULK')


if __name__=='__main__':main()
