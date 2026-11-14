"""Mapper and MMIO register-bank emulator for ``av-cam.bin`` Imager sensor tables.

Locates ``Camera::Imager`` RTTI/vtables, sensor readout geometry tables,
video/recording mode strings, ``/usr/sabin/`` references, and
``0xFC09xxxx..0xFC0Axxxx`` Imager/ComboPHY/AIF MMIO register sequences.
"""
from __future__ import annotations

import hashlib
import re
import struct
from dataclasses import dataclass

ORIL_BASE = 0x635C6000
ORIL_MAGIC = b"ORIL"
MMIO_BASE = 0xFC090000
MMIO_END = 0xFC0B0000


class ImagerTableError(ValueError):
    """Raised when ``av-cam.bin`` does not match the ORIL v4 Imager contract."""


@dataclass(frozen=True)
class SensorGeometry:
    """20-byte (10 x u16) sensor readout/crop descriptor."""

    va: int
    raw_w: int
    raw_h: int
    off_x: int
    off_y: int
    eff_w: int
    eff_h: int
    crop_x: int
    crop_y: int
    active_w: int
    active_h: int


@dataclass(frozen=True)
class MmioWrite:
    """A single ``(reg_addr, value)`` pair from an Imager MMIO table."""

    table_va: int
    reg_addr: int
    value: int


@dataclass(frozen=True)
class SensorTimingEntry:
    """12-byte (3 x u32) sensor mode timing/line-count descriptor."""

    va: int
    flags: int
    h_param: int
    v_param: int


@dataclass(frozen=True)
class ImagerTableSummary:
    """Structured map of ``av-cam.bin`` sensor/imager tables and mode strings."""

    size: int
    sha256: str
    oril_version: int
    oril_entry: int
    imager_classes: dict[str, tuple[int, ...]]
    imx_identifiers: tuple[str, ...]
    geometries: tuple[SensorGeometry, ...]
    timing_entries: tuple[SensorTimingEntry, ...]
    video_mode_strings: tuple[str, ...]
    codec_strings: tuple[str, ...]
    active_encoder_engines: tuple[str, ...]
    enum_only_encoders: tuple[str, ...]
    sabin_refs: tuple[str, ...]
    mmio_tables: dict[int, tuple[MmioWrite, ...]]


def _find_imager_vtables(data: bytes) -> dict[str, tuple[int, ...]]:
    out: dict[str, tuple[int, ...]] = {}
    for m in re.finditer(rb"N6Camera6Imager[A-Za-z0-9_]+", data):
        name = m.group(0).decode("ascii")
        str_va = m.start() + ORIL_BASE
        ti_pat = struct.pack("<I", str_va)
        vtables: list[int] = []
        for ti_m in re.finditer(re.escape(ti_pat), data):
            ti_va = (ti_m.start() - 4) + ORIL_BASE
            vt_pat = struct.pack("<I", ti_va)
            for vt_m in re.finditer(re.escape(vt_pat), data):
                vtables.append(vt_m.start() + 4 + ORIL_BASE)
        out[name] = tuple(vtables)
    return out


def _extract_geometries(data: bytes) -> tuple[SensorGeometry, ...]:
    """Extract 20-byte (10 x u16) sensor readout geometries anchored at 6048x4108."""
    anchor = struct.pack("<HH", 6048, 4108)
    idx = data.find(anchor)
    if idx < 0:
        # Fallback: search for 6024x4024
        idx = data.find(struct.pack("<HH", 6024, 4024))
    if idx < 0:
        return ()

    geoms: list[SensorGeometry] = []
    pos = idx
    for _ in range(16):
        if pos + 20 > len(data):
            break
        vals = struct.unpack_from("<10H", data, pos)
        raw_w, raw_h, off_x, off_y, eff_w, eff_h, crop_x, crop_y, act_w, act_h = vals
        if raw_w < 320 or raw_h < 240 or raw_w > 8192 or raw_h > 6144:
            break
        if act_w == 0 or act_h == 0 or act_w > raw_w or act_h > raw_h:
            break
        geoms.append(
            SensorGeometry(
                va=pos + ORIL_BASE,
                raw_w=raw_w,
                raw_h=raw_h,
                off_x=off_x,
                off_y=off_y,
                eff_w=eff_w,
                eff_h=eff_h,
                crop_x=crop_x,
                crop_y=crop_y,
                active_w=act_w,
                active_h=act_h,
            )
        )
        pos += 20
    return tuple(geoms)


def _extract_timing_entries(data: bytes) -> tuple[SensorTimingEntry, ...]:
    """Extract 12-byte sensor timing/line-count entries anchored at (0x001b1d01, 862, 1740)."""
    anchor = struct.pack("<III", 0x001B1D01, 862, 1740)
    idx = data.find(anchor)
    if idx < 0:
        return ()
    entries: list[SensorTimingEntry] = []
    pos = idx
    for _ in range(32):
        if pos + 12 > len(data):
            break
        flags, h_param, v_param = struct.unpack_from("<III", data, pos)
        if not (200 <= h_param <= 8192 and 200 <= v_param <= 8192):
            break
        entries.append(
            SensorTimingEntry(
                va=pos + ORIL_BASE,
                flags=flags,
                h_param=h_param,
                v_param=v_param,
            )
        )
        pos += 12
    return tuple(entries)


