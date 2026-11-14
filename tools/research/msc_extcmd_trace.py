"""Original a6400A external-command readiness controls, offline and fixture-only.

Runs a closed ARM decision window, not a loaded kernel or live camera. The list
lookup is an explicit callee fixture; unsupported execution stops the control.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import struct

from elftools.elf.elffile import ELFFile
from unicorn import (UC_ARCH_ARM, UC_HOOK_CODE, UC_HOOK_MEM_WRITE, UC_MODE_ARM,
                     UC_MODE_THUMB, Uc, UcError)
from unicorn.arm_const import (UC_ARM_REG_CPSR, UC_ARM_REG_LR, UC_ARM_REG_PC,
                               UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
                               UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6,
                               UC_ARM_REG_R10, UC_ARM_REG_SP, UC_CPU_ARM_CORTEX_A9)

from tools.research.a6400a_native_readonly import MODEL_CDB, MODEL_REQUEST
from tools.research.storage_trace import module_relocations

ROOT = Path(__file__).resolve().parents[2]
KMOD = (ROOT / "firmware" / "extracted_a6400a_v101" / "firmware.tar_unpacked"
        / "0700_part_image" / "dev" / "nflasha15_unpacked" / "kmod")
DRIVER_SHA = "d47d05ec891d18c8582baf19e413967c5d3fd5c36438d76f6d2e8a7f112428e3"
STORAGE_SHA = "3c79156a3f3e9fc1a1bff733d33647a1121a5688aed87271647a14d8b9c346b2"
USBCMD_SHA = "23b94deb094d31f160cfe1d46330f2425e94d4801dfccb66720c4cf4b81cfb7e"
DEVINFO_SHA = "db4a0c97ccbd5fad6acec2354dbfeea12c50b2e93e7d346d02e280d7f70d896e"
CODE, STORAGE, LOOKUP, RETURN = 0x01000000, 0x01100000, 0x01800000, 0x01801000
DATA, STACK = 0x03000000, 0x03200000
ARG, CDB, SENSE, NODE = DATA, DATA + 0x1000, DATA + 0x2000, DATA + 0x3000
DEVICE, COMMAND = DATA + 0x4000, DATA + 0x5000


def original_text(raw: bytes, expected_sha: str) -> dict:
    if hashlib.sha256(raw).hexdigest() != expected_sha:
        raise ValueError("Original module identity mismatch")
    elf = ELFFile(io.BytesIO(raw))
    if (elf.elfclass, elf.little_endian, elf["e_machine"], elf["e_type"]) != (
            32, True, "EM_ARM", "ET_REL"):
        raise ValueError("Expected ELF32 little-endian ARM relocatable module")
    table, text = elf.get_section_by_name(".symtab"), elf.get_section_by_name(".text")
    if table is None or text is None:
        raise ValueError("Original module has no text/symbol table")
    symbols = {symbol.name: (symbol["st_value"], symbol["st_size"])
               for symbol in table.iter_symbols()
               if symbol["st_info"]["type"] == "STT_FUNC"
               and isinstance(symbol["st_shndx"], int)
               and elf.get_section(symbol["st_shndx"]).name == ".text"}
    index = next(i for i, section in enumerate(elf.iter_sections()) if section.name == ".text")
    return {"text": text.data(), "symbols": symbols,
            "relocations": {offset: item for (section, offset), item in
                            module_relocations(elf).items() if section == index},
            "sha256": expected_sha}


def link_arm_call(word: int, place: int, target: int) -> int:
    if word & 0x0F000000 != 0x0B000000 or word >> 28 == 15:
        raise ValueError("Expected an ARM BL relocation")
    displacement = target - place - 8
    if displacement % 4 or not -(1 << 25) <= displacement < 1 << 25:
        raise ValueError("ARM BL target is unaligned or outside its signed range")
    return (word & 0xFF000000) | ((displacement >> 2) & 0xFFFFFF)


def linked_window(image: dict, base: int, calls: dict[int, tuple[str, int]]) -> bytes:
    text = bytearray(image["text"])
    for offset, (name, target) in calls.items():
        relocation = image["relocations"].get(offset)
        if not relocation or relocation["type"] != 28 or relocation["symbol"] != name:
            raise ValueError(f"Original call-site identity changed at {offset:#x}")
        word = struct.unpack_from("<I", text, offset)[0]
        struct.pack_into("<I", text, offset, link_arm_call(word, base + offset, target))
    return bytes(text)


class ReadinessControl:
    def __init__(self, driver: dict, *, present=True, mask=0, feature=1, opcode=0x7A):
        if not 0 <= mask <= 3 or not 0 <= feature <= 65535 or not 0 <= opcode <= 255:
            raise ValueError("Invalid declared lookup/readiness fixture")
        if driver["symbols"].get("get_inquiry_state") != (0x50C, 48):
            raise ValueError("Unsupported original readiness-function layout")
        self.driver = driver
        self.present = present
        self.uc = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        self.uc.ctl_set_cpu_model(UC_CPU_ARM_CORTEX_A9)
        code = linked_window(driver, CODE, {
            0x51C: ("list_get_node", LOOKUP),
            0x163C: ("get_inquiry_state", CODE + 0x50C),
        })
        self.uc.mem_map(CODE, (len(code) + 4095) & ~4095, 5)
        self.uc.mem_write(CODE, code)
        self.uc.mem_map(LOOKUP, 8192, 5)
        self.uc.mem_map(DATA, 0x10000, 3)
        self.uc.mem_map(STACK, 0x10000, 3)
        self.uc.mem_write(CDB, MODEL_CDB)
        self.uc.mem_write(NODE + 8, bytes([opcode, 0]) + struct.pack("<H", feature))
        self.write32(NODE + 0x14, mask)
        self.allowed = []
        self.lookups = []
        self.writes = []
        self.instructions = 0
        self.stop = None
        self.state = None
        self.ready_stop = False
        self.arithmetic = {}
        self.arithmetic_calls = []
        self.uc.hook_add(UC_HOOK_CODE, self._code)
        self.uc.hook_add(UC_HOOK_MEM_WRITE, self._write,
                         begin=NODE + 0x14, end=NODE + 0x17)

    def write32(self, address: int, value: int):
        self.uc.mem_write(address, struct.pack("<I", value))

    def read32(self, address: int) -> int:
        return struct.unpack("<I", bytes(self.uc.mem_read(address, 4)))[0]

    def _write(self, uc, access, address, size, value, user):
        self.writes.append({"address": address, "size": size, "value": value})

    def _code(self, uc, address, size, user):
        self.instructions += 1
        if address in self.arithmetic:
            name = self.arithmetic[address]
            numerator, divisor = uc.reg_read(UC_ARM_REG_R0), uc.reg_read(UC_ARM_REG_R1)
            if not divisor:
                self.stop = "unsupported_divide_by_zero"
                uc.emu_stop()
                return
            quotient, remainder = divmod(numerator, divisor)
            self.arithmetic_calls.append({"helper_fixture": name, "numerator": numerator,
                                          "divisor": divisor, "quotient": quotient,
                                          "remainder": remainder})
            uc.reg_write(UC_ARM_REG_R0, quotient)
            if name == "__aeabi_uidivmod":
                uc.reg_write(UC_ARM_REG_R1, remainder)
            uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR))
            return
        if address == LOOKUP:
            opcode, feature = uc.reg_read(UC_ARM_REG_R0), uc.reg_read(UC_ARM_REG_R1)
            node_opcode, _, node_feature = struct.unpack(
                "<BBH", bytes(uc.mem_read(NODE + 8, 4)))
            matched = self.present and (opcode, feature) == (node_opcode, node_feature)
            self.lookups.append({"opcode": opcode, "feature": feature,
                                 "callee_fixture_match": matched})
            uc.reg_write(UC_ARM_REG_R0, NODE if matched else 0)
            uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR))
            return
        if address == CODE + 0x1640:
            self.state = uc.reg_read(UC_ARM_REG_R0)
        if self.ready_stop and address == CODE + 0x1660:
            self.stop = "ready_branch_before_cancel_or_transfer"
            uc.emu_stop()
            return
        if not any(start <= address < end for start, end in self.allowed):
            self.stop = f"unsupported_pc_{address:#x}"
            uc.emu_stop()

    def run(self, start: int, end: int, registers: dict[int, int], allowed: list) -> dict:
        self.allowed = allowed
        self.stop = None
        self.instructions = 0
        for register, value in {
            UC_ARM_REG_CPSR: 0xD3, UC_ARM_REG_SP: STACK + 0xFF00,
            UC_ARM_REG_LR: end, **registers,
        }.items():
            self.uc.reg_write(register, value)
        self.uc.emu_start(start, end, timeout=1_000_000, count=2000)
        pc = self.uc.reg_read(UC_ARM_REG_PC)
        if self.stop is None:
            self.stop = "bounded_return" if pc == end else "instruction_or_time_limit"
        if self.stop not in ("bounded_return", "ready_branch_before_cancel_or_transfer"):
            raise RuntimeError(f"Original decision control stopped: {self.stop}")
        return {"stop": self.stop, "pc": pc, "instructions": self.instructions,
                "return_register": self.uc.reg_read(UC_ARM_REG_R0)}

    def status(self, direction: int) -> dict:
        if direction not in (1, 2):
            raise ValueError("Only declared IN/OUT direction fixtures are supported")
        before = self.read32(NODE + 0x14)
        self.uc.mem_write(ARG, struct.pack("<IIHHIII", 16, CDB, direction, 0, SENSE, 0, 0))
        self.uc.mem_write(SENSE, b"\xA5" * 4)
        self.ready_stop = True
        result = self.run(CODE + 0x1624, CODE + 0x1BF0,
                          {UC_ARM_REG_R0: 0, UC_ARM_REG_R1: 0,
                           UC_ARM_REG_R2: ARG, UC_ARM_REG_R4: ARG},
                          [(CODE + 0x50C, CODE + 0x53C), (CODE + 0x1624, CODE + 0x16DC),
                           (CODE + 0x1978, CODE + 0x1984), (CODE + 0x19C4, CODE + 0x19D0)])
        raw = bytes(self.uc.mem_read(SENSE, 4))
        result.update(
            direction=direction, readiness_mask_before=before,
            readiness_mask_after=self.read32(NODE + 0x14),
            original_state_result=self.state,
            sense=None if self.state == 2 else [raw[0], raw[3], raw[2]],
            readiness_writes=list(self.writes), lookup_fixtures=list(self.lookups),
            scope="original status decision window; not a whole ioctl, SCSI transfer or live kernel")
        return result

    def arm_sequence(self) -> dict:
        self.ready_stop = False
        transitions = []
        for name, argument in (("enable_inquiry_state", 2), ("enable_inquiry_state", 1),
                               ("disable_inquiry_state", 0), ("disable_inquiry_state", 1)):
            start, size = self.driver["symbols"][name]
            before = self.read32(NODE + 0x14)
            run = self.run(CODE + start, RETURN,
                           {UC_ARM_REG_R0: NODE, UC_ARM_REG_R1: argument},
                           [(CODE + start, CODE + start + size)])
            transitions.append({"function": name, "argument": argument, "before": before,
                                "after": self.read32(NODE + 0x14), **run})
        return {"transitions": transitions, "scope": "original bit-arming helpers on one constructed node"}

    def normal_ready_tur(self, storage: dict) -> dict:
        code = linked_window(storage, STORAGE, {0x72C0: ("setSense", STORAGE + 0x5EA8)})
        self.uc.mem_map(STORAGE, (len(code) + 4095) & ~4095, 5)
        self.uc.mem_write(STORAGE, code)
        self.write32(COMMAND, DEVICE)
        self.write32(COMMAND + 8, CDB)
        self.uc.mem_write(CDB, bytes(16))
        self.write32(DEVICE + 0x30, 1)
        self.uc.mem_write(DEVICE + 0x48, b"\xA5" * 3)
        before = self.read32(NODE + 0x14)
        run = self.run(STORAGE + 0x720C, RETURN, {UC_ARM_REG_R0: COMMAND},
                       [(STORAGE + 0x720C, STORAGE + 0x72E0),
                        (STORAGE + 0x5EA8, STORAGE + 0x5ECC)])
        run.update(readiness_mask_before=before, readiness_mask_after=self.read32(NODE + 0x14),
                   readiness_writes=list(self.writes),
                   sense=list(self.uc.mem_read(DEVICE + 0x48, 3)),
                   scope="original TEST UNIT READY normal-ready media fixture only")
        return run

    def timeout_conversion(self, milliseconds: int) -> dict:
        if not 0 < milliseconds <= 0xFFFFFFFF:
            raise ValueError("The finite-wait window needs a positive timeout fixture")
        self.arithmetic = {LOOKUP + 0x100: "__aeabi_uidivmod",
                           LOOKUP + 0x110: "__aeabi_uidiv"}
        code = linked_window(self.driver, CODE, {
            0x51C: ("list_get_node", LOOKUP),
            0x163C: ("get_inquiry_state", CODE + 0x50C),
            0x950: ("__aeabi_uidivmod", LOOKUP + 0x100),
            0x960: ("__aeabi_uidiv", LOOKUP + 0x110),
        })
        self.uc.mem_write(CODE, code)
        run = self.run(CODE + 0x948, CODE + 0x984, {UC_ARM_REG_R10: milliseconds},
                       [(CODE + 0x948, CODE + 0x984)])
        run.update(input_timeout_ms=milliseconds, schedule_timeout_ticks=self.uc.reg_read(UC_ARM_REG_R6),
                   arithmetic_fixtures=self.arithmetic_calls,
                   scope="original finite-wait conversion; integer ABI helper fixtures; no scheduler run")
        return run


def original_thumb(raw: bytes, expected_sha: str, fragment: str) -> tuple[int, bytes]:
    if hashlib.sha256(raw).hexdigest() != expected_sha:
        raise ValueError("Original library identity mismatch")
    elf = ELFFile(io.BytesIO(raw))
    if (elf.elfclass, elf.little_endian, elf["e_machine"], elf["e_type"]) != (
            32, True, "EM_ARM", "ET_DYN"):
        raise ValueError("Expected an ARM shared-library input")
    table = elf.get_section_by_name(".dynsym")
    symbols = [symbol for symbol in table.iter_symbols()
               if fragment in symbol.name and isinstance(symbol["st_shndx"], int)]
    if len(symbols) != 1 or not symbols[0]["st_value"] & 1:
        raise ValueError("Absent/ambiguous original Thumb function")
    symbol = symbols[0]
    section = elf.get_section(symbol["st_shndx"])
    address = symbol["st_value"] & ~1
    offset = address - section["sh_addr"]
    code = section.data()[offset:offset + symbol["st_size"]]
    if offset < 0 or not 0 < len(code) == symbol["st_size"] <= 1024:
        raise ValueError("Original Thumb function is outside the bounded section")
    return address, code


def thumb_fixture(functions: list[tuple[int, bytes]]):
    uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
    uc.ctl_set_cpu_model(UC_CPU_ARM_CORTEX_A9)
    uc.mem_map(0x2000, 0x2000, 5)
    for address, code in functions:
        if not 0x2000 <= address < address + len(code) <= 0x4000:
            raise ValueError("Thumb fixture code window is not declared")
        uc.mem_write(address, code)
    uc.mem_map(0x10000, 0x10000, 3)
    uc.mem_map(0x20000, 8192, 3)
    uc.mem_map(0x30000, 4096, 5)
    return uc


def run_thumb(uc, start: int, end: int, registers: dict, ranges: list) -> int:
    stopped = []
    count = [0]

    def guard(cpu, address, size, user):
        count[0] += 1
        if not any(lo <= address < hi for lo, hi in ranges):
            stopped.append(address)
            cpu.emu_stop()

    hook = uc.hook_add(UC_HOOK_CODE, guard)
    try:
        for register, value in {
            UC_ARM_REG_CPSR: 0x30, UC_ARM_REG_SP: 0x1FFF0,
            UC_ARM_REG_LR: 0x30001, **registers,
        }.items():
            uc.reg_write(register, value)
        uc.emu_start(start | 1, end, timeout=100_000, count=200)
    finally:
        uc.hook_del(hook)
    if stopped or uc.reg_read(UC_ARM_REG_PC) != end:
        raise RuntimeError("Original Thumb control left its declared window")
    return count[0]


def reply_timeout_controls(devinfo: bytes, usbcmd: bytes) -> dict:
    callback = original_thumb(devinfo, DEVINFO_SHA, "13ReqTranserCmp")
    callback_rows = []
    for status, direction in ((0, 0), (0, 0x80), (62, 0x80)):
        uc = thumb_fixture([callback])
        uc.mem_write(0x20000, MODEL_REQUEST)
        uc.mem_write(0x12000 + 0x10, struct.pack("<II", direction, 0x20000))
        uc.mem_write(0x12000 + 0x24, struct.pack("<I", status))
        count = run_thumb(uc, 0x2646, 0x2670,
                          {UC_ARM_REG_R0: 0x11000, UC_ARM_REG_R1: 0x12000,
                           UC_ARM_REG_R4: 0x11000}, [(0x2646, 0x2670)])
        callback_rows.append({"completion_status_fixture": status, "previous_direction": direction,
                              "next_direction": uc.reg_read(UC_ARM_REG_R6),
                              "next_timeout": uc.reg_read(UC_ARM_REG_R5), "instructions": count})
    if [(row["next_direction"], row["next_timeout"]) for row in callback_rows] != [
            (0x80, 10000), (0, 0), (0, 0)]:
        raise AssertionError("Original receive/reply/rearm preparation differs")
    init = original_thumb(usbcmd, USBCMD_SHA, "9transInit")
    pack = original_thumb(usbcmd, USBCMD_SHA, "15PackParamDriver")
    uc = thumb_fixture([init, pack])
    uc.mem_write(0x14000, struct.pack("<II", 0x15000, 0x16000))
    uc.mem_write(0x12000 + 0x10, struct.pack("<I", 0x80))
    uc.mem_write(0x12000 + 0x14, struct.pack("<I", 0x20000))
    uc.mem_write(0x12000 + 0x1C, struct.pack("<II", 8192, 10000))
    init_count = run_thumb(uc, init[0], 0x30000,
                           {UC_ARM_REG_R0: 0x11000, UC_ARM_REG_R1: 0x14000,
                            UC_ARM_REG_R2: 0x12000}, [(init[0], init[0] + len(init[1]))])
    pack_count = run_thumb(uc, pack[0], 0x30000,
                           {UC_ARM_REG_R0: 0x15000, UC_ARM_REG_R1: 0x17000,
                            UC_ARM_REG_R2: 0x16000}, [(pack[0], pack[0] + len(pack[1]))])
    public_timeout = struct.unpack("<I", bytes(uc.mem_read(0x16010, 4)))[0]
    driver_timeout = struct.unpack("<I", bytes(uc.mem_read(0x1700C, 4)))[0]
    if public_timeout != 10000 or driver_timeout != 10000:
        raise AssertionError("Original service-to-driver timeout packing differs")
    return {"callback_preparation_windows": callback_rows,
            "public_timeout_ms": public_timeout, "driver_timeout_ms": driver_timeout,
            "init_instructions": init_count, "pack_instructions": pack_count,
            "scope": "original callback windows and pure packing functions; no model-info build, backup read, IPC or driver call"}


def controls(driver: dict, storage: dict) -> dict:
    rows = []
    for present, mask in [(False, 0)] + [(True, mask) for mask in range(4)]:
        for direction in (1, 2):
            result = ReadinessControl(driver, present=present, mask=mask).status(direction)
            expected = 0 if not present else 2 if mask & direction else 1
            sense = [5, 0x20, 0] if not present else None if expected == 2 else [9, 0x81, 0x81]
            if (result["original_state_result"] != expected or result["sense"] != sense
                    or result["readiness_writes"] or result["readiness_mask_after"] != mask):
                raise AssertionError("Original status decision differs from the decoded contract")
            rows.append({"present_fixture": present, **result})
    for key in ({"feature": 2}, {"opcode": 0x7B}):
        result = ReadinessControl(driver, mask=3, **key).status(1)
        if result["original_state_result"] != 0 or result["sense"] != [5, 0x20, 0]:
            raise AssertionError("A different command key was treated as the registered fixture")
        rows.append({"different_key_fixture": key, **result})
    sequence = ReadinessControl(driver).arm_sequence()
    if [row["after"] for row in sequence["transitions"]] != [2, 3, 1, 0]:
        raise AssertionError("Original ready-bit arming/clearing sequence differs")
    tur = ReadinessControl(driver, mask=2).normal_ready_tur(storage)
    if tur["readiness_writes"] or tur["readiness_mask_after"] != 2 or tur["sense"] != [0, 0, 0]:
        raise AssertionError("The normal-ready TUR fixture changed external-command readiness")
    timeout = ReadinessControl(driver).timeout_conversion(10000)
    if timeout["schedule_timeout_ticks"] != 1000:
        raise AssertionError("The original finite reply timeout did not convert to 1000 ticks")
    return {"status_cases": rows, "arm_sequence": sequence, "normal_ready_tur": tur,
            "reply_wait_conversion": timeout}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--driver", type=Path, default=KMOD / "usb_extcmd.ko")
    parser.add_argument("--storage", type=Path, default=KMOD / "usbg_storage.ko")
    parser.add_argument("--usbcmd", type=Path, default=KMOD.parent / "lib" / "libusbcmd.so")
    parser.add_argument("--devinfo", type=Path, default=KMOD.parent / "lib" / "libInfraDevInfoSender.so")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    out = args.output_dir.resolve()
    if not out.is_relative_to(ROOT / "artifacts"):
        parser.error("Reports must remain under artifacts")
    out.mkdir(parents=True, exist_ok=False)
    report = {"scope": "Original a6400A ARM decision controls with declared fixtures; no camera access",
              "status": "in_progress", "lookup": "explicit callee fixture, not original list traversal",
              "relocation_scope": "only the closed executed call graph; no full-module linkage claimed",
              "driver_sha256": DRIVER_SHA, "storage_sha256": STORAGE_SHA}
    try:
        driver = original_text(args.driver.read_bytes(), DRIVER_SHA)
        storage = original_text(args.storage.read_bytes(), STORAGE_SHA)
        report["controls"] = controls(driver, storage)
        report["reply_lifetime"] = reply_timeout_controls(args.devinfo.read_bytes(),
                                                         args.usbcmd.read_bytes())
        report.update(usbcmd_sha256=USBCMD_SHA, devinfo_sha256=DEVINFO_SHA)
        report["status"] = "passed_fixture_controls"
    except (OSError, ValueError, RuntimeError, AssertionError, UcError) as error:
        report.update(status="failed", error_type=type(error).__name__, error=str(error))
    (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "controls"}, indent=2))
    return 0 if report["status"] == "passed_fixture_controls" else 2


if __name__ == "__main__":
    raise SystemExit(main())
