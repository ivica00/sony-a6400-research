"""Clean-room DMP SMAPH / P3D command-list decoder and 8x8 Morton detiler.

Implements the DMP P3D 8-byte ``[header][value]`` command-list format and
8x8 Morton-tiled surface detiling documented in ``Oein/a5000-emulator``
(``docs/RE_GPU_P3D_CMD.md``, CC BY 4.0, by Park SungHyun / Oein).

Note on provenance:
    The command-list encoding and register layout were documented on Sony
    ILCE-5000 (``CXD90014``) ``libObj.so`` (DMP-EGL / SMAPH-S30).  ``CXD90045``
    (``ILCE-6400``) uses the same DMP-EGL / ``gl_common`` stack, but exact
    register parity on ``CXD90045`` command lists must be confirmed against
    captured or replayed ``gl_common`` submissions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import struct
from typing import Callable, Dict, List, Optional, Tuple

#: P3D register numbers documented in Oein/a5000-emulator (RE_GPU_P3D_CMD.md).
P3D_REG_FINALIZE = 0x010
P3D_FINALIZE_MAGIC = 0x12345678
P3D_REG_CULLING = 0x041
P3D_REG_VIEWPORT_HALF_W = 0x042
P3D_REG_VIEWPORT_HALF_H = 0x043
P3D_REG_SCISSOR_MIN = 0x047
P3D_REG_SCISSOR_MAX = 0x048
P3D_REG_VIEWPORT_CENTER_2X = 0x049
P3D_REG_FB_FORMAT = 0x110
P3D_REG_SYNC_PA_SHIFT4 = 0x116
P3D_REG_SYNC_ENABLE = 0x117
P3D_REG_DRAW_KICK = 0x202
P3D_REG_TEX_USE = 0x580

P3D_HEADER_CALL_BIT = 1 << 0
P3D_HEADER_AUTO_INC_BIT = 1 << 1
P3D_HEADER_BURST_BIT = 1 << 2
P3D_MAX_CALL_DEPTH = 4
P3D_REG_FILE_SIZE = 4096


def _byte_enable_mask(byte_enable: int) -> int:
    """Convert a 4-bit P3D byte-enable nibble into a 32-bit write mask."""
    mask = 0
    for byte_idx in range(4):
        if (byte_enable >> byte_idx) & 1:
            mask |= 0xFF << (byte_idx * 8)
    return mask


def _write_masked_reg(
    regs: Dict[int, int],
    reg: int,
    value: int,
    mask: int,
) -> None:
    """Apply a masked 32-bit write to the P3D register file."""
    if mask == 0 or not (0 <= reg < P3D_REG_FILE_SIZE):
        return
    if mask == 0xFFFFFFFF:
        regs[reg] = value & 0xFFFFFFFF
    else:
        prev = regs.get(reg, 0)
        regs[reg] = ((prev & ~mask) | (value & mask)) & 0xFFFFFFFF


@dataclass(frozen=True)
class P3dDrawEvent:
    """Snapshot of key P3D registers at a ``0x202`` draw kick."""

    kick_index: int
    kick_value: int
    culling: int
    fb_format: int
    viewport_center_2x: int
    scissor_min: int
    scissor_max: int
    tex_use: int


@dataclass
class P3dDecodeResult:
    """Result of walking a DMP P3D command list."""

    registers: Dict[int, int] = field(default_factory=dict)
    draws: List[P3dDrawEvent] = field(default_factory=list)
    entries_executed: int = 0
    sublist_calls: int = 0
    finalized: bool = False
    stop_reason: Optional[str] = None


class P3dCommandListDecoder:
    """Walks DMP P3D 8-byte ``[header][value]`` command lists.

    Supports single writes, byte-enable masking, burst transfers (with or
    without register auto-increment and 8-byte zero-padding), and nested
    ``call`` sublists up to ``P3D_MAX_CALL_DEPTH``.
    """

    def __init__(
        self,
        memory_reader: Optional[Callable[[int, int], Optional[bytes]]] = None,
        max_call_depth: int = P3D_MAX_CALL_DEPTH,
        max_entries: int = 65536,
    ) -> None:
        self._memory_reader = memory_reader
        self._max_call_depth = max_call_depth
        self._max_entries = max_entries

    def decode_bytes(self, data: bytes) -> P3dDecodeResult:
        """Decode a top-level command list buffer."""
        result = P3dDecodeResult()
        self._execute_buffer(data, result, depth=0)
        return result

    def decode_from_memory(self, phys_addr: int, entry_count: int) -> P3dDecodeResult:
        """Read and decode ``entry_count`` 8-byte entries from ``phys_addr``."""
        result = P3dDecodeResult()
        if self._memory_reader is None:
            result.stop_reason = 'no-memory-reader'
            return result
        if entry_count <= 0:
            return result
        raw = self._memory_reader(phys_addr, entry_count * 8)
        if raw is None or len(raw) < entry_count * 8:
            result.stop_reason = f'unmapped-list:0x{phys_addr:08x}'
            return result
        self._execute_buffer(raw[: entry_count * 8], result, depth=0)
        return result

    def _record_write(
        self,
        reg: int,
        value: int,
        mask: int,
        result: P3dDecodeResult,
    ) -> None:
        if mask == 0:
            return
        _write_masked_reg(result.registers, reg, value, mask)
        if reg == P3D_REG_FINALIZE and result.registers.get(reg) == P3D_FINALIZE_MAGIC:
            result.finalized = True
        elif reg == P3D_REG_DRAW_KICK:
            regs = result.registers
            result.draws.append(
                P3dDrawEvent(
                    kick_index=len(result.draws),
                    kick_value=regs.get(P3D_REG_DRAW_KICK, 0),
                    culling=regs.get(P3D_REG_CULLING, 0),
                    fb_format=regs.get(P3D_REG_FB_FORMAT, 0),
                    viewport_center_2x=regs.get(P3D_REG_VIEWPORT_CENTER_2X, 0),
                    scissor_min=regs.get(P3D_REG_SCISSOR_MIN, 0),
                    scissor_max=regs.get(P3D_REG_SCISSOR_MAX, 0),
                    tex_use=regs.get(P3D_REG_TEX_USE, 0),
                )
            )

    def _execute_buffer(
        self,
        data: bytes,
        result: P3dDecodeResult,
        depth: int,
    ) -> None:
        if len(data) % 8 != 0:
            result.stop_reason = f'unaligned-list-size:{len(data)}'
            return

        offset = 0
        total_len = len(data)
        while offset + 8 <= total_len:
            if result.entries_executed >= self._max_entries:
                result.stop_reason = f'entry-limit:{self._max_entries}'
                return
            header, value = struct.unpack_from('<II', data, offset)
            offset += 8
            result.entries_executed += 1

            if header & P3D_HEADER_CALL_BIT:
                if depth >= self._max_call_depth:
                    result.stop_reason = f'call-depth-exceeded:{depth + 1}'
                    return
                if self._memory_reader is None:
                    result.stop_reason = f'call-without-memory-reader:0x{value:08x}'
                    return
                sub_count = (header >> 3) & 0x1FF
                result.sublist_calls += 1
                if sub_count > 0:
                    sub_bytes = self._memory_reader(value, sub_count * 8)
                    if sub_bytes is None or len(sub_bytes) < sub_count * 8:
                        result.stop_reason = f'unmapped-sublist:0x{value:08x}'
                        return
                    self._execute_buffer(sub_bytes[: sub_count * 8], result, depth + 1)
                    if result.stop_reason is not None:
                        return
                continue

            reg = (header >> 16) & 0xFFF
            mask = _byte_enable_mask((header >> 12) & 0xF)
            self._record_write(reg, value, mask, result)

            if header & P3D_HEADER_BURST_BIT:
                extra_words = (header >> 3) & 0x1FF
                auto_inc = bool(header & P3D_HEADER_AUTO_INC_BIT)
                needed_bytes = ((extra_words + 1) // 2) * 8
                if offset + needed_bytes > total_len:
                    result.stop_reason = 'truncated-burst'
                    return
                for idx in range(extra_words):
                    word = struct.unpack_from('<I', data, offset + idx * 4)[0]
                    target_reg = reg + 1 + idx if auto_inc else reg
                    self._record_write(target_reg, word, mask, result)
                offset += needed_bytes


def morton_index_8x8(x_in_tile: int, y_in_tile: int) -> int:
    """Return the 0..63 Z-order (Morton) pixel index within an 8x8 tile."""
    x = x_in_tile & 7
    y = y_in_tile & 7
    return (
        (x & 1)
        | ((y & 1) << 1)
        | (((x >> 1) & 1) << 2)
        | (((y >> 1) & 1) << 3)
        | (((x >> 2) & 1) << 4)
        | (((y >> 2) & 1) << 5)
    )


def detile_morton_8x8(
    data: bytes,
    width: int,
    height: int,
    bpp: int,
) -> bytes:
    """Convert an 8x8 Morton-tiled DMP buffer to linear row-major pixels.

    Args:
        data: Tiled pixel bytes. Must cover ``aligned_w * aligned_h * bpp``
            where dimensions are rounded up to multiples of 8.
        width: Logical image width in pixels.
        height: Logical image height in pixels.
        bpp: Bytes per pixel (1 for A8/L8, 2 for RGBA4444/RGB565, 4 for RGBA8).
    """
    if width <= 0 or height <= 0:
        raise ValueError(f'Invalid dimensions: {width}x{height}')
    if bpp not in (1, 2, 4):
        raise ValueError(f'Unsupported bpp={bpp}; expected 1, 2, or 4')

    tiles_x = (width + 7) // 8
    tiles_y = (height + 7) // 8
    required = tiles_x * tiles_y * 64 * bpp
    if len(data) < required:
        raise ValueError(
            f'Tiled buffer too small: got {len(data)} bytes, need {required}'
        )

    out = bytearray(width * height * bpp)
    tile_stride = 64 * bpp
    row_stride = width * bpp

    for y in range(height):
        ty = y >> 3
        ly = y & 7
        dst_row_off = y * row_stride
        tile_row_base = ty * tiles_x * tile_stride
        for x in range(width):
            tx = x >> 3
            lx = x & 7
            src_off = tile_row_base + tx * tile_stride + morton_index_8x8(lx, ly) * bpp
            dst_off = dst_row_off + x * bpp
            out[dst_off : dst_off + bpp] = data[src_off : src_off + bpp]

    return bytes(out)
