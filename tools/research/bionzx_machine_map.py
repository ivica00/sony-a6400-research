"""Map preserved BIONZ X packages and optionally replay an updater prefix offline.

Package configuration is never represented as live /proc or /setting evidence.
No camera, executable updater, host mount, or original-build execution hook is used.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import struct
from pathlib import Path

from capstone import CS_ARCH_ARM, CS_MODE_ARM, Cs
from capstone.arm_const import ARM_OP_IMM, ARM_OP_MEM, ARM_OP_REG, ARM_REG_PC
from elftools.elf.elffile import ELFFile

from src.a6400.execution.arm_atags import parse_mem_parameters
from src.a6400.execution.kernel_backing import KernelBacking, KernelImage, KernelSymbolTable
from src.a6400.execution.machine_contract import UpdaterBootContract, recover_machine_descriptor
from src.a6400.execution.nflasha_boot_set import NflashaBootSet, detect_image_format
from src.a6400.execution.unicorn_machine import (
    PL011_FR_RXFE, PL011_FR_TXFE, PL011_ID_REGS, UnicornMachine,
)
from src.a6400.execution.zve10_uvc_enablement import hash_file
from tools.research.decode_kernel_kallsyms import decode

ROOT = Path(__file__).resolve().parents[2]
DEV = Path("firmware.tar_unpacked") / "0700_part_image" / "dev"
UPDATER = Path("firmware.tar_unpacked") / "0400_updater" / "dev" / "nflasha1"
KERNEL_BASE = 0x60108000
SELECTED_SYMBOLS = (
    "_stext", "_etext", "linux_banner", "ret_to_user", "__pabt_usr",
    "__dabt_usr", "__pabt_svc", "__dabt_svc", "do_PrefetchAbort",
    "do_page_fault", "v7_early_abort", "cpu_v7_switch_mm", "swapper_pg_dir",
    "cxd900x0_map_io", "cxd900x0_init_irq", "cxd900x0_init_timer",
    "ext_timer_setup",
)


def checked_path(root: Path, relative: Path | str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError(f"Input escapes its declared package: {relative}")
    return path


def checked_bytes(path: Path, expected_sha256: str) -> bytes:
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError(f"Input SHA-256 mismatch: {path}")
    return raw


def mount_configuration(text: str) -> list[dict]:
    result = []
    seen = set()
    for line in text.splitlines():
        line = line.partition("#")[0].strip()
        if not line:
            continue
        fields = line.split()
        if len(fields) != 5 or not re.fullmatch(r"/dev/nflasha[0-9]+", fields[0]):
            raise ValueError("Malformed mount.conf row")
        device, mount, kind, size, cluster = fields
        size, cluster = int(size, 10), int(cluster, 10)
        if device in seen or size < 0 or cluster < 0:
            raise ValueError("Duplicate device or invalid mount.conf geometry")
        seen.add(device)
        result.append(dict(device=device, mount=mount, filesystem=kind,
                           bytes=size, cluster_bytes=cluster))
    if not result:
        raise ValueError("Empty mount configuration")
    return result


def partition_configuration(text: str) -> list[dict]:
    result = []
    device = None
    for line in text.splitlines():
        match = re.match(r"\s*#\s*(/dev/nflasha[0-9]+)\b", line)
        if match:
            device = match[1]
        content = line.partition("#")[0].strip()
        if not content:
            continue
        fields = content.split(",")
        if device is None or len(fields) != 4:
            raise ValueError("Partition row has no unambiguous device label")
        start, size, kind, flags = (int(value.strip(), 0) for value in fields)
        if min(start, size, kind, flags) < 0 or start + size > 1 << 32:
            raise ValueError("Invalid partition extent")
        if any(row["device"] == device for row in result):
            raise ValueError("Duplicate partition device")
        result.append(dict(device=device, start=start, bytes=size, type=kind, flags=flags))
        device = None
    if not result:
        raise ValueError("Empty partition configuration")
    occupied = sorted((row["start"], row["start"] + row["bytes"])
                      for row in result if row["bytes"])
    if any(left[1] > right[0] for left, right in zip(occupied, occupied[1:])):
        raise ValueError("Overlapping partition extents")
    return result


def image_bytes(raw: bytes, address: int, size: int) -> bytes:
    offset = address - KERNEL_BASE
    if offset < 0 or size < 0 or offset + size > len(raw):
        raise ValueError(f"Kernel range is not file-backed: {address:#x}+{size:#x}")
    return raw[offset:offset + size]


def call_arguments(raw: bytes, symbols: dict[str, int], caller: str, callee: str) -> dict:
    """Resolve constants at a direct ARM call, refusing intervening control flow."""
    address, target = symbols[caller], symbols[callee]
    decoder = Cs(CS_ARCH_ARM, CS_MODE_ARM)
    decoder.detail = True
    registers = {}
    next_symbol = min((value for value in symbols.values() if value > address),
                      default=address + 512)
    size = min(512, next_symbol - address)
    for instruction in decoder.disasm(image_bytes(raw, address, size), address):
        operands = instruction.operands
        if instruction.mnemonic == "bl":
            if len(operands) == 1 and operands[0].type == ARM_OP_IMM and operands[0].imm == target:
                return {"call_pc": instruction.address, "callee": callee,
                        "registers": {instruction.reg_name(reg): value
                                      for reg, value in registers.items()}}
            raise ValueError(f"Unresolved preceding call in {caller}")
        if instruction.mnemonic.startswith("b") and instruction.mnemonic != "bic":
            raise ValueError(f"Nonlinear argument setup in {caller}")
        update = None
        if len(operands) == 2 and operands[0].type == ARM_OP_REG:
            destination = operands[0].reg
            if instruction.mnemonic == "mov" and operands[1].type == ARM_OP_IMM:
                update = destination, operands[1].imm & 0xFFFFFFFF
            elif instruction.mnemonic == "mov" and operands[1].type == ARM_OP_REG:
                if operands[1].reg in registers:
                    update = destination, registers[operands[1].reg]
            elif (instruction.mnemonic == "ldr" and operands[1].type == ARM_OP_MEM
                  and operands[1].mem.base == ARM_REG_PC and not operands[1].mem.index):
                literal = instruction.address + 8 + operands[1].mem.disp
                update = destination, struct.unpack("<I", image_bytes(raw, literal, 4))[0]
        _, written = instruction.regs_access()
        for register in written:
            registers.pop(register, None)
        if update is not None:
            registers[update[0]] = update[1]
    raise ValueError(f"No bounded direct call from {caller} to {callee}")


def mmio_contract(raw: bytes, symbols: dict[str, int]) -> dict:
    setup = call_arguments(raw, symbols, "cxd900x0_map_io", "iotable_init")
    registers = setup["registers"]
    pointer, count = registers.get("r0"), registers.get("r1")
    if pointer is None or count is None or not 1 <= count <= 32:
        raise ValueError("Unresolved/bounded iotable_init arguments")
    table = image_bytes(raw, pointer, count * 16)
    mappings = []
    for offset in range(0, len(table), 16):
        virtual, pfn, size, kind = struct.unpack_from("<4I", table, offset)
        physical = pfn << 12
        if (virtual % 4096 or size == 0 or size % 4096
                or physical + size > 1 << 32 or virtual + size > 1 << 32):
            raise ValueError("Invalid static map_desc geometry")
        mappings.append(dict(virtual=virtual, physical=physical, bytes=size,
                             stored_type=kind))
    gic = call_arguments(raw, symbols, "cxd900x0_init_irq", "gic_init")
    if any(name not in gic["registers"] for name in ("r0", "r1", "r2", "r3")):
        raise ValueError("Unresolved gic_init arguments")
    return {"tier": "static ARM instructions and map_desc data, not live MMIO",
            "map_setup": setup, "table_address": pointer, "mappings": mappings,
            "gic_setup": gic,
            "type_caveat": "The map_io code overwrites stored map types before iotable_init."}


def timer_context(raw: bytes, symbols: dict[str, int]) -> dict:
    address = symbols["ext_timer_setup"]
    decoder = Cs(CS_ARCH_ARM, CS_MODE_ARM)
    decoder.detail = True
    candidates = []
    for instruction in decoder.disasm(image_bytes(raw, address, 48), address):
        ops = instruction.operands
        if (instruction.mnemonic != "ldr" or len(ops) != 2 or ops[1].type != ARM_OP_MEM
                or ops[1].mem.base != ARM_REG_PC or ops[1].mem.index):
            continue
        literal = instruction.address + 8 + ops[1].mem.disp
        pointer = struct.unpack("<I", image_bytes(raw, literal, 4))[0]
        if not KERNEL_BASE <= pointer <= KERNEL_BASE + len(raw) - 12:
            continue
        base = struct.unpack("<I", image_bytes(raw, pointer + 8, 4))[0]
        if 0xF0000000 <= base <= 0xFFFFF000 and base % 4096 == 0:
            candidates.append({"load_pc": instruction.address, "literal_address": literal,
                               "context": pointer, "base_field_offset": 8, "base": base})
    if len(candidates) != 1:
        raise ValueError("No unique static ext_timer_setup context/base candidate")
    return {**candidates[0], "tier": "static timer-context reference, not a live timer observation"}


def direct_calls(raw: bytes, symbols: dict[str, int], caller: str, callee: str) -> list[dict]:
    address, target = symbols[caller], symbols[callee]
    end = min(value for value in symbols.values() if value > address)
    if end - address > 4096:
        raise ValueError(f"Function exceeds the direct-call analysis bound: {caller}")
    decoder = Cs(CS_ARCH_ARM, CS_MODE_ARM)
    decoder.detail = True
    return [{"call_pc": instruction.address, "return_pc": instruction.address + 4}
            for instruction in decoder.disasm(image_bytes(raw, address, end - address), address)
            if instruction.mnemonic == "bl" and len(instruction.operands) == 1
            and instruction.operands[0].type == ARM_OP_IMM
            and instruction.operands[0].imm == target]


def kernel_report(raw: bytes) -> dict:
    decoded = decode(raw)
    symbols = KernelSymbolTable.from_kallsyms(raw)
    image = KernelImage(raw)
    verification = KernelBacking(image, symbols).verify()
    if not verification["linux_banner_symbol_matches_file"] or not verification["text_range_valid"]:
        raise ValueError("Kernel backing verification failed")
    sites = {}
    for name in SELECTED_SYMBOLS:
        address = symbols.symbols.get(name)
        sites[name] = (None if address is None else
                       {"virtual": address, "file_offset": address - KERNEL_BASE})
    cp15 = {}
    start = symbols.address("v7_early_abort")
    expected = {"dfsr": 0xEE151F10, "dfar": 0xEE160F10,
                "ifar": 0xEE160F50, "ifsr": 0xEE151F30}
    for name, word in expected.items():
        matches = [start + offset for offset in range(0, 64, 4)
                   if struct.unpack("<I", image_bytes(raw, start + offset, 4))[0] == word]
        if len(matches) != 1:
            raise ValueError(f"Ambiguous or missing original CP15 {name} instruction")
        cp15[name] = matches[0]
    ret = symbols.address("ret_to_user")
    ret_words = [struct.unpack("<I", image_bytes(raw, ret + offset, 4))[0]
                 for offset in range(0, 0x34, 4)]
    return {
        "sha256": image.sha256, "bytes": len(raw), "banner": image.banner_string(),
        "symbol_count": decoded["symbol_count"], "unique_symbol_names": len(symbols),
        "selected_symbols": sites,
        "machine": recover_machine_descriptor(raw, virtual_base=KERNEL_BASE,
                                               image_sha256=image.sha256).as_dict(),
        "mmio": mmio_contract(raw, symbols.symbols), "cp15_fault_read_sites": cp15,
        "timer_context": timer_context(raw, symbols.symbols),
        "ret_to_user_words": ret_words,
        "handle_mm_fault_calls": direct_calls(raw, symbols.symbols, "do_page_fault",
                                              "handle_mm_fault"),
        "ttbr0_opcode_candidates": UnicornMachine.scan_ttbr0_write_sites(raw, KERNEL_BASE),
        "ttbr0_scan_caveat": "Opcode candidates, not executed sites; the existing scan can also match an overlapping Thumb encoding beside an ARM instruction.",
        "embedded_config": "IKCFG_ST present" if b"IKCFG_ST" in raw else "No IKCFG_ST anchor found; configuration unknown",
        "symbols": decoded,
    }


def component_identity(path: Path) -> dict:
    raw = path.read_bytes()
    elf = ELFFile(io.BytesIO(raw))
    if elf.elfclass != 32 or not elf.little_endian or elf["e_machine"] != "EM_ARM":
        raise ValueError(f"Not ELF32 little-endian ARM: {path}")
    patterns = (rb"BusyBox v[ -~]{1,140}",
                rb"GNU C Library stable release version [^\x00\n]{1,160}")
    versions = sorted({match.group().decode("ascii")
                       for pattern in patterns for match in re.finditer(pattern, raw)})
    return {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
            "elf_type": elf["e_type"], "eabi": elf["e_flags"] >> 24,
            "entry": elf["e_entry"], "version_strings": versions}


def package_report(root: Path, kernel_sha256: str) -> dict:
    root = root.resolve()
    raw = checked_bytes(checked_path(root, DEV / "nflasha3_unpacked" / "vmlinux.bin"),
                        kernel_sha256)
    mounts_path = checked_path(root, "firmware.tar_unpacked/0100_config/mount.conf")
    part_path = checked_path(root, "firmware.tar_unpacked/0300_partconf/partinf.conf")
    mounts = mount_configuration(mounts_path.read_text(encoding="ascii"))
    partitions = partition_configuration(part_path.read_text(encoding="latin1"))
    sizes = {row["device"]: row["bytes"] for row in mounts}
    if any(sizes.get(row["device"]) != row["bytes"] for row in partitions):
        raise ValueError("Partition and mount configuration sizes disagree")
    result = {
        "tier": "packaged firmware, not a camera capture",
        "kernel": kernel_report(raw),
        "mount_configuration": {"identity": hash_file(mounts_path), "rows": mounts},
        "partition_configuration": {"identity": hash_file(part_path), "rows": partitions},
        "rootfs": {},
        "packaged_images": {},
        "live": {name: None for name in
                 ("/proc/version", "/proc/partitions", "/proc/kallsyms",
                  "/proc/cmdline", "/proc/iomem", "/setting inventory")},
    }
    for label, relative in (("main", DEV / "nflasha7_unpacked"),
                            ("updater", UPDATER.parent / "nflasha1_unpacked" /
                             "boot" / "initrd.img_unpacked")):
        folder = checked_path(root, relative)
        if not folder.is_dir():
            result["rootfs"][label] = {"status": "not_preserved"}
            continue
        result["rootfs"][label] = {
            "components": {name: component_identity(checked_path(root, relative / name))
                           for name in ("bin/busybox", "lib/libc-2.11.2.so", "lib/ld-2.11.2.so")},
            "version_file": checked_path(root, relative / "version.txt").read_text(encoding="ascii").strip(),
        }
    for name in ("nflasha3", "nflasha7", "nflasha15"):
        path = checked_path(root, DEV / name)
        with path.open("rb") as stream:
            prefix = stream.read(4096)
        result["packaged_images"][name] = {
            "identity": hash_file(path), "format": detect_image_format(prefix),
            "configured_partition_bytes": sizes[f"/dev/{name}"],
            "tier": "packaged image; not the owner's physical partition"}
    cmdline = checked_path(root, "firmware.tar_unpacked/0800_appli/setting/kemco.txt")
    result["main_boot_parameters"] = {
        "identity": hash_file(cmdline), "text": cmdline.read_text(encoding="ascii").strip(),
        "memory_parameters": parse_mem_parameters(cmdline.read_text(encoding="ascii")),
        "tier": "packaged /setting input, not /proc/cmdline or captured ATAGS"}
    settings = checked_path(root, "firmware.tar_unpacked/0800_appli/setting")
    result["packaged_setting_structure"] = [
        {"path": str(path.relative_to(settings)), "directory": path.is_dir()}
        for path in sorted(settings.rglob("*"))]
    result["dtb_files"] = [str(path.relative_to(root)) for path in sorted(root.rglob("*.dtb"))]
    result["dtb_caveat"] = "No supplied DTB does not prove that the live boot never uses a DTB."
    return result


def prefix_replay(contract: UpdaterBootContract, *, limit: int, uart_base: int | None = None) -> dict:
    from unicorn import (UC_ARCH_ARM, UC_HOOK_CODE, UC_HOOK_MEM_READ, UC_HOOK_MEM_UNMAPPED,
                         UC_HOOK_MEM_WRITE, UC_MEM_WRITE, UC_MODE_ARM, UC_QUERY_TIMEOUT, Uc, UcError)
    from unicorn.arm_const import (UC_ARM_REG_CPSR, UC_ARM_REG_PC, UC_ARM_REG_R0,
                                   UC_ARM_REG_R1, UC_ARM_REG_R2, UC_CPU_ARM_CORTEX_A9)
    if not 1 <= limit <= 2_000_000:
        raise ValueError("Prefix instruction limit must be 1..2000000")
    if uart_base is not None and (uart_base % 4096 or not 0xF0000000 <= uart_base < 0xFFFFF000):
        raise ValueError("Invalid explicitly selected UART window")
    if contract.banks[0][0] != 0 or contract.banks[0][1] < 32 * 1024 * 1024:
        raise ValueError("The prefix RAM fixture is not within the package's first bank")
    cpu = Uc(UC_ARCH_ARM, UC_MODE_ARM)
    cpu.ctl_set_cpu_model(UC_CPU_ARM_CORTEX_A9)
    cpu.mem_map(0, 32 * 1024 * 1024)
    for address, raw in ((contract.load_addresses["kernel_load"], contract.raw_kernel),
                         (contract.load_addresses["initrd_load"], contract.initrd),
                         (contract.load_addresses["boot_params"], contract.sony_payload)):
        if address < 0 or address + len(raw) > 32 * 1024 * 1024:
            raise ValueError("Boot input is outside the declared RAM fixture")
        cpu.mem_write(address, raw)
    for register, value in ((UC_ARM_REG_R0, 0), (UC_ARM_REG_R1, contract.machine.machine_id),
                            (UC_ARM_REG_R2, contract.load_addresses["boot_params"]),
                            (UC_ARM_REG_CPSR, 0xD3)):
        cpu.reg_write(register, value)
    report = {
        "tier": "original kernel prefix with reconstructed registers and zero-initialized RAM fixture",
        "raw_kernel_sha256": hashlib.sha256(contract.raw_kernel).hexdigest(),
        "instruction_limit": limit, "instructions": 0, "timeout_us": 10_000_000,
        "cpu_fixture": "Cortex-A9", "ram_fixture_bytes": 32 * 1024 * 1024,
        "uart_fixture": uart_base, "mmio": [], "mmio_count": 0,
        "mmio_log_truncated": False, "serial_hex": "", "stop": None,
        "code_patches": 0, "inherited_kernel_hooks": 0, "camera_access": False,
    }
    serial = bytearray()

    def code(uc, address, size, user):
        report["instructions"] += 1

    def unmapped(uc, access, address, size, value, user):
        report["stop"] = {"reason": "unmapped_access", "access": access,
                          "address": address, "size": size,
                          "pc": uc.reg_read(UC_ARM_REG_PC)}
        return False

    def uart(uc, access, address, size, value, user):
        offset = address - uart_base
        write = access == UC_MEM_WRITE
        report["mmio_count"] += 1
        supported = size == 4 and (
            (write and offset in (0, 4, 0x24, 0x28, 0x2C, 0x30, 0x38, 0x44))
            or (not write and (offset == 0x18 or offset in PL011_ID_REGS)))
        if len(report["mmio"]) < 64:
            report["mmio"].append({"address": address, "size": size,
                                   "write": write, "value": value if write else None,
                                   "supported": supported})
        else:
            report["mmio_log_truncated"] = True
        if not supported:
            report["stop"] = {"reason": "unsupported_uart_register", "address": address,
                              "size": size, "write": write, "pc": uc.reg_read(UC_ARM_REG_PC)}
            uc.emu_stop()
        elif write:
            if offset == 0:
                serial.append(value & 255)
        else:
            read_value = PL011_FR_TXFE | PL011_FR_RXFE if offset == 0x18 else PL011_ID_REGS[offset]
            uc.mem_write(address, struct.pack("<I", read_value))

    cpu.hook_add(UC_HOOK_CODE, code)
    cpu.hook_add(UC_HOOK_MEM_UNMAPPED, unmapped)
    if uart_base is not None:
        cpu.mem_map(uart_base, 4096)
        cpu.hook_add(UC_HOOK_MEM_READ | UC_HOOK_MEM_WRITE, uart,
                     begin=uart_base, end=uart_base + 4095)
    try:
        cpu.emu_start(contract.load_addresses["kernel_load"], 0xFFFFFFFF,
                      count=limit, timeout=report["timeout_us"])
    except UcError as error:
        report["unicorn_error"] = str(error)
        if report["stop"] is None:
            report["stop"] = {"reason": "unicorn_error"}
    if report["stop"] is None:
        reason = ("timeout" if cpu.query(UC_QUERY_TIMEOUT) else
                  "instruction_limit" if report["instructions"] >= limit else "unexpected_return")
        report["stop"] = {"reason": reason}
    report.update(stop_pc=cpu.reg_read(UC_ARM_REG_PC),
                  stop_cpsr=cpu.reg_read(UC_ARM_REG_CPSR), serial_hex=serial.hex())
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--kernel-sha256", required=True)
    parser.add_argument("--reference-root", type=Path)
    parser.add_argument("--reference-kernel-sha256")
    parser.add_argument("--updater-sha256")
    parser.add_argument("--replay-prefix", action="store_true")
    parser.add_argument("--pl011-base", type=lambda value: int(value, 0))
    parser.add_argument("--limit", type=int, default=500_000)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    if bool(args.reference_root) != bool(args.reference_kernel_sha256):
        parser.error("Reference root and expected kernel hash must be supplied together")
    if (args.replay_prefix or args.pl011_base is not None) and not args.updater_sha256:
        parser.error("Prefix replay needs an explicitly identified updater partition")
    if args.pl011_base is not None and not args.replay_prefix:
        parser.error("The PL011 fixture is only used with --replay-prefix")
    out = args.output_dir.resolve()
    if not out.is_relative_to(ROOT / "artifacts"):
        parser.error("Output must remain under artifacts")
    out.mkdir(parents=True, exist_ok=False)
    report = {"scope": "offline package map; never a live /proc inventory"}
    candidate = package_report(args.package_root, args.kernel_sha256)
    report["candidate"] = candidate
    if args.reference_root:
        reference = package_report(args.reference_root, args.reference_kernel_sha256)
        report["reference"] = reference
        report["comparison"] = {
            "partition_rows_equal": candidate["partition_configuration"]["rows"] == reference["partition_configuration"]["rows"],
            "mount_rows_equal": candidate["mount_configuration"]["rows"] == reference["mount_configuration"]["rows"],
            "mmio_rows_equal": candidate["kernel"]["mmio"]["mappings"] == reference["kernel"]["mmio"]["mappings"],
            "gic_arguments_equal": candidate["kernel"]["mmio"]["gic_setup"]["registers"] == reference["kernel"]["mmio"]["gic_setup"]["registers"],
            "timer_base_equal": candidate["kernel"]["timer_context"]["base"] == reference["kernel"]["timer_context"]["base"],
            "main_memory_parameters_equal": candidate["main_boot_parameters"]["memory_parameters"] == reference["main_boot_parameters"]["memory_parameters"],
            "ret_to_user_words_equal": candidate["kernel"]["ret_to_user_words"] == reference["kernel"]["ret_to_user_words"],
        }
    if args.updater_sha256:
        raw = checked_bytes(checked_path(args.package_root, UPDATER), args.updater_sha256)
        boot = NflashaBootSet("nflasha1", raw, {
            "declared_size": len(raw), "sha256": args.updater_sha256,
            "role": "packaged updater, not a physical camera dump"})
        contract = UpdaterBootContract(boot)
        if not all(contract.verify()["checks"].values()):
            raise ValueError("Updater boot contract validation failed")
        report["updater"] = {"boot_contract": contract.verify(),
                             "initrd_format": detect_image_format(contract.initrd),
                             "kernel": kernel_report(contract.raw_kernel)}
        if args.replay_prefix:
            report["prefix"] = prefix_replay(contract, limit=args.limit,
                                               uart_base=args.pl011_base)
    for label in ("candidate", "reference", "updater"):
        if label in report:
            symbols = report[label]["kernel"].pop("symbols")
            (out / f"{label}-symbols.json").write_text(json.dumps(symbols, indent=2), encoding="utf-8")
    (out / "machine-map.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(out / "machine-map.json")
    print(json.dumps({"comparison": report.get("comparison"), "prefix": report.get("prefix")}, indent=2))
    return 2 if args.replay_prefix else 0


if __name__ == "__main__":
    raise SystemExit(main())
