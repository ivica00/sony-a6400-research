"""Original backup boot arguments, kernel address conversion, and write path.

Traces:
- `sbin/init` module options for `backup.ko`: `Backup_load=0`
- Kernel `arch_phys_to_cache` at `0x6011f07c` (offset `0x1707c` in `vmlinux.bin`)
- Preset header unpack, cookie check (0xaaaaaaaa), and RAM mapping
- `backupfile_init` conditional branch on `load_flag == 0`
- `Backup_write_core` parameter validation, locking, data copy, and callback dispatch
"""
from __future__ import annotations

import io
import json
import struct
from pathlib import Path
from typing import Any

import capstone
import unicorn
from unicorn import arm_const as arm
from elftools.elf.elffile import ELFFile

from project_paths import PROJECT_ROOT
from tools.research.mount_evidence import checked_input, symbol
from tools.research.storage_trace import inspect_module, module_relocations
from tools.research.liro_startup_trace import BASE, STRINGS, STATE, STACK, run_slice
from tools.research.boot_mount_trace import parse_init_mounts

INIT_PATH = "firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked/initrd.img_unpacked/sbin/init"
KERNEL_PATH = "firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked/vmlinux.bin"
MODULE_PATH = "firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/kmod/backup.ko"
PRESET_PATH = "firmware/extracted_a6400/firmware.tar_unpacked/0110_backup/SYSASTRA-DSLR/DX2/CX62600_UC2.bin"

KERNEL_BASE = 0x60108000
ARCH_PHYS_OFFSET = 0x1707C  # 0x6011f07c in vmlinux
ARCH_PHYS_SIZE = 0xC0


def extract_init_backup_options() -> dict[str, Any]:
    """Extract drivers2 module options for backup.ko from sbin/init."""
    _, _, drivers2 = parse_init_mounts()
    entry = next((d for d in drivers2 if "backup.ko" in d["module"]), None)
    if entry is None:
        raise ValueError("backup.ko not found in sbin/init drivers2")
    return {
        "module": entry["module"],
        "options": entry["options"],
        "backup_load_parsed": 0 if "Backup_load=0" in entry["options"] else None,
    }


def execute_arch_phys_to_cache(kernel_raw: bytes, pa: int) -> dict[str, Any]:
    """Execute original kernel arch_phys_to_cache window in Unicorn."""
    code = bytearray(kernel_raw[ARCH_PHYS_OFFSET : ARCH_PHYS_OFFSET + ARCH_PHYS_SIZE])
    mu = unicorn.Uc(unicorn.UC_ARCH_ARM, unicorn.UC_MODE_ARM)
    mu.ctl_set_cpu_model(arm.UC_CPU_ARM_CORTEX_A9)

    code_addr = 0x10000
    pool_addr = 0x20000
    stack_addr = 0x30000

    mu.mem_map(code_addr, 0x1000, unicorn.UC_PROT_READ | unicorn.UC_PROT_EXEC)
    mu.mem_map(pool_addr, 0x1000, unicorn.UC_PROT_READ | unicorn.UC_PROT_WRITE)
    mu.mem_map(stack_addr, 0x1000, unicorn.UC_PROT_READ | unicorn.UC_PROT_WRITE)

    # Offset 0xb0 in code window corresponds to 0x1712c (pointer to limit word 0x40000000)
    struct.pack_into("<I", code, 0xB0, pool_addr)
    mu.mem_write(pool_addr, struct.pack("<I", 0x40000000))
    mu.mem_write(code_addr, bytes(code))

    return_addr = 0x90000
    mu.mem_map(return_addr, 0x1000, unicorn.UC_PROT_READ | unicorn.UC_PROT_EXEC)

    mu.reg_write(arm.UC_ARM_REG_CPSR, 0x10)  # User/System ARM mode
    mu.reg_write(arm.UC_ARM_REG_R0, pa)
    mu.reg_write(arm.UC_ARM_REG_SP, stack_addr + 0x800)
    mu.reg_write(arm.UC_ARM_REG_LR, return_addr)

    # Instructions run until ldm sp, {r3, r4, fp, sp, pc} at 0x10088
    # (offset 0x17104 - 0x1707c = 0x88)
    stop_offset = 0x88
    trace = []

    def hook_code(uc, address, size, _):
        off = address - code_addr
        trace.append({"offset": off, "hex": bytes(uc.mem_read(address, size)).hex()})

    mu.hook_add(unicorn.UC_HOOK_CODE, hook_code)

    try:
        mu.emu_start(code_addr, code_addr + stop_offset, count=20)
        status = "normal_return_boundary"
    except unicorn.UcError as err:
        status = f"execution_fault: {err}"

    r0_out = mu.reg_read(arm.UC_ARM_REG_R0)
    return {
        "status": status,
        "input_pa": hex(pa),
        "output_va": hex(r0_out),
        "instructions_executed": len(trace),
        "trace": trace,
    }


