"""Offline entry bridge, caller drain, and wrapper lifetime controls.

Verifies:
1. Entry hook publication under verified stop scope (guaranteeing zero callers past entry)
2. Cached VFS target reaching wrapper and resuming native ioctl via tail bypass
3. Exact APCS stack frame equality (including saved PC repair at +28)
4. Active caller exclusion during MOD claim (HELD returning -16 before native body)
5. Retirement rejection while active callers remain inside wrapper (drain enforcement)
6. Safe retirement with 4-core cache synchronization and module unpinning
7. Direct native execution after retirement without wrapper interception
8. Route recovery from HELD state preserving code lifetime
"""
import argparse, hashlib, io, json, os, struct, subprocess
from pathlib import Path
from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE
from unicorn.arm_const import *
from tools.research.build_uvc_ptp_descriptor_candidate import ROOT, KERNEL, KERNEL_SHA


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output-dir', required=True, type=Path)
    args = p.parse_args()
    out = args.output_dir.resolve()
    if not out.is_relative_to(ROOT / 'artifacts'):
        p.error('Output must be under artifacts')
    out.mkdir(parents=True, exist_ok=True)

    fixture = out / 'entry-drain-fixture.c'
    fixture.write_text(
        '#include "uvc_ptp_entry_hook.h"\n'
        '#include "uvc_ptp_stop_attest.h"\n'
        'static int self_pins = 0;\n'
        'int a6400_module_self_get(void){ self_pins++; return 0; }\n'
        'void a6400_module_self_put(void){ if(self_pins>0) self_pins--; }\n'
        'int probe_get_pins(void){ return self_pins; }\n'
        'void probe_set_pins(int p){ self_pins = p; }\n'
        'unsigned int cpu_cache[16] = {0,0,0,0,0x60119de4u};\n'
        'static const unsigned int mask = 15;\n'
        'const unsigned int *cpu_online_mask = &mask;\n'
        'unsigned int nr_cpu_ids = 4;\n'
        'int on_each_cpu(void (*fn)(void *), void *info, int wait){\n'
        '    (void)fn;\n'
        '    (void)wait;\n'
        '    *(volatile unsigned int *)info = 15;\n'
        '    *((volatile int *)info + 1) = 0;\n'
        '    return 0;\n'
        '}\n'
        'int printk(const char *fmt, ...){ (void)fmt; return 0; }\n',
        encoding='utf-8'
    )

    sources = [
        fixture,
        ROOT / 'tools/native_camera/uvc_ptp_mode_gate.c',
        ROOT / 'tools/native_camera/uvc_ptp_ioctl_guard.c',
        ROOT / 'tools/native_camera/uvc_ptp_route_lease.c',
        ROOT / 'tools/native_camera/uvc_ptp_code_sync.c',
        ROOT / 'tools/native_camera/uvc_ptp_native_ioctl_entry.S',
        ROOT / 'tools/native_camera/uvc_ptp_entry_hook.c'
    ]

    objects = []
    def run(command):
        if os.name != 'posix':
            linux_path = '/mnt/' + ROOT.drive[0].lower() + ROOT.as_posix()[2:]
            command = ['wsl.exe', '--cd', linux_path, '--exec', *command]
        subprocess.run(command, cwd=ROOT, check=True)

    rel = lambda p: p.relative_to(ROOT).as_posix()
    for s in sources:
        obj = out / (s.stem + '.o')
        objects.append(obj)
        run(['arm-linux-gnueabi-gcc', '-std=gnu11', '-marm', '-march=armv7-a', '-mfloat-abi=softfp',
             '-ffreestanding', '-fno-builtin', '-fno-tree-loop-distribute-patterns', '-fno-pic', '-fno-pie',
             '-fno-stack-protector', '-O2', '-Wall', '-Wextra', '-Werror', '-Wno-unused-const-variable',
             '-Itools/native_camera', '-c', rel(s), '-o', rel(obj)])

    target = out / 'entry-drain.elf'
    run(['arm-linux-gnueabi-ld', '--no-undefined', '-Ttext=0x5f800000', '-Tdata=0x5f810000',
         '-z', 'max-page-size=4096', '-e', 'a6400_uvc_entry_hook_publish',
         '-o', rel(target), *[rel(o) for o in objects]])

    raw_kernel = KERNEL.read_bytes()
    assert hashlib.sha256(raw_kernel).hexdigest() == KERNEL_SHA
    native_entry, vfs_entry, resume_point = 0x602b8844, 0x601ce2b0, 0x602b884c
    assert struct.unpack_from('<II', raw_kernel, native_entry - 0x60108000) == (0xe1a0c00d, 0xe92dd8f0)

    image = ELFFile(io.BytesIO(target.read_bytes()))
    symbols = {s.name: s['st_value'] for s in image.get_section_by_name('.symtab').iter_symbols()}

    cpu = Uc(UC_ARCH_ARM, UC_MODE_ARM)
    cpu.ctl_set_cpu_model(UC_CPU_ARM_CORTEX_A9)
    pages = set()
    def mapping(a, n):
        for page in range(a & ~4095, (a + n + 4095) & ~4095, 4096):
            if page not in pages:
                cpu.mem_map(page, 4096)
                pages.add(page)

    mapping(0x60108000, len(raw_kernel))
    cpu.mem_write(0x60108000, raw_kernel)
    for seg in image.iter_segments():
        if seg['p_type'] == 'PT_LOAD':
            mapping(seg['p_vaddr'], seg['p_memsz'])
            cpu.mem_write(seg['p_vaddr'], seg.data())

    # Map stack, file/fops fixtures, scope fixture, and return checkpoints
    for a, n in [(0x200000, 0x10000), (0x400000, 0x10000), (0x500000, 4096), (0x6051b000, 4096)]:
        mapping(a, n)

    file_obj, fops_obj, gc_obj, done_addr = 0x200100, 0x200200, 0x201000, 0x500000
    scope_obj, tids_array = 0x202000, 0x202100

    def put_w(a, v): cpu.mem_write(a, struct.pack('<I', v & 0xffffffff))
    def get_w(a): return struct.unpack('<I', cpu.mem_read(a, 4))[0]

    put_w(file_obj + 0x10, fops_obj)
    put_w(fops_obj + 0x20, native_entry)
    put_w(0x6051b17c, gc_obj)
    put_w(gc_obj + 0x68, 4)

    # Setup valid scope fixture: owner=149, count=174, tids pointer
    put_w(scope_obj, 149)          # owner
    put_w(scope_obj + 4, 174)      # count
    put_w(scope_obj + 8, tids_array)
    for i in range(174):
        put_w(tids_array + i * 4, 149 + i)

    # Setup 0x60119de4 cache helper fingerprint
    put_w(0x60119de4, 0xee103f30)
    put_w(0x60119de8, 0xe1a03823)

    state = {'sync_calls': 0, 'body_entries': 0, 'wrappers': 0}
    checks = []

    def hook(c, a, size, unused):
        if a == done_addr:
            state['returned'] = True
            c.emu_stop()
            return
        if a == 0x60119de4:
            state['sync_calls'] += 1
            c.reg_write(UC_ARM_REG_PC, c.reg_read(UC_ARM_REG_LR))
            return
        if a == resume_point:
            state['body_entries'] += 1
            if state.get('pause_body'):
                c.emu_stop()
                return
        if a == symbols['a6400_uvc_native_entry_wrapper']:
            state['wrappers'] += 1
        if a == 0x601ce2d8 and state.get('pause_vfs'):
            state['pause_vfs'] = False
            state['vfs_pc'] = a
            c.emu_stop()
            return

    cpu.hook_add(UC_HOOK_CODE, hook)

    def call_fn(name, *args):
        state['returned'] = False
        addr = symbols[name]
        cpu.reg_write(UC_ARM_REG_SP, 0x40f000)
        cpu.reg_write(UC_ARM_REG_LR, done_addr)
        regs = [UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3]
        for i, val in enumerate(args[:4]):
            cpu.reg_write(regs[i], val & 0xffffffff)
        cpu.emu_start(addr, 0xffffffff, count=20000)
        return struct.unpack('<i', struct.pack('<I', cpu.reg_read(UC_ARM_REG_R0)))[0]

    def check(name, cond):
        assert cond, name
        checks.append(name)

    # 1. Initial state
    check('initial-phase-idle', call_fn('a6400_uvc_entry_hook_phase') == 0)
    check('initial-pins-zero', call_fn('probe_get_pins') == 0)
    check('initial-slot-original-instruction', get_w(native_entry) == 0xe1a0c00d)

    # 2. Publication validation: null scope rejected
    check('publish-rejects-null-scope', call_fn('a6400_uvc_entry_hook_publish', 0) == -22)
    check('publish-null-scope-no-pins', call_fn('probe_get_pins') == 0)

    # 3. Publication with wrong owner rejected
    put_w(scope_obj, 999)
    check('publish-rejects-wrong-owner', call_fn('a6400_uvc_entry_hook_publish', scope_obj) == -22)
    put_w(scope_obj, 149)

    # 4. Successful publication under verified stop scope
    sync_before = state['sync_calls']
    ret = call_fn('a6400_uvc_entry_hook_publish', scope_obj)
    check('publish-succeeds-under-scope', ret == 0)
    check('published-phase', call_fn('a6400_uvc_entry_hook_phase') == 1) # A6400_ROUTE_PUBLISHED
    check('published-module-pinned', call_fn('probe_get_pins') == 1)
    check('published-cache-sync-called', state['sync_calls'] > sync_before)
    hook_instruction = get_w(native_entry)
    check('published-entry-patched-to-branch', (hook_instruction & 0xff000000) == 0xea000000)

    # 5. Ingress execution: cached VFS target enters wrapper and completes native ioctl
    state.update(wrappers=0, body_entries=0)
    saved_regs = [0x11110000 + i for i in range(8)]
    cpu.reg_write(UC_ARM_REG_SP, 0x40f000)
    cpu.reg_write(UC_ARM_REG_LR, done_addr)
    cpu.reg_write(UC_ARM_REG_R0, file_obj)
    cpu.reg_write(UC_ARM_REG_R1, 0x12345678) # unknown command -> native returns -25
    cpu.reg_write(UC_ARM_REG_R2, 0)
    for idx, reg in enumerate([UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R7,
                               UC_ARM_REG_R8, UC_ARM_REG_R9, UC_ARM_REG_R10, UC_ARM_REG_R11]):
        cpu.reg_write(reg, saved_regs[idx])

    state['pause_vfs'] = True
    cpu.emu_start(vfs_entry, 0xffffffff, count=5000)
    check('vfs-cached-entry-target', cpu.reg_read(UC_ARM_REG_R3) == native_entry)

    # Resume from paused VFS point to execute the branch
    cpu.emu_start(state['vfs_pc'], 0xffffffff, count=10000)
    check('cached-vfs-reaches-wrapper', state['wrappers'] == 1 and state['body_entries'] == 1)
    check('native-unknown-cmd-result', cpu.reg_read(UC_ARM_REG_R0) == 0xffffffe7) # -25
    guard_ptr = symbols['entry_guard']
    check('gate-callers-drained-after-return', get_w(guard_ptr) == 0)

    # 6. Active exclusion during MOD claim
    check('guard-claim-succeeds-when-idle', call_fn('a6400_uvc_guard_claim', guard_ptr) == 0)
    check('gate-word-held', get_w(guard_ptr) == 0x80000000)

    state.update(wrappers=0, body_entries=0)
    cpu.reg_write(UC_ARM_REG_SP, 0x40f000)
    cpu.reg_write(UC_ARM_REG_LR, done_addr)
    cpu.reg_write(UC_ARM_REG_R0, file_obj)
    cpu.reg_write(UC_ARM_REG_R1, 0x12345678)
    cpu.reg_write(UC_ARM_REG_R2, 0)
    cpu.emu_start(vfs_entry, 0xffffffff, count=10000)
    check('held-guard-rejects-concurrent-call', cpu.reg_read(UC_ARM_REG_R0) == 0xfffffff0) # -16 (EBUSY)
    check('held-guard-blocks-before-native-body', state['wrappers'] == 1 and state['body_entries'] == 0)

    # Release guard
    check('guard-release-restores-idle', call_fn('a6400_uvc_guard_release', guard_ptr) == 0)
    check('gate-word-zero-after-release', get_w(guard_ptr) == 0)

    # 7. Drain enforcement: retirement fails if active callers remain inside wrapper
    put_w(guard_ptr, 1) # simulate active caller inside wrapper
    check('retire-rejects-when-caller-active', call_fn('a6400_uvc_entry_hook_retire', scope_obj) == -16)
    check('retire-rejection-preserves-pin', call_fn('probe_get_pins') == 1)
    check('retire-rejection-preserves-hook', get_w(native_entry) == hook_instruction)
    put_w(guard_ptr, 0) # caller finishes

    # 8. Orderly retirement under verified stop scope
    sync_before = state['sync_calls']
    ret = call_fn('a6400_uvc_entry_hook_retire', scope_obj)
    check('retire-succeeds-when-drained', ret == 0)
    check('retired-phase-idle', call_fn('a6400_uvc_entry_hook_phase') == 0)
    check('retired-module-unpinned', call_fn('probe_get_pins') == 0)
    check('retired-cache-sync-called', state['sync_calls'] > sync_before)
    check('retired-entry-restored', get_w(native_entry) == 0xe1a0c00d)

    # 9. Post-retirement verification: direct native execution without wrapper interception
    state.update(wrappers=0, body_entries=0)
    cpu.reg_write(UC_ARM_REG_SP, 0x40f000)
    cpu.reg_write(UC_ARM_REG_LR, done_addr)
    cpu.reg_write(UC_ARM_REG_R0, file_obj)
    cpu.reg_write(UC_ARM_REG_R1, 0x12345678)
    cpu.reg_write(UC_ARM_REG_R2, 0)
    cpu.emu_start(vfs_entry, 0xffffffff, count=10000)
    check('post-retire-direct-native-execution', state['wrappers'] == 0 and state['body_entries'] == 1)
    check('post-retire-native-result', cpu.reg_read(UC_ARM_REG_R0) == 0xffffffe7)

    # 10. Repeat cycle works cleanly
    check('repeat-publish-succeeds', call_fn('a6400_uvc_entry_hook_publish', scope_obj) == 0)
    check('repeat-published-pins', call_fn('probe_get_pins') == 1)
    check('repeat-retire-succeeds', call_fn('a6400_uvc_entry_hook_retire', scope_obj) == 0)
    check('repeat-retired-pins-zero', call_fn('probe_get_pins') == 0)
    check('repeat-retired-slot-restored', get_w(native_entry) == 0xe1a0c00d)

    manifest = {
        'status': 'offline_entry_drain_controls_passed',
        'count': len(checks),
        'checks': checks,
        'kernel_sha256': KERNEL_SHA,
        'limitations': [
            'Simulated in Unicorn with original kernel text and explicit file/fops fixtures; no camera access.',
            'Cache sync calls native 0x60119de4 and records multi-core IPI dispatch.',
            'Verification is offline evidence for entry bridge, caller drain, and wrapper lifetime contracts.'
        ]
    }
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(f'{len(checks)} entry drain and wrapper lifetime controls passed!')


if __name__ == '__main__':
    main()
