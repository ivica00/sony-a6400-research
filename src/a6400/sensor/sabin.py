"""Parsers and inventory for Sony BIONZ X ``sabin/`` sensor & DSP payload tables.

Observed binary families in ``nflasha3/sabin/`` and ``nflasha15/sabin/``:
* ``sa_*.bin``: Signal Accelerator microcode/firmware (magic ``0x91130AAA`` LE, ASCII tag at ``+0x14``)
* ``dcv_psf_table_*.bin``: Deconvolution PSF tables (magic ``IMX2``, 0x40-byte header + payload)
* ``idt_cam.bin``, ``ssboot.bin``, ``ssboot_any.bin``: Sub-processor boot/IDT images (word0 low16 ``0x003D``, declared size at ``+0x18``)
* ``spica_musashi_*.bin``: Chroma (40,000 B) and luma (48,000 B) multi-tap scaler/filter coefficient tables
"""
from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass
from pathlib import Path

SA_MAGIC = 0x91130AAA
DCV_MAGIC = b"IMX2"
IDT_SSBOOT_MAGIC_LOW16 = 0x003D


class SabinParseError(ValueError):
    """Raised when a ``sabin/`` binary does not match its declared header contract."""


@dataclass(frozen=True)
class SaModuleHeader:
    """Header of a ``sa_*.bin`` Signal Accelerator module."""

    filename: str
    size: int
    sha256: str
    magic: int
    version: int
    w2: int
    w3: int
    w4: int
    name_tag: str


@dataclass(frozen=True)
class DcvPsfHeader:
    """Header of a ``dcv_psf_table_*.bin`` deconvolution PSF table."""

    filename: str
    size: int
    sha256: str
    magic: str
    format_tag: str
    generator_tag: str
    timestamp: str
    payload_size: int
    header_words: tuple[int, int, int]


@dataclass(frozen=True)
class IdtSsbootHeader:
    """Header of ``idt_cam.bin``, ``ssboot.bin``, or ``ssboot_any.bin``."""

    filename: str
    size: int
    sha256: str
    word0: int
    word1: int
    flags: int
    code_offset: int
    word4: int
    word5: int
    declared_size: int
    payload_end: int


@dataclass(frozen=True)
class SpicaMusashiEntry:
    """Classified ``spica_musashi_*.bin`` tap-filter table."""

    filename: str
    size: int
    sha256: str
    mode: str
    channel: str
    step: str


@dataclass(frozen=True)
class SabinInventory:
    """Complete parsed inventory of one or more ``sabin/`` directories."""

    sa_modules: tuple[SaModuleHeader, ...]
    dcv_tables: tuple[DcvPsfHeader, ...]
    idt_ssboot: tuple[IdtSsbootHeader, ...]
    spica_tables: tuple[SpicaMusashiEntry, ...]
    other_files: tuple[tuple[str, int, str], ...]

    @property
    def total_files(self) -> int:
        return (
            len(self.sa_modules)
            + len(self.dcv_tables)
            + len(self.idt_ssboot)
            + len(self.spica_tables)
            + len(self.other_files)
        )


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_sa_module(data: bytes, filename: str = "<memory>") -> SaModuleHeader:
    """Parse and validate a ``sa_*.bin`` Signal Accelerator module header."""
    if len(data) < 0x28:
        raise SabinParseError(f"{filename}: truncated SA module ({len(data)} B)")
    magic, version, w2, w3, w4 = struct.unpack_from("<5I", data, 0)
    if magic != SA_MAGIC:
        raise SabinParseError(f"{filename}: expected SA magic {SA_MAGIC:#010x}, got {magic:#010x}")
    raw_tag = data[0x14:0x20].split(b"\x00", 1)[0]
    name_tag = raw_tag.decode("ascii", errors="replace")
    return SaModuleHeader(
        filename=filename,
        size=len(data),
        sha256=_sha256(data),
        magic=magic,
        version=version,
        w2=w2,
        w3=w3,
        w4=w4,
        name_tag=name_tag,
    )