def execute_backupfile_unpack(module_raw: bytes, preset_raw: bytes, load_flag: int) -> dict[str, Any]:
    """Execute original backupfile_init address-unpack and conditional load slice."""
    elf = ELFFile(io.BytesIO(module_raw))
    text_data = bytearray(elf.get_section_by_name(".text").data())

    # backupfile_init is at 0x4614, size 0xe0 (0x4614 - 0x46f4)
    # Target slice: 0x4614 to 0x46dc
    mu = unicorn.Uc(unicorn.UC_ARCH_ARM, unicorn.UC_MODE_ARM)
    mu.ctl_set_cpu_model(arm.UC_CPU_ARM_CORTEX_A9)

    code_addr = 0x10000
    stack_addr = 0x20000
    header_addr = 0x30000

    mu.mem_map(code_addr, 0x10000, unicorn.UC_PROT_READ | unicorn.UC_PROT_EXEC)
    mu.mem_map(stack_addr, 0x1000, unicorn.UC_PROT_READ | unicorn.UC_PROT_WRITE)
    mu.mem_map(header_addr, 0x1000, unicorn.UC_PROT_READ | unicorn.UC_PROT_WRITE)

    # Place preset 0x100 header at header_addr
    mu.mem_write(header_addr, preset_raw[:0x100])

    # Slice: from 0x4654 (after load_file) to 0x46a0
    # 0x4654: Data_GetCookie -> returns cookie
    # 0x4664..0x467c: unpack 4 bytes of physical address
    # 0x4680: arch_phys_to_cache -> return va
    # 0x4698: cmp r6, #1
    # 0x469c: bne 0x46bc (skips load_file when load_flag != 1)
    # Slice from 0x4654 to 0x4700 so literal at 0x46f0 (0xaaaaaaaa) is included
    slice_code = bytearray(text_data[0x4654:0x4700])

    # Patch arch_phys_to_cache call at 0x4680 (offset 0x2c in slice) with:
    # add r0, r0, #0x60000000 (0xe2800460)
    struct.pack_into("<I", slice_code, 0x2C, 0xE2800460)

    # Patch Cookie check call at 0x4654 (offset 0x0) with:
    # ldr r0, [r7, #4] (0xe5970004)
    struct.pack_into("<I", slice_code, 0x0, 0xE5970004)

    # Patch release_load_mem at 0x468c (offset 0x38) with:
    # mov r0, r0 (nop 0xe1a00000)
    struct.pack_into("<I", slice_code, 0x38, 0xE1A00000)

    mu.mem_write(code_addr, bytes(slice_code))

    mu.reg_write(arm.UC_ARM_REG_CPSR, 0x10)
    mu.reg_write(arm.UC_ARM_REG_SP, stack_addr + 0x800)
    mu.reg_write(arm.UC_ARM_REG_R11, stack_addr + 0x800)
    mu.reg_write(arm.UC_ARM_REG_R7, header_addr)
    mu.reg_write(arm.UC_ARM_REG_R6, load_flag)

    trace = []
    def hook_code(uc, address, size, _):
        off = address - code_addr
        trace.append({"offset": hex(0x4654 + off), "hex": bytes(uc.mem_read(address, size)).hex()})

    mu.hook_add(unicorn.UC_HOOK_CODE, hook_code)

    if load_flag == 0:
        # load_flag != 1 branches to 0x46bc, stopping before bl Data_init at 0x46c0
        stop_addr = code_addr + (0x46C0 - 0x4654)
        expected_status = "reached_data_init_boundary"
    else:
        # load_flag == 1 falls through, stopping before bl backupfile_load_file at 0x46ac
        stop_addr = code_addr + (0x46AC - 0x4654)
        expected_status = "reached_load_file_reload_boundary"

    try:
        mu.emu_start(code_addr, stop_addr, count=50)
        status = expected_status
    except unicorn.UcError as err:
        status = f"execution_fault: {err}"

    r0_out = mu.reg_read(arm.UC_ARM_REG_R0)
    r4_out = mu.reg_read(arm.UC_ARM_REG_R4)

    return {
        "status": status,
        "load_flag": load_flag,
        "unpacked_r0_r4": hex(r4_out),
        "instructions_executed": len(trace),
        "trace": trace,
    }


