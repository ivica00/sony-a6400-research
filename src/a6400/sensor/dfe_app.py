"""Parser and bounded state-machine emulator for ``dfe_app.bin`` (Data Front-End).

``dfe_app.bin`` (1,956 B on ILCE-6400) is a self-contained ARM/Thumb-2 helper
linked at ``0xFE1ED000`` (``0x7A4`` bytes) that initializes its SRAM workspace at
``0xFE1F0000..0xFE1F1000`` and manages DFE XDMAC descriptor lists and padding.
"""
from __future__ import annotations

import hashlib
import re
import struct
from dataclasses import dataclass

DFE_LINK_BASE = 0xFE1ED000
DFE_SRAM_BASE = 0xFE1F0000
DFE_SRAM_SIZE = 0x1000  # 0xFE1F0000..0xFE1F1000
DFE_SCRATCH_BASE = 0xFE1E9000

PROLOGUE_WORDS = (0xEA000000, 0xE12FFF1E, 0xE28FC03B, 0xE12FFF1C)


class DfeError(RuntimeError):
    """Explicit DFE hardware/contract error matching firmware error strings."""


@dataclass(frozen=True)
class DfeAppInfo:
    """Parsed metadata and memory-map contract of ``dfe_app.bin``."""

    size: int
    sha256: str
    link_base: int
    link_end: int
    sram_regions: tuple[int, ...]
    entrypoints: tuple[int, ...]
    error_strings: tuple[str, ...]


@dataclass(frozen=True)
class DfeXdmacDescriptor:
    """Bounded XDMAC transfer descriptor for DFE list creation."""

    src_addr: int
    dst_addr: int
    byte_count: int
    padding_mode: str = "none"  # "none", "cpu", "mpr"


def parse_dfe_app(data: bytes) -> DfeAppInfo:
    """Parse ``dfe_app.bin`` and verify its ARM/Thumb-2 prologue and literal map."""
    if len(data) < 0x80:
        raise DfeError(f"dfe_app.bin truncated ({len(data)} B)")
    words = struct.unpack_from("<4I", data, 0)
    if words != PROLOGUE_WORDS:
        raise DfeError(
            f"unexpected dfe_app.bin prologue: {[hex(w) for w in words]} != {[hex(w) for w in PROLOGUE_WORDS]}"
        )

    sram_regions: list[int] = []
    entrypoints: list[int] = []
    link_end = DFE_LINK_BASE + len(data)

    for off in range(0, len(data) - 3, 4):
        w = struct.unpack_from("<I", data, off)[0]
        if DFE_LINK_BASE <= w <= link_end and (w & 1):
            entrypoints.append(w)
        elif 0xFE1E0000 <= w <= 0xFE1FFFFF and (w & 0xFF) == 0:
            if w not in sram_regions:
                sram_regions.append(w)

    errs = tuple(
        m.group(0).decode("ascii")
        for m in re.finditer(rb"DFE:[A-Z0-9_ :]+", data)
    )

    return DfeAppInfo(
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        link_base=DFE_LINK_BASE,
        link_end=link_end,
        sram_regions=tuple(sorted(sram_regions)),
        entrypoints=tuple(sorted(set(entrypoints))),
        error_strings=errs,
    )


class DfeAppModel:
    """Bounded emulator for ``dfe_app.bin`` SRAM and XDMAC descriptor-list contracts."""

    MAX_LIST_ENTRIES = 64

    def __init__(self, info: DfeAppInfo, binary: bytes) -> None:
        self.info = info
        self.code_image = bytearray(binary)
        self.sram = bytearray(DFE_SRAM_SIZE)
        self.xdmac_list: list[DfeXdmacDescriptor] = []
        self.xdmac_status: int = 0
        self.xddcc_status: int = 0
        self.transfer_count: int = 0

    @classmethod
    def from_bytes(cls, data: bytes) -> "DfeAppModel":
        return cls(parse_dfe_app(data), data)

    def reset(self) -> None:
        """Reset DFE SRAM and XDMAC descriptor list."""
        self.sram[:] = b"\x00" * DFE_SRAM_SIZE
        self.xdmac_list.clear()
        self.xdmac_status = 0
        self.xddcc_status = 0

    def read_sram(self, addr: int, size: int) -> bytes:
        if addr < DFE_SRAM_BASE or addr + size > DFE_SRAM_BASE + DFE_SRAM_SIZE:
            raise DfeError(f"DFE SRAM read out of bounds: {addr:#x}+{size:#x}")
        off = addr - DFE_SRAM_BASE
        return bytes(self.sram[off : off + size])

    def write_sram(self, addr: int, payload: bytes) -> None:
        if addr < DFE_SRAM_BASE or addr + len(payload) > DFE_SRAM_BASE + DFE_SRAM_SIZE:
            raise DfeError(f"DFE SRAM write out of bounds: {addr:#x}+{len(payload):#x}")
        off = addr - DFE_SRAM_BASE
        self.sram[off : off + len(payload)] = payload

    def create_list(self, descriptors: list[DfeXdmacDescriptor]) -> int:
        """Validate and stage an XDMAC descriptor list (enforces DFE error contracts)."""
        if not descriptors or len(descriptors) > self.MAX_LIST_ENTRIES:
            raise DfeError(f"DFE:LIST CREATE ERR  : invalid count {len(descriptors)}")

        for idx, desc in enumerate(descriptors):
            if desc.byte_count <= 0 or (desc.byte_count & 0x7) != 0:
                if desc.padding_mode == "cpu":
                    raise DfeError(f"DFE:CPU PADDING ERR  : entry {idx} unaligned size {desc.byte_count}")
                if desc.padding_mode == "mpr":
                    raise DfeError(f"DFE:MPR PADDING ERR  : entry {idx} unaligned size {desc.byte_count}")
                raise DfeError(f"DFE:LIST CREATE ERR  : entry {idx} invalid byte_count {desc.byte_count}")
            if (desc.src_addr & 0x3) != 0 or (desc.dst_addr & 0x3) != 0:
                raise DfeError(
                    f"DFE:LIST CREATE ERR  : entry {idx} unaligned addr src={desc.src_addr:#x} dst={desc.dst_addr:#x}"
                )

        self.xdmac_list = list(descriptors)
        # Write compact descriptor count + status into SRAM header (0xFE1F0000)
        struct.pack_into("<II", self.sram, 0, len(self.xdmac_list), 0x1)
        return len(self.xdmac_list)

    def run_xdmac(self) -> int:
        """Execute staged XDMAC descriptor list; returns total bytes transferred."""
        if not self.xdmac_list:
            self.xdmac_status = 1
            raise DfeError("DFE:XDMAC STATUS ERR : empty descriptor list")
        if self.xddcc_status != 0:
            raise DfeError(f"DFE:XDMAC XDDCC ERR  : xddcc={self.xddcc_status:#x}")

        total = sum(d.byte_count for d in self.xdmac_list)
        self.transfer_count += 1
        self.xdmac_status = 0
        struct.pack_into("<III", self.sram, 8, total, self.transfer_count, 0)
        return total
