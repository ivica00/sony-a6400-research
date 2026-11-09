"""Build/run MOD route lifetime policy with explicit barrier/pin fixtures."""
import argparse, hashlib, io, json, os, subprocess
from pathlib import Path
from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC
from tools.research.build_uvc_ptp_descriptor_candidate import ROOT

FIXTURE = r'''
#include "uvc_ptp_route_lease.h"
void *memset(void *p,int value,unsigned int count){volatile unsigned char *q=p;while(count--)*q++=(unsigned char)value;return p;}
__attribute__((noreturn,noinline)) void fail(int line){(void)line;for(;;){}}
#define assert(c) ((c)?(void)0:fail(__LINE__))
static unsigned int slot;
static int pins, barriers, pin_error, enter_error, leave_error, busy, recover_error, partial_leave, recoveries;
static int pin(void *p){(void)p;if(pin_error)return pin_error;assert(!pins);pins=1;return 0;}
static void unpin(void *p){(void)p;assert(pins && !barriers);pins=0;}
static int enter(void *p){(void)p;assert(pins && !barriers);if(enter_error)return enter_error;barriers=1;return 0;}
static int leave(void *p){(void)p;assert(pins && barriers);if(leave_error){if(partial_leave)barriers=0;return leave_error;}barriers=0;return 0;}
static int retirable(void *p){(void)p;assert(pins && barriers);return busy;}
static int recover(void *p){(void)p;assert(pins);++recoveries;if(recover_error)return recover_error;barriers=1;return 0;}
static struct a6400_route_lease fresh(void){
 struct a6400_route_lease r={0};
 pins=barriers=pin_error=enter_error=leave_error=busy=0;slot=0x1234;
 recover_error=partial_leave=recoveries=0;
 r.slot=&slot;r.original=0x1234;r.wrapper=0x5678;
 r.ops=(struct a6400_route_ops){pin,unpin,enter,leave,retirable,recover};return r;
}
int main(void){
 struct a6400_route_lease r=fresh();
 assert(a6400_route_publish(0)==-22);assert(a6400_route_retire(0)==-22);
 assert(a6400_route_retire(&r)==-16);
 assert(!a6400_route_publish(&r));assert(pins && !barriers && slot==r.wrapper);
 assert(a6400_route_publish(&r)==-16);
 busy=-16;assert(a6400_route_retire(&r)==-16);assert(pins && !barriers && slot==r.wrapper);
 busy=0;assert(!a6400_route_retire(&r));assert(!pins && !barriers && slot==r.original);
 assert(!a6400_route_publish(&r));assert(!a6400_route_retire(&r));
 r=fresh();pin_error=-12;assert(a6400_route_publish(&r)==-12);assert(!pins && slot==r.original);
 r=fresh();enter_error=-3;assert(a6400_route_publish(&r)==-3);assert(!pins && !barriers);
 r=fresh();slot=0x9999;assert(a6400_route_publish(&r)==-116);assert(pins && r.phase==A6400_ROUTE_HELD && slot==0x9999);
 r=fresh();slot=r.wrapper;assert(a6400_route_publish(&r)==-116);assert(pins && r.phase==A6400_ROUTE_HELD);
 r=fresh();leave_error=-5;assert(a6400_route_publish(&r)==-5);assert(pins && barriers && r.phase==A6400_ROUTE_HELD);
 r=fresh();assert(!a6400_route_publish(&r));enter_error=-3;assert(a6400_route_retire(&r)==-3);assert(pins && slot==r.wrapper);
 r=fresh();assert(!a6400_route_publish(&r));slot=0x9999;assert(a6400_route_retire(&r)==-116);assert(pins && r.phase==A6400_ROUTE_HELD && slot==0x9999);
 r=fresh();assert(!a6400_route_publish(&r));leave_error=-5;assert(a6400_route_retire(&r)==-5);assert(pins && barriers && slot==r.original && r.phase==A6400_ROUTE_HELD);
 assert(a6400_route_retire(&r)==-16);
 r=fresh();assert(a6400_route_recover(&r)==-16);
 r=fresh();leave_error=-5;partial_leave=1;
 assert(a6400_route_publish(&r)==-5);assert(pins && !barriers && r.barrier_held);
 recover_error=-3;assert(a6400_route_recover(&r)==-3);assert(pins && slot==r.wrapper);
 recover_error=0;leave_error=0;busy=-16;
 assert(a6400_route_recover(&r)==-16);assert(pins && !barriers && r.phase==A6400_ROUTE_HELD);
 busy=0;assert(!a6400_route_recover(&r));assert(!pins && !barriers && slot==r.original && recoveries==3);
 assert(!r.published);assert(a6400_route_recover(&r)==-16);
 assert(!a6400_route_publish(&r));assert(!a6400_route_retire(&r));
 r=fresh();assert(!a6400_route_publish(&r));leave_error=-5;
 assert(a6400_route_retire(&r)==-5);assert(slot==r.original && pins);
 leave_error=0;assert(!a6400_route_recover(&r));assert(!pins && !barriers);
 r=fresh();slot=r.wrapper;assert(a6400_route_publish(&r)==-116);
 assert(a6400_route_recover(&r)==-116);assert(pins && slot==r.wrapper && !barriers && !r.published);
 slot=r.original;assert(!a6400_route_recover(&r));assert(!pins);
 r=fresh();slot=0x9999;assert(a6400_route_publish(&r)==-116);
 assert(a6400_route_recover(&r)==-116);assert(pins && slot==0x9999);
 r.ops.barrier_recover=0;assert(a6400_route_recover(&r)==-95);assert(pins);
 r=fresh();leave_error=-5;assert(a6400_route_publish(&r)==-5);
 assert(a6400_route_recover(&r)==-5);assert(pins && r.phase==A6400_ROUTE_HELD && slot==r.original);
 leave_error=0;assert(!a6400_route_recover(&r));assert(!pins);
 return 0;
}
'''


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output-dir', type=Path, required=True)
    out = p.parse_args().output_dir.resolve()
    if not out.is_relative_to(ROOT / 'artifacts'):
        p.error('Output must be under artifacts')
    out.mkdir(parents=True, exist_ok=True)
    fixture = out / 'route-lease-fixture.c'
    fixture.write_text(FIXTURE)
    def run(command):
        if os.name == 'nt':
            command = ['wsl.exe', '--cd', '/mnt/' + ROOT.drive[0].lower() + ROOT.as_posix()[2:], '--exec', *command]
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        return result.stdout
    rel = lambda path: path.relative_to(ROOT).as_posix()
    source = ROOT / 'tools/native_camera/uvc_ptp_route_lease.c'
    binary = out / 'route-lease-fixture'
    common = ['-O2', '-Wall', '-Wextra', '-Werror', '-Itools/native_camera']
    run(['arm-linux-gnueabi-gcc', *common, '-marm', '-march=armv7-a', '-mfloat-abi=softfp',
         '-ffreestanding', '-fno-builtin', '-fno-pie', '-fno-pic', '-fno-stack-protector',
         '-nostdlib', '-static', '-Wl,--build-id=none,-Ttext=0x10000,-e,main',
         rel(fixture), rel(source), '-o', rel(binary)])
    elf = ELFFile(io.BytesIO(binary.read_bytes()))
    names = {s.name: s['st_value'] for s in elf.get_section_by_name('.symtab').iter_symbols()}
    cpu = Uc(UC_ARCH_ARM, UC_MODE_ARM)
    cpu.mem_map(0, 0x40000)
    cpu.mem_map(0x400000, 0x10000)
    for segment in elf.iter_segments():
        if segment['p_type'] == 'PT_LOAD':
            cpu.mem_write(segment['p_vaddr'], segment.data())
    def hook(c, address, size, unused):
        if address == names['fail']:
            raise AssertionError('Fixture assertion at line ' + str(c.reg_read(UC_ARM_REG_R0)))
    cpu.hook_add(UC_HOOK_CODE, hook)
    cpu.reg_write(UC_ARM_REG_SP, 0x40f000)
    cpu.reg_write(UC_ARM_REG_LR, 0x30000)
    cpu.emu_start(names['main'], 0x30000, count=100000)
    assert cpu.reg_read(UC_ARM_REG_PC) == 0x30000 and cpu.reg_read(UC_ARM_REG_R0) == 0, (hex(cpu.reg_read(UC_ARM_REG_PC)), hex(cpu.reg_read(UC_ARM_REG_R0)))
    result = 'compiled ARM route lease lifecycle fixture checks passed'
    run(['arm-linux-gnueabi-gcc', *common, '-marm', '-march=armv7-a', '-mfloat-abi=softfp',
         '-ffreestanding', '-fno-builtin', '-c', rel(source), '-o', rel(out / 'route-lease-arm.o')])
    (out / 'manifest.json').write_text(json.dumps(dict(
        status='compiled_arm_policy_fixtures_passed', result=result.strip(),
        source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        limitations=['Compiled MOD ARM policy executed in Unicorn, not original firmware behavior.',
                     'Barrier, pin and retirable callbacks are explicit fixtures.',
                     'No actual kernel route write or safe physical publication proof.',
                     'Recovery barrier callback must rebuild complete quiescence after partial resume.',
                     'Not integrated into shared module; no physical barrier provider.']), indent=2) + '\n')
    print(result.strip())


if __name__ == '__main__':
    main()