def parse_dcv_psf(data: bytes, filename: str = "<memory>") -> DcvPsfHeader:
    """Parse and validate a ``dcv_psf_table_*.bin`` header (0x40 bytes)."""
    if len(data) < 0x40:
        raise SabinParseError(f"{filename}: truncated DCV PSF table ({len(data)} B)")
    if data[0:4] != DCV_MAGIC:
        raise SabinParseError(f"{filename}: expected DCV magic {DCV_MAGIC!r}, got {data[0:4]!r}")
    format_tag = data[4:16].split(b"\x00", 1)[0].decode("ascii", errors="replace")
    generator_tag = data[16:32].split(b"\x00", 1)[0].decode("ascii", errors="replace")
    timestamp = data[32:48].split(b"\x00", 1)[0].decode("ascii", errors="replace")
    declared_size, h1, h2, h3 = struct.unpack_from("<4I", data, 0x30)
    if declared_size != len(data):
        raise SabinParseError(
            f"{filename}: DCV declared_size {declared_size} != file size {len(data)}"
        )
    return DcvPsfHeader(
        filename=filename,
        size=len(data),
        sha256=_sha256(data),
        magic=DCV_MAGIC.decode("ascii"),
        format_tag=format_tag,
        generator_tag=generator_tag,
        timestamp=timestamp,
        payload_size=declared_size - 0x40,
        header_words=(h1, h2, h3),
    )


def parse_idt_ssboot(data: bytes, filename: str = "<memory>") -> IdtSsbootHeader:
    """Parse and validate ``idt_cam.bin``, ``ssboot.bin``, or ``ssboot_any.bin``."""
    if len(data) < 0x20:
        raise SabinParseError(f"{filename}: truncated IDT/SSBOOT image ({len(data)} B)")
    w0, w1, flags, code_offset, w4, w5, declared_size, payload_end = struct.unpack_from("<8I", data, 0)
    if (w0 & 0xFFFF) != IDT_SSBOOT_MAGIC_LOW16:
        raise SabinParseError(
            f"{filename}: expected low16 {IDT_SSBOOT_MAGIC_LOW16:#06x}, got {w0 & 0xFFFF:#06x}"
        )
    if declared_size != len(data):
        raise SabinParseError(
            f"{filename}: declared size {declared_size} != actual size {len(data)}"
        )
    return IdtSsbootHeader(
        filename=filename,
        size=len(data),
        sha256=_sha256(data),
        word0=w0,
        word1=w1,
        flags=flags,
        code_offset=code_offset,
        word4=w4,
        word5=w5,
        declared_size=declared_size,
        payload_end=payload_end,
    )


def _classify_spica(path: Path, data: bytes) -> SpicaMusashiEntry:
    stem = path.stem.removeprefix("spica_musashi_")
    channel = "Y (luma)" if "_y_tap_" in stem else ("C (chroma)" if "_c_tap_" in stem else "unknown")
    step = "step1" if stem.endswith("step1") else ("step2" if stem.endswith("step2") else "unknown")
    mode = stem.split("_y_tap_")[0].split("_c_tap_")[0]
    return SpicaMusashiEntry(
        filename=path.name,
        size=len(data),
        sha256=_sha256(data),
        mode=mode,
        channel=channel,
        step=step,
    )


def scan_sabin_tree(sabin_dirs: tuple[Path, ...] | list[Path]) -> SabinInventory:
    """Scan one or more ``sabin/`` directories and parse all recognized binary families."""
    sa_modules: list[SaModuleHeader] = []
    dcv_tables: list[DcvPsfHeader] = []
    idt_ssboot: list[IdtSsbootHeader] = []
    spica_tables: list[SpicaMusashiEntry] = []
    other_files: list[tuple[str, int, str]] = []

    for directory in sabin_dirs:
        if not directory.exists():
            continue
        for path in sorted(directory.iterdir()):
            if not path.is_file():
                continue
            data = path.read_bytes()
            name = path.name
            if name.startswith("sa_") and len(data) >= 4 and struct.unpack_from("<I", data, 0)[0] == SA_MAGIC:
                sa_modules.append(parse_sa_module(data, name))
            elif name.startswith("dcv_psf_table_") and data[:4] == DCV_MAGIC:
                dcv_tables.append(parse_dcv_psf(data, name))
            elif name in ("idt_cam.bin", "ssboot.bin", "ssboot_any.bin"):
                idt_ssboot.append(parse_idt_ssboot(data, name))
            elif name.startswith("spica_musashi_"):
                spica_tables.append(_classify_spica(path, data))
            else:
                other_files.append((name, len(data), _sha256(data)))

    return SabinInventory(
        sa_modules=tuple(sa_modules),
        dcv_tables=tuple(dcv_tables),
        idt_ssboot=tuple(idt_ssboot),
        spica_tables=tuple(spica_tables),
        other_files=tuple(other_files),
    )
