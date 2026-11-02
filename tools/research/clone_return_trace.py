"""Hash-checked original libc clone return windows; no guest or host child is launched."""
import json

from project_paths import PROJECT_ROOT
from tools.research.mount_evidence import checked_input
from tools.research.startup_trace import analyze

SOURCE = 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha7_unpacked/lib/libc-2.11.2.so'


def main():
    inventory = json.loads((PROJECT_ROOT / 'artifacts/inventory/elf-inventory.json').read_text(encoding='utf-8'))
    expected = next(entry['sha256'] for entry in inventory['entries'] if entry['path'] == SOURCE)
    checked_input(PROJECT_ROOT, SOURCE, expected)
    report = analyze(PROJECT_ROOT / SOURCE, [], explicit_blocks=[
        ('clone setup, syscall and parent return', 0xa05a0, 0x4c),
        ('clone child dispatch and exit branch', 0xa05ec, 0x40),
    ])
    instructions = {row['address']: row for block in report['blocks'] for row in block['instructions']}
    for address, raw in {0xa05d4: '000000ef', 0xa05d8: '000050e3',
                         0xa061c: '04009de5', 0xa0620: '0fe0a0e1',
                         0xa0624: '08f09de4'}.items():
        if instructions[address]['bytes'] != raw:
            raise ValueError('Original libc clone-window preimage mismatch')
    report['kernel_contract_reference'] = 'https://raw.githubusercontent.com/torvalds/linux/v3.0/arch/arm/kernel/process.c'
    report['contract'] = 'copy_thread copies syscall registers, replaces child r0 with zero and sp with stack_start; CLONE_SETTLS selects supplied TLS'
    report['limitations'] = [
        'Static libc consumer and upstream contract comparison, not execution of Sony kernel copy_thread.',
        'General-register clone/switch subset; VFP/NEON state, signals and scheduler timing remain unvalidated.',
        'No runtime state, entropy, IPC message or display response is supplied.',
    ]
    output = PROJECT_ROOT / 'artifacts/execution/package-h-clone-return-static.json'
    output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(output)


if __name__ == '__main__':
    main()
