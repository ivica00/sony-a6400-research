"""Directly trace TID 1004 execution when supplied with the category 3 subcmd 1 reply."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import struct
import json
import unicorn
import unicorn.arm_const as arm
from tools.research.probe_interpreter import load_guest_image
from src.a6400.execution.interpreter_probe import InterpreterProbe
from src.a6400.execution.guest_uname import extract_kernel_uts
from src.a6400.execution.guest_kuser import extract_kuser_template
from src.a6400.execution.guest_checkpoint import restore_checkpoint
from src.a6400.images.verified_content import VerifiedContent
from src.a6400.images.ext2_metadata import Ext2Metadata

folder = ROOT / 'artifacts/inventory'
manifest = json.loads((folder / 'guest-filesystem.json').read_text(encoding='utf-8'))
inventory = json.loads((folder / 'elf-inventory.json').read_text(encoding='utf-8'))['entries']
baseline = json.loads((folder / 'baseline.json').read_text(encoding='utf-8'))
expected_inputs = {item['path']: item['sha256'] for item in baseline['inputs']}

app = load_guest_image(manifest, inventory, '/usr/bin/im.elf')
interp = load_guest_image(manifest, inventory, app['interpreter'])

kernel = 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked/vmlinux.bin'
kernel_sha = expected_inputs[kernel]
uname_profile = extract_kernel_uts(ROOT / kernel, kernel_sha)
kuser_template = extract_kuser_template(ROOT / kernel, kernel_sha)

content_loader = VerifiedContent(ROOT, ROOT / 'firmware', expected_inputs)
nodes = {path: dict(node) for path, node in manifest['nodes'].items()}
boot_mount_data = json.loads((folder / 'boot-mount-trace.json').read_text(encoding='utf-8'))
major = boot_mount_data['devnodes_summary']['nflasha']['major']
for image in manifest['images']:
    source = Ext2Metadata(ROOT / image['path'], image['sha256'])
    indexed = source.index()
    for node in nodes.values():
        if node.get('image') != Path(image['path']).name:
            continue
        metadata = indexed[node['archive_path'] or '/']
        node_stat = {**metadata, 'image_sha256': image['sha256']}
        part_num = 7 if 'nflasha7' in image['path'] else 15
        node_stat['st_dev'] = (major << 8) | part_num
        node['stat_metadata'] = node_stat

filesystem = {'nodes': nodes, 'content_loader': content_loader,
              'urandom_open': True, 'urandom_entropy_policy': 'deterministic',
              'regular_inode_rdev': False, 'tmp_overlay': 'experimental-empty',
              'proc_overlay': 'experimental-empty', 'setting_overlay': 'experimental-empty',
              'readonly_image_times': False}

probe = InterpreterProbe(
    syscall_policy='threads', uname_profile=uname_profile,
    filesystem=filesystem, kuser_template=kuser_template,
    madvise_policy='private-anonymous-dontneed',
    backup_service_policy='preset-backed',
    graphics_service_policy='authentic-grm',
    null_page_policy='read-zero',
    hook_mode='fast',
    kmod_service_policy='verified-image',
    media_service_policy='authentic-sd',
    mmap_base=None,
    mmap_search_low=0x10000000
)

probe.prepare(app, interp, ['/usr/bin/im.elf'], stack_bottom=0x5e390000, stack_size=0x800000)

ckpt_path = ROOT / 'artifacts/checkpoints/boot-125m.ckpt'
print(f'[*] Restoring {ckpt_path}...')
restore_checkpoint(probe, ckpt_path)
print(f'[*] Checkpoint restored at instruction {probe.instructions:,}.')

t4 = probe.threads.threads[1004]
print(f'TID 1004 state: {t4.state}, blocked_uaddr: {getattr(t4, "blocked_uaddr", None)}')
print(f'TID 1004 PC: 0x{t4.regs[arm.UC_ARM_REG_PC]:08x}, SP: 0x{t4.regs[arm.UC_ARM_REG_SP]:08x}')

# Allocate and write reply to 0x8000103a
reply_queue = 0x8000103a
notify_queue = 0x8000103b
subcmd_payload = 1 | (4 << 16)
raw_ptr = probe.uipc.allocate_message(64)
probe.mu.mem_write(raw_ptr, struct.pack('<IBBHII', 0, 2, 1, 1, 0, 0)[:12])
reply_ptr = raw_ptr + 12
reply_data = struct.pack('<IIIIIIII', 3, subcmd_payload, reply_queue, 0, 0, 0, notify_queue, 0)
probe.mu.mem_write(reply_ptr, reply_data)
probe.uipc.enqueue_message(reply_queue, reply_ptr)
print(f'[+] Enqueued reply on 0x{reply_queue:08x} at 0x{reply_ptr:08x}')

# Wake TID 1004
woken = probe.threads.handle_uipc_wake(reply_queue)
print(f'[+] Woken: {woken}, TID 1004 state now: {t4.state}')

# Save current TID 1008 and restore TID 1004 as active
probe.threads.save_context(probe.mu)
probe.threads.threads[probe.threads.current_tid].state = 'runnable'
probe.threads.restore_context(probe.mu, 1004, probe.kuser)
entry_pc = t4.regs[arm.UC_ARM_REG_PC]
cpsr = t4.regs[arm.UC_ARM_REG_CPSR]
if cpsr & 0x20:
    entry_pc |= 1
probe.entry = entry_pc
print(f'[+] Switched active TID to 1004, entry PC=0x{entry_pc:08x}')

# Hook to trace syscalls and prints
def on_syscall(probe_inst):
    pass

# Run 1,000,000 instructions
report = probe.run(instruction_budget=probe.instructions + 1000000, timeout_us=30000000)
print(f'[*] Run finished! Status: {report["status"]}')
print(f'[*] Instructions executed: {probe.instructions:,}')
print(f'[*] TID 1004 state: {t4.state}, PC: 0x{probe.mu.reg_read(arm.UC_ARM_REG_PC):08x}')
print(f'[*] Current TID: {probe.threads.current_tid}')

# Check stdout/stderr
stdout = b''.join(probe.stdio.stdout_log).decode('latin1', errors='replace')
stderr = b''.join(probe.stdio.stderr_log).decode('latin1', errors='replace')
if stdout:
    print(f'[*] Stdout:\n{stdout[-500:]}')
if stderr:
    print(f'[*] Stderr:\n{stderr[-500:]}')

# Check recent syscalls
for s in list(probe.report.get('serviced_syscalls', []))[-15:]:
    print('  ', s)
