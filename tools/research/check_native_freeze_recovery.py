"""Compile and execute actual CPU barrier header with ptrace/libc doubles."""
import argparse, hashlib, io, json, os, subprocess
from pathlib import Path
from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC
from tools.research.build_uvc_ptp_descriptor_candidate import ROOT


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output-dir',required=True,type=Path)
    out=p.parse_args().output_dir.resolve()
    if not out.is_relative_to(ROOT/'artifacts'):p.error('Output must be under artifacts')
    out.mkdir(parents=True,exist_ok=True)
    target=out/'native-freeze-contract.elf'
    source=ROOT/'tools/research/native_freeze_contract_fixture.c'
    command=['arm-linux-gnueabi-gcc','-std=gnu11','-marm','-march=armv7-a','-mfloat-abi=softfp',
             '-O2','-Wall','-Wextra','-Werror','-ffreestanding','-fno-builtin','-fno-pie','-fno-pic',
             '-fno-stack-protector','-nostdlib','-static','-Itools/native_camera',
             '-Wl,--build-id=none,-Ttext=0x10000,-e,main',source.relative_to(ROOT).as_posix(),
             '-o',target.relative_to(ROOT).as_posix(),'-lgcc']
    if os.name=='nt':command=['wsl.exe','--cd','/mnt/'+ROOT.drive[0].lower()+ROOT.as_posix()[2:],'--exec',*command]
    subprocess.run(command,cwd=ROOT,check=True)
    elf=ELFFile(io.BytesIO(target.read_bytes()))
    names={s.name:s['st_value'] for s in elf.get_section_by_name('.symtab').iter_symbols()}
    c=Uc(UC_ARCH_ARM,UC_MODE_ARM);c.mem_map(0,0x100000);c.mem_map(0x400000,0x10000)
    for segment in elf.iter_segments():
        if segment['p_type']=='PT_LOAD':c.mem_write(segment['p_vaddr'],segment.data())
    def hook(cpu,a,size,unused):
        if a==names['fail']:raise AssertionError('Fixture line '+str(cpu.reg_read(UC_ARM_REG_R0)))
    c.hook_add(UC_HOOK_CODE,hook)
    c.reg_write(UC_ARM_REG_SP,0x40f000);c.reg_write(UC_ARM_REG_LR,0x30000)
    c.emu_start(names['main'],0x30000,count=100000)
    assert c.reg_read(UC_ARM_REG_PC)==0x30000 and c.reg_read(UC_ARM_REG_R0)==0
    header=ROOT/'tools/native_camera/native_freeze.h'
    (out/'manifest.json').write_text(json.dumps(dict(status='compiled_arm_freeze_recovery_fixtures_passed',
        header_sha256=hashlib.sha256(header.read_bytes()).hexdigest(),
        limitations=['Actual shared CPU header, explicit ptrace/wait/directory/clock service doubles.',
                     'No camera access, real thread freeze, full-owner proof or VFS/DMA drain.']),indent=2)+'\n')
    print('compiled ARM CPU barrier recovery fixtures passed')


if __name__=='__main__':main()
