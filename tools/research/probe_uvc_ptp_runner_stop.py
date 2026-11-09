"""Execute compiled runner STOP permission policy with failure recorders."""
import hashlib
import json
import os
import subprocess
from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_SP, UC_ARM_REG_LR
from tools.research.build_uvc_ptp_descriptor_candidate import ROOT


def main():
    out = ROOT / 'artifacts/analysis/uvc-ptp-runner-stop-e0215'
    out.mkdir(parents=True, exist_ok=True)
    fixture = out / 'fixture.c'
    fixture.write_text('''#include "uvc_ptp_runner_stop.h"
struct scenario {int stop_result,query_result,field,value,stops,queries;};
static int stop(void *p){struct scenario *s=p;s->stops++;return s->stop_result;}
static int query(void *p,int state[4]){struct scenario *s=p;unsigned i;s->queries++;for(i=0;i<4;i++)state[i]=0;if(s->field>=0 && s->field<4)state[s->field]=s->value;return s->query_result;}
unsigned probe(int stop_result,int query_result,int field,int value){
struct scenario s={stop_result,query_result,field,value,0,0};
struct a6400_runner_stop_ops ops={stop,query};int state[4];
unsigned allowed=a6400_runner_stop_verified(&ops,&s,state);
return allowed | ((unsigned)s.stops<<8) | ((unsigned)s.queries<<16);
}
''')
    obj, target = out / 'fixture.o', out / 'fixture.elf'
    def run(command):
        if os.name == 'nt':
            command = ['wsl.exe', '--cd', '/mnt/' + ROOT.drive[0].lower() + ROOT.as_posix()[2:], '--exec', *command]
        subprocess.run(command, cwd=ROOT, check=True)
    rel = lambda p: p.relative_to(ROOT).as_posix()
    run(['arm-linux-gnueabi-gcc', '-marm', '-march=armv7-a', '-mfloat-abi=softfp', '-O2', '-Wall', '-Wextra', '-Werror', '-ffreestanding', '-fno-builtin', '-fno-stack-protector', '-Itools/native_camera', '-c', rel(fixture), '-o', rel(obj)])
    run(['arm-linux-gnueabi-ld', '-e', 'probe', '-Ttext=0x100000', '-z', 'max-page-size=4096', rel(obj), '-o', rel(target)])
    c = Uc(UC_ARCH_ARM, UC_MODE_ARM)
    with target.open('rb') as f:
        e = ELFFile(f)
        for segment in e.iter_segments():
            if segment['p_type'] == 'PT_LOAD' and segment['p_memsz']:
                base = segment['p_vaddr'] & ~4095
                end = (segment['p_vaddr'] + segment['p_memsz'] + 4095) & ~4095
                c.mem_map(base, end-base)
                c.mem_write(segment['p_vaddr'], segment.data())
        entry = e.header['e_entry']
    c.mem_map(0x200000, 0x10000)
    c.mem_map(0x300000, 4096)
    reached = []
    def hook(cpu, address, size, unused):
        if address == 0x300000:
            reached.append(True)
            cpu.emu_stop()
    c.hook_add(UC_HOOK_CODE, hook)
    cases = [('idle', 0, 0, -1, 0, True), ('stop-fails', -16, 0, -1, 0, False), ('status-fails', 0, -5, -1, 0, False)]
    cases += [(name, 0, 0, field, value, False) for field, name, value in [(0, 'active', 2), (0, 'held', 3), (1, 'pinned', 1), (2, 'hook-live', 15), (3, 'retained-error', -16)]]
    checks = []
    for name, stop, query, field, value, allowed in cases:
        reached.clear()
        for reg, arg in zip((UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3), (stop, query, field, value)):
            c.reg_write(reg, arg & 0xffffffff)
        c.reg_write(UC_ARM_REG_SP, 0x20f000)
        c.reg_write(UC_ARM_REG_LR, 0x300000)
        c.emu_start(entry, 0xffffffff, count=2000)
        result = c.reg_read(UC_ARM_REG_R0)
        expected = int(allowed) | (1 << 8) | ((0 if stop else 1) << 16)
        assert reached and result == expected, (name, result, expected)
        checks.append(dict(name=name, allowed=allowed, stop_calls=1, status_calls=0 if stop else 1))
    (out / 'manifest.json').write_text(json.dumps(dict(status='compiled_runner_stop_policy_passed', checks=checks, header_sha256=hashlib.sha256((ROOT/'tools/native_camera/uvc_ptp_runner_stop.h').read_bytes()).hexdigest(), limitations=['STOP/status services are scenario recorders; original kernel teardown does not execute.', 'Permission helper verified; live blocked ioctl, FD retention, signal behavior and receipt recovery are not proven.']), indent=2) + '\n')
    print(f'{len(checks)} compiled runner STOP cases passed')


if __name__ == '__main__':
    main()