def _extract_mmio_tables(data: bytes) -> dict[int, tuple[MmioWrite, ...]]:
    """Find ``.data`` pointers to ``0xFC09xxxx..0xFC0Axxxx`` register-write sequences."""
    tables: dict[int, tuple[MmioWrite, ...]] = {}
    scan_start = max(0, 0x64400000 - ORIL_BASE)
    candidate_vas: set[int] = set()
    for off in range(scan_start, len(data) - 4, 4):
        w = struct.unpack_from("<I", data, off)[0]
        if ORIL_BASE <= w < ORIL_BASE + len(data) - 16:
            toff = w - ORIL_BASE
            reg0 = struct.unpack_from("<I", data, toff)[0]
            if MMIO_BASE <= reg0 < MMIO_END and (reg0 & 0x3) == 0:
                candidate_vas.add(w)

    for tva in sorted(candidate_vas):
        toff = tva - ORIL_BASE
        writes: list[MmioWrite] = []
        pos = toff
        while pos + 8 <= len(data) and len(writes) < 64:
            reg, val = struct.unpack_from("<II", data, pos)
            if not (MMIO_BASE <= reg < MMIO_END) or (reg & 0x3) != 0:
                break
            writes.append(MmioWrite(table_va=tva, reg_addr=reg, value=val))
            pos += 8
        if len(writes) >= 2:
            tables[tva] = tuple(writes)
    return tables


def analyze_avcam_imager(data: bytes) -> ImagerTableSummary:
    """Analyze an unpacked ``av-cam.bin`` ORIL image for Imager tables and modes."""
    if len(data) < 0x40 or data[4:8] != ORIL_MAGIC:
        raise ImagerTableError("not an ORIL av-cam.bin image")
    oril_version, oril_entry = struct.unpack_from("<II", data, 8)

    imx_ids = tuple(
        sorted(set(m.group(0).decode("ascii") for m in re.finditer(rb"IMX\d+[A-Za-z0-9_]*", data)))
    )
    video_modes = tuple(
        sorted(set(m.group(0).decode("ascii") for m in re.finditer(rb"\d{3,4}[Xx]\d{3,4}[A-Za-z0-9_]*", data)))
    )
    codec_kws = (
        b"PRO_RES_QT",
        b"DNXHD_MXF",
        b"HEVC_MP4",
        b"XAVC_MXF_I",
        b"XAVC_MXF_L",
        b"XAVC_INTRA",
        b"MPEG2_HD422",
        b"MPEG4_SSTP",
        b"STREAMING_HEVC_FF",
        b"STREAMING_AVC_FF",
    )
    codecs = tuple(k.decode("ascii") for k in codec_kws if k in data)
    sabin_refs = tuple(
        sorted(set(m.group(0).decode("ascii") for m in re.finditer(rb"/[A-Za-z0-9_/\-\.]*sabin[A-Za-z0-9_/\-\.]*", data)))
    )

    active_encoders = tuple(
        name for name, kw in (("ZIMA_AVC/ZMA", b"ZIMA"), ("IMOLA_SEI", b"IMOLA")) if kw in data
    )
    enum_only = tuple(
        name
        for name, kw in (
            ("Beaune_L (XAVC_MXF_L)", b"Beaune_L"),
            ("Beaune_I (XAVC_MXF_I)", b"Beaune_I"),
            ("CURIE (HEVC_MP4)", b"CURIE"),
            ("FPGA_PRORES (PRO_RES_QT)", b"FPGA_PRORES"),
            ("FPGA_DNXHD (DNXHD_MXF)", b"FPGA_DNXHD"),
        )
        if data.count(kw) == 1
    )

    return ImagerTableSummary(
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        oril_version=oril_version,
        oril_entry=oril_entry,
        imager_classes=_find_imager_vtables(data),
        imx_identifiers=imx_ids,
        geometries=_extract_geometries(data),
        timing_entries=_extract_timing_entries(data),
        video_mode_strings=video_modes,
        codec_strings=codecs,
        active_encoder_engines=active_encoders,
        enum_only_encoders=enum_only,
        sabin_refs=sabin_refs,
        mmio_tables=_extract_mmio_tables(data),
    )


class ImagerMmioBank:
    """Bounded MMIO register bank emulator for ``0xFC090000..0xFC0B0000``."""

    def __init__(self) -> None:
        self.regs: dict[int, int] = {}
        self.history: list[tuple[int, int]] = []

    def _validate(self, addr: int) -> None:
        if not (MMIO_BASE <= addr < MMIO_END) or (addr & 0x3) != 0:
            raise ImagerTableError(f"Imager MMIO address out of bounds/unaligned: {addr:#x}")

    def write32(self, addr: int, value: int) -> None:
        self._validate(addr)
        val32 = value & 0xFFFFFFFF
        self.regs[addr] = val32
        self.history.append((addr, val32))

    def read32(self, addr: int) -> int:
        self._validate(addr)
        return self.regs.get(addr, 0)

    def apply_table(self, writes: tuple[MmioWrite, ...] | list[MmioWrite]) -> int:
        for w in writes:
            self.write32(w.reg_addr, w.value)
        return len(writes)
