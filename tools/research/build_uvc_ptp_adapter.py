"""Offline compiled ARM adapter checks, with original UVC classification slices.

Does not bind callbacks, patch a module, register endpoints or access a camera.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import struct
import subprocess

from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE, UC_HOOK_MEM_WRITE, UC_PROT_READ, UC_PROT_EXEC
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC

ROOT=Path(__file__).resolve().parents[2]
REF=ROOT/'firmware/extracted_zve10_v203_linuxnames/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/kmod/usbg_video.ko'
REF_SHA='d385a051bf01b0e5ea37412623ae85cfe3cda76ab0d11e61d111994ca9fbf4fb'
SOURCE=ROOT/'tools/native_camera/uvc_ptp_adapter.c'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',required=True,type=Path)
    args=parser.parse_args(); out=args.output_dir.resolve()
    if not out.is_relative_to(ROOT/'artifacts'): parser.error('Output must be under artifacts')
    out.mkdir(parents=True,exist_ok=True)
    def run(command):
        if os.name=='nt':
            command=['wsl.exe','--cd','/mnt/'+ROOT.drive[0].lower()+ROOT.as_posix()[2:],'--exec',*command]
        subprocess.run(command,cwd=ROOT,check=True)
    rel=lambda p:p.relative_to(ROOT).as_posix()
    obj=out/'adapter.o'; target=out/'adapter.elf'
    run(['arm-linux-gnueabi-gcc','-std=gnu11','-marm','-march=armv7-a',
         '-mfloat-abi=softfp','-ffreestanding','-fno-builtin',
         '-fno-tree-loop-distribute-patterns','-fno-pic','-fno-pie',
         '-fno-stack-protector','-O2','-Wall','-Wextra','-Werror',
         '-c',rel(SOURCE),'-o',rel(obj)])
    run(['arm-linux-gnueabi-ld','--no-undefined','-Ttext=0x10000','-e',
         'a6400_uvc_ptp_translate_setup','-o',rel(target),rel(obj)])
    reference=REF.read_bytes()
    if hashlib.sha256(reference).hexdigest()!=REF_SHA: raise ValueError('Reference identity mismatch')
    ref_elf=ELFFile(io.BytesIO(reference)); ref_text=ref_elf.get_section_by_name('.text').data()
    elf=ELFFile(io.BytesIO(target.read_bytes()))
    symbols={s.name:s['st_value'] for s in elf.get_section_by_name('.symtab').iter_symbols()}
    cpu=Uc(UC_ARCH_ARM,UC_MODE_ARM)
    cpu.mem_map(0,0x50000)
    for s in elf.iter_segments():
        if s['p_type']=='PT_LOAD':cpu.mem_write(s['p_vaddr'],s.data())
    cpu.mem_map(0x100000,0x10000);cpu.mem_write(0x100000,ref_text)
    cpu.mem_protect(0x100000,0x10000,UC_PROT_READ|UC_PROT_EXEC)
    cpu.mem_map(0x200000,0x10000);cpu.mem_map(0x400000,0x10000)
    cpu.mem_map(0x500000,0x1000)
    phase=['adapter']; stop=[0x500000]; writes=[]
    text=elf.get_section_by_name('.text')
    def code_guard(machine,address,size,user):
        if address==stop[0]:machine.emu_stop();return
        if phase[0]=='adapter': valid=text['sh_addr']<=address<text['sh_addr']+text['sh_size']
        elif phase[0]=='classify': valid=0x101390<=address<0x101418 or address in (0x101690,0x101694,0x101698,0x10169c,0x1016a0)
        else: valid=0x10116c<=address<0x101178
        if not valid:raise RuntimeError(f'Unexpected code {address:08x} in {phase[0]}')
    def write_guard(machine,access,address,size,value,user):
        if 0x400000<=address and address+size<=0x410000:return
        if phase[0]=='adapter' and 0x200100<=address and address+size<=0x200108:
            writes.append(address);return
        if phase[0]=='start-tag' and address==0x200818 and size==1:return
        raise RuntimeError(f'Unexpected {phase[0]} write {address:08x}/{size}')
    cpu.hook_add(UC_HOOK_CODE,code_guard);cpu.hook_add(UC_HOOK_MEM_WRITE,write_guard)
    def execute(address,end,*args):
        stop[0]=end
        for r,v in zip((UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2),args):cpu.reg_write(r,v)
        cpu.reg_write(UC_ARM_REG_SP,0x40f000);cpu.reg_write(UC_ARM_REG_LR,0x500000)
        cpu.emu_start(address,0xffffffff,count=1000)
        if cpu.reg_read(UC_ARM_REG_PC)!=end:raise RuntimeError('Missing bounded stop')
        return cpu.reg_read(UC_ARM_REG_R0)
    checks=[]
    def check(name,value):
        if not value:raise AssertionError(name)
        checks.append(name)
    def translate(data,wire,source=0x200000,dest=0x200100):
        phase[0]='adapter';cpu.mem_write(0x200000,data);cpu.mem_write(0x200100,b'\xa5'*8)
        value=execute(symbols['a6400_uvc_ptp_translate_setup'],0x500000,source,wire,dest)
        return value,bytes(cpu.mem_read(0x200100,8))
    def classify(data,end):
        phase[0]='classify';cpu.mem_write(0x200000,data)
        execute(0x101390,end,0x200000,0x200800)
    for wire,expected_stop in [(1,0x101410),(2,0x1016a4)]:
        request=bytes([0xa1,0x81,0,1,wire,0,1,0])
        value,mapped=translate(request,wire)
        check(f'interface-{wire}-translated',value==0 and mapped[4]==wire-1)
        check(f'interface-{wire}-other-bytes-preserved',mapped[:4]+mapped[5:]==request[:4]+request[5:])
        check(f'interface-{wire}-source-unchanged',bytes(cpu.mem_read(0x200000,8))==request)
        classify(mapped,expected_stop);check(f'original-classification-interface-{wire}',True)
        entity=bytes([0xa1,0x81,0,1,wire,2,1,0])
        value,mapped=translate(entity,wire)
        check(f'entity-id-preserved-{wire}',value==0 and mapped[5]==2)
        classify(mapped,0x1016f8);check(f'original-entity-path-{wire}',True)
    # Unadapted wire VC=1 reaches the original VS path: direct relocation fails.
    classify(bytes([0xa1,0x81,0,1,1,0,1,0]),0x1016a4)
    check('original-unadapted-vc-misclassified-as-vs',True)
    good=bytes([0x21,1,0,2,1,0,26,0])
    value,mapped=translate(good,1)
    check('set-cur-fields-preserved',value==0 and mapped==good[:4]+b'\0'+good[5:])
    for name,data,wire,source,dest in [
        ('ptp-interface-zero',good[:4]+b'\0'+good[5:],1,0x200000,0x200100),
        ('wrong-shadow',good,2,0x200000,0x200100),
        ('invalid-shadow',good,3,0x200000,0x200100),
        ('standard',b'\x81'+good[1:],1,0x200000,0x200100),
        ('vendor',b'\xc1'+good[1:],1,0x200000,0x200100),
        ('endpoint-recipient',b'\x22'+good[1:],1,0x200000,0x200100),
        ('null-source',good,1,0,0x200100),
        ('null-output',good,1,0x200000,0),
        ('alias',good,1,0x200000,0x200000),
        ('partial-overlap',good,1,0x200000,0x200004),
    ]:
        before=len(writes);value,_=translate(data,wire,source,dest)
        check('reject-'+name,value==0xffffffea)
        check('reject-'+name+'-no-write',len(writes)==before)
    phase[0]='adapter'
    def fixture():
        cpu.mem_write(0x201000,bytes(0x1000))
        cpu.mem_write(0x2010f4,struct.pack('<I',0x201200))
        cpu.mem_write(0x20121c,struct.pack('<I',0x201300))
        cpu.mem_write(0x20124c,struct.pack('<I',1))
        cpu.mem_write(0x201300,bytes([7,5,0x84,2,0,2,0]))
        cpu.mem_write(0x201424,struct.pack('<I',0x201200))
        cpu.mem_write(0x201524,struct.pack('<I',0x201200))
        cpu.mem_write(0x201600,struct.pack('<II',0,0x201400))
    def select(count=2,dwc=0x201000,listing=0x201600):
        return execute(symbols['a6400_uvc_ptp_select_endpoint'],0x500000,dwc,count,listing)
    fixture();check('endpoint-84-wrapper-returned',select()==0x201400)
    check('original-packed-count-low-byte',select(0xaacc0002)==0x201400)
    for name,address,data in [
        ('missing-raw',0x2010f4,bytes(4)),('disabled',0x20124c,bytes(4)),
        ('missing-descriptor',0x20121c,bytes(4)),('ptp-in-81',0x201302,b'\x81'),
        ('ptp-event-83',0x201302,b'\x83'),('interrupt-type',0x201303,b'\x03'),
        ('wrong-packet-size',0x201304,b'\x40\0'),('short-descriptor',0x201300,b'\x06'),
        ('wrong-wrapper-raw',0x201424,struct.pack('<I',0x201280)),
        ('duplicate-wrapper',0x201600,struct.pack('<II',0x201400,0x201400)),
        ('ambiguous-wrappers',0x201600,struct.pack('<II',0x201500,0x201400)),
    ]:
        fixture();cpu.mem_write(address,data);check('endpoint-reject-'+name,select()==0)
    for name,count,dwc,listing in [('zero-count',0,0x201000,0x201600),
        ('oversized-count',17,0x201000,0x201600),('null-dwc',2,0,0x201600),
        ('null-list',2,0x201000,0)]:
        fixture();check('endpoint-reject-'+name,select(count,dwc,listing)==0)
    # Original START's explicit endpoint tag is still 81. Do not silently
    # claim the original module can consume the new endpoint without changes.
    phase[0]='start-tag';cpu.mem_write(0x200800,bytes(0x100))
    cpu.reg_write(UC_ARM_REG_R5,0x200800);cpu.reg_write(UC_ARM_REG_R6,0x200900)
    cpu.mem_write(0x2009b4,struct.pack('<I',0x200a00))
    cpu.mem_write(0x200a00,struct.pack('<I',0x201400))
    cpu.reg_write(UC_ARM_REG_R3,0x200a00)
    execute(0x10116c,0x101178)
    check('original-start-tag-remains-81',bytes(cpu.mem_read(0x200818,1))==b'\x81')
    # Explicit MOD, not an original-code compatibility claim: change only
    # the immediate in the proved START request tag instruction.
    text_offset=ref_elf.get_section_by_name('.text')['sh_offset']
    instruction_offset=text_offset+0x116c
    original_instruction=reference[instruction_offset:instruction_offset+4]
    check('start-tag-original-instruction-identity',original_instruction==bytes.fromhex('7e20e0e3'))
    patched=bytearray(reference)
    patched[instruction_offset:instruction_offset+4]=bytes.fromhex('7b20e0e3')
    changed=[i for i,(a,b) in enumerate(zip(reference,patched)) if a!=b]
    check('endpoint-mod-only-one-proved-byte',changed==[instruction_offset])
    cpu.mem_write(0x10116c,bytes.fromhex('7b20e0e3'))
    # Host changes the instruction between runs; discard cached translations.
    cpu.ctl_remove_cache(0x10116c,0x101178)
    cpu.reg_write(UC_ARM_REG_R5,0x200800);cpu.reg_write(UC_ARM_REG_R6,0x200900)
    cpu.reg_write(UC_ARM_REG_R3,0x200a00)
    execute(0x10116c,0x101178)
    check('explicit-mod-start-tag-84',bytes(cpu.mem_read(0x200818,1))==b'\x84')
    patched_path=out/'reference-endpoint84.offline.o'
    patched_path.write_bytes(patched)
    # Alternative to copied setup requests: let a narrowly modified original
    # classifier consume wire 1/2 directly, keeping the original request pointer.
    classifier_offset=text_offset+0x13e8
    check('classifier-original-instruction-identity',reference[classifier_offset:classifier_offset+4]==bytes.fromhex('ff5015e2'))
    combined=bytearray(patched)
    combined[classifier_offset:classifier_offset+4]=bytes.fromhex('015055e2') # subs r5,r5,#1
    combined_changes=[i for i,(a,b) in enumerate(zip(reference,combined)) if a!=b]
    check('combined-mod-only-three-proved-bytes',combined_changes==sorted([instruction_offset,classifier_offset,classifier_offset+2]))
    cpu.mem_write(0x1013e8,bytes.fromhex('015055e2'))
    cpu.ctl_remove_cache(0x101390,0x1017b0)
    for wire,end in [(1,0x101410),(2,0x1016a4)]:
        request=bytes([0xa1,0x81,0,1,wire,0,1,0])
        classify(request,end)
        check('mod-direct-wire-classification-'+str(wire),True)
        check('mod-native-interface-register-'+str(wire),cpu.reg_read(UC_ARM_REG_R5)==wire-1)
        check('mod-original-request-retained-'+str(wire),bytes(cpu.mem_read(0x200000,8))==request)
        request=bytes([0xa1,0x81,0,1,wire,2,1,0])
        classify(request,0x1016f8)
        check('mod-entity-path-unchanged-'+str(wire),True)
    combined_path=out/'reference-wire12-endpoint84.offline.o'
    combined_path.write_bytes(combined)
    report=dict(status='offline_controls_passed',check_count=len(checks),checks=checks,
        source_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        header_sha256=hashlib.sha256(SOURCE.with_suffix('.h').read_bytes()).hexdigest(),
        reference_sha256=REF_SHA,elf_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
        endpoint_mod=dict(path=str(patched_path.relative_to(ROOT)),
            sha256=hashlib.sha256(patched).hexdigest(),file_offset=hex(instruction_offset),
            text_offset='0x116c',original_instruction=original_instruction.hex(),
            mod_instruction='7b20e0e3',changed_byte_count=len(changed)),
        direct_wire_mod=dict(path=str(combined_path.relative_to(ROOT)),
            sha256=hashlib.sha256(combined).hexdigest(),
            classifier_file_offset=hex(classifier_offset),classifier_text_offset='0x13e8',
            original_instruction='ff5015e2',mod_instruction='015055e2',
            changed_byte_count=len(combined_changes)),
        camera_access=False,deployed=False,deployable=False,
        limitations=['Copied-request adapter is not connected to live callbacks; caller-owned output lifetime remains unresolved for that approach.',
            'Direct-wire MOD uses the unchanged native request pointer; only its classifier slices are executed, not complete callback/EP0 completion.',
            'Original classification slices stop before allocators/queueing; entity errors and stream negotiation are not completed.',
            'Endpoint pointers/descriptors/enabled state are explicit fixtures, not live hardware allocation.',
            'Original START writes 81; a separate explicit one-byte MOD changes the tag to 84. It is not a complete linked/deployable module.',
            'No combined UVC/PTP enumeration, stream, control command, or teardown is proven.'])
    (out/'manifest.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