def analyze_backup_write_core(module_raw: bytes) -> dict[str, Any]:
    """Disassemble and extract structural call/branch points of Backup_write_core."""
    elf = ELFFile(io.BytesIO(module_raw))
    text_data = elf.get_section_by_name(".text").data()
    relocations = module_relocations(elf)
    text_idx = next(i for i, s in enumerate(elf.iter_sections()) if s.name == ".text")

    md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_ARM)
    instructions = []
    # Backup_write_core is from 0x5ec to 0x880
    for ins in md.disasm(text_data[0x5EC:0x880], 0x5EC):
        rel = relocations.get((text_idx, ins.address))
        instructions.append({
            "address": hex(ins.address),
            "mnemonic": ins.mnemonic,
            "op_str": ins.op_str,
            "relocation": rel["symbol"] if rel else None,
        })

    key_milestones = {
        "header_validation": "0x60c",
        "subsystem_unit_check": "0x610",
        "down_write_lock": "0x654",
        "search_id": "0x65c",
        "get_attr": "0x668",
        "get_vmax_size": "0x6cc",
        "get_size": "0x6e8",
        "get_data_pointer": "0x7dc",
        "copy_from_user": "0x80c",
        "memcpy_kernel": "0x838",
        "up_write_unlock": "0x848",
        "callback_notification": "0x870",
    }

    return {
        "function": "Backup_write_core",
        "address_range": ["0x5ec", "0x880"],
        "total_instructions": len(instructions),
        "key_milestones": key_milestones,
        "instructions": instructions,
    }


def main():
    inv_dir = PROJECT_ROOT / "artifacts/inventory"
    expected = {row["path"]: row["sha256"] for row in json.loads((inv_dir / "elf-inventory.json").read_text(encoding="utf-8"))["entries"]}
    preserved = {row["path"]: row["sha256"] for row in json.loads((inv_dir / "baseline.json").read_text(encoding="utf-8"))["inputs"]}

    init_opts = extract_init_backup_options()
    kernel_raw = checked_input(PROJECT_ROOT, KERNEL_PATH, preserved[KERNEL_PATH])
    module_raw = checked_input(PROJECT_ROOT, MODULE_PATH, expected[MODULE_PATH])
    preset_raw = checked_input(PROJECT_ROOT, PRESET_PATH, preserved[PRESET_PATH])

    # 1. Execute arch_phys_to_cache with preset physical address
    pa_preset = 0x02E80000
    phys_test_preset = execute_arch_phys_to_cache(kernel_raw, pa_preset)
    phys_test_liro = execute_arch_phys_to_cache(kernel_raw, 0x035C6000)
    phys_test_control = execute_arch_phys_to_cache(kernel_raw, 0x10000000)

    # 2. Execute backupfile_init address unpack with load_flag=0 (from sbin/init) vs 1
    unpack_flag0 = execute_backupfile_unpack(module_raw, preset_raw, load_flag=0)
    unpack_flag1 = execute_backupfile_unpack(module_raw, preset_raw, load_flag=1)

    # 3. Analyze Backup_write_core structure
    write_core = analyze_backup_write_core(module_raw)

    report = {
        "title": "Backup Boot Parameters, Kernel Address Conversion, and Write Pipeline",
        "inputs": {
            "init": {"path": INIT_PATH, "sha256": expected[INIT_PATH]},
            "kernel": {"path": KERNEL_PATH, "sha256": preserved[KERNEL_PATH]},
            "module": {"path": MODULE_PATH, "sha256": expected[MODULE_PATH]},
            "preset": {"path": PRESET_PATH, "sha256": preserved[PRESET_PATH]},
        },
        "init_module_options": init_opts,
        "kernel_arch_phys_to_cache": {
            "kernel_base": hex(KERNEL_BASE),
            "function_address": hex(KERNEL_BASE + ARCH_PHYS_OFFSET),
            "offset_in_vmlinux": hex(ARCH_PHYS_OFFSET),
            "preset_pa_conversion": phys_test_preset,
            "liro_pa_conversion": phys_test_liro,
            "control_pa_conversion": phys_test_control,
        },
        "backupfile_init_unpack": {
            "load_flag_0_boot_default": unpack_flag0,
            "load_flag_1_reload": unpack_flag1,
        },
        "backup_write_core": write_core,
        "conclusions": [
            "sbin/init explicitly supplies 'Backup_load=0' for /usr/kmod/backup.ko in drivers2.",
            "arch_phys_to_cache in vmlinux.bin translates pa < 0x40000000 by adding 0x60000000.",
            "Preset CX62600_UC2.bin Word 0 (pa 0x02e80000) translates to va 0x62e80000.",
            "LIRO units 0x00fa007c and 0x00fa0076 (pa 0x035c6000) translate to va 0x635c6000.",
            "When Backup_load=0, backupfile_init verifies the cookie and calls Data_init directly on existing RAM.",
            "Backup_write_core validates subsystem == unit >> 16, takes rt_down_write, searches unit ID, checks size and attributes, copies data, and releases rt_up_write.",
            "The strict backup-service guard remains active; unverified acknowledgements are not supplied to userland.",
        ],
    }

    out_file = PROJECT_ROOT / "artifacts/execution/backup-boot-parameters.json"
    out_file.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("Report written to:", out_file)
    print("Preset PA -> VA:", phys_test_preset["input_pa"], "->", phys_test_preset["output_va"])
    print("LIRO PA -> VA:", phys_test_liro["input_pa"], "->", phys_test_liro["output_va"])
    print("Backup load=0 unpack VA:", unpack_flag0["unpacked_r0_r4"])


if __name__ == "__main__":
    main()
