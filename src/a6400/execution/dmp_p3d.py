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


def tile_morton_8x8(
    data: bytes,
    width: int,
    height: int,
    bpp: int,
) -> bytes:
    """Convert a linear row-major buffer to 8x8 Morton-tiled DMP format."""
    if width <= 0 or height <= 0:
        raise ValueError(f'Invalid dimensions: {width}x{height}')
    if bpp not in (1, 2, 4):
        raise ValueError(f'Unsupported bpp={bpp}; expected 1, 2, or 4')

    row_stride = width * bpp
    if len(data) < row_stride * height:
        raise ValueError(
            f'Linear buffer too small: got {len(data)} bytes, need {row_stride * height}'
        )

    tiles_x = (width + 7) // 8
    tiles_y = (height + 7) // 8
    tile_stride = 64 * bpp
    out = bytearray(tiles_x * tiles_y * tile_stride)

    for y in range(height):
        ty = y >> 3
        ly = y & 7
        src_row_off = y * row_stride
        tile_row_base = ty * tiles_x * tile_stride
        for x in range(width):
            tx = x >> 3
            lx = x & 7
            src_off = src_row_off + x * bpp
            dst_off = tile_row_base + tx * tile_stride + morton_index_8x8(lx, ly) * bpp
            out[dst_off : dst_off + bpp] = data[src_off : src_off + bpp]

    return bytes(out)


def flip_vertical(data: bytes, width: int, height: int, bpp: int) -> bytes:
    """Vertically flip a linear row-major pixel buffer."""
    row_stride = width * bpp
    if len(data) < row_stride * height:
        raise ValueError(
            f'Linear buffer too small for flip: got {len(data)}, need {row_stride * height}'
        )
    out = bytearray(row_stride * height)
    for y in range(height):
        src_off = (height - 1 - y) * row_stride
        dst_off = y * row_stride
        out[dst_off : dst_off + row_stride] = data[src_off : src_off + row_stride]
    return bytes(out)


#: PPF format codes from Oein/a5000-emulator (RE_DISPLAY_GPU.md §2.3).
PPF_FMT_BPP = {
    0: 4,  # RGBA8
    1: 3,  # RGB8
    2: 2,  # RGB565
    3: 2,  # RGB5A1
    4: 2,  # RGBA4444
}

#: Sugilite GPU MMIO offsets and IRQ status bits (RE_DISPLAY_GPU.md §2.2-2.4).
SUGI_REG_PSC_START = 0x0010
SUGI_REG_PSC_END = 0x0014
SUGI_REG_PSC_VALUE = 0x0018
SUGI_REG_PSC_CTRL = 0x001C
SUGI_REG_IRQ_STATUS = 0x0034
SUGI_REG_PPF_SRC = 0x0C00
SUGI_REG_PPF_DST = 0x0C04
SUGI_REG_PPF_DIM0 = 0x0C08
SUGI_REG_PPF_DIM1 = 0x0C0C
SUGI_REG_PPF_FLAGS = 0x0C10
SUGI_REG_PPF_TRIGGER = 0x0C18
SUGI_REG_PPF_COPY_SIZE = 0x0C20
SUGI_REG_P3D_ACK = 0x1000
SUGI_REG_P3D_KICK = 0x1800
SUGI_REG_P3D_LIST_PA = 0x1804

SUGI_IRQ_P3D_DONE = 1 << 31
SUGI_IRQ_PPF_DONE = 1 << 30
SUGI_IRQ_PSC0_DONE = 1 << 26


def execute_ppf_transfer(
    memory_reader: Callable[[int, int], Optional[bytes]],
    memory_writer: Callable[[int, bytes], None],
    src_pa: int,
    dst_pa: int,
    width: int,
    height: int,
    flags: int,
    copy_size: int = 0,
) -> Tuple[bool, str]:
    """Execute a DMP PPF display transfer or texture copy.

    Follows the register semantics documented in ``Oein/a5000-emulator``
    (``docs/RE_DISPLAY_GPU.md`` §2.3, CC BY 4.0):
    - ``flags & 8``: raw linear texture copy of ``copy_size`` bytes.
    - ``flags & 2``: 0 = 8x8 Morton-tiled -> linear; 1 = linear -> 8x8 tiled.
    - ``flags & 1``: vertical flip (used to convert GL y-up to panel y-down).
    """
    if flags & 8:
        if copy_size <= 0:
            return False, 'ppf-copy-zero-size'
        raw = memory_reader(src_pa, copy_size)
        if raw is None or len(raw) < copy_size:
            return False, f'ppf-unmapped-src:0x{src_pa:08x}'
        memory_writer(dst_pa, raw[:copy_size])
        return True, 'ppf-copy'

    if width <= 0 or height <= 0:
        return False, f'ppf-invalid-dims:{width}x{height}'

    in_fmt = (flags >> 8) & 0x7
    out_fmt = (flags >> 12) & 0x7
    if in_fmt != out_fmt:
        return False, f'ppf-unsupported-fmt-conv:{in_fmt}->{out_fmt}'

    bpp = PPF_FMT_BPP.get(in_fmt)
    if bpp not in (2, 4):
        return False, f'ppf-unsupported-bpp:fmt={in_fmt}'

    flip_v = bool(flags & 1)
    linear_to_tiled = bool(flags & 2)

    if linear_to_tiled:
        needed = width * height * bpp
        raw = memory_reader(src_pa, needed)
        if raw is None or len(raw) < needed:
            return False, f'ppf-unmapped-src:0x{src_pa:08x}'
        pixels = flip_vertical(raw[:needed], width, height, bpp) if flip_v else raw[:needed]
        out = tile_morton_8x8(pixels, width, height, bpp)
        memory_writer(dst_pa, out)
        return True, 'ppf-linear-to-tiled'

    tiles_x = (width + 7) // 8
    tiles_y = (height + 7) // 8
    needed = tiles_x * tiles_y * 64 * bpp
    raw = memory_reader(src_pa, needed)
    if raw is None or len(raw) < needed:
        return False, f'ppf-unmapped-src:0x{src_pa:08x}'
    linear = detile_morton_8x8(raw[:needed], width, height, bpp)
    out = flip_vertical(linear, width, height, bpp) if flip_v else linear
    memory_writer(dst_pa, out)
    return True, 'ppf-tiled-to-linear'


class SugiliteMmioModel:
    """Clean-room MMIO & IRQ state machine for DMP SMAPH-S30 (``BAR 0xF1000000``).

    Models the P3D kick (``+0x1800``/``+0x1804``), PPF transfer (``+0xC00..0xC18``),
    PSC memory fill (``+0x010..0x01C``), and level-high IRQ status/ack contract
    (``+0x034`` bits 31/30/26) documented in ``Oein/a5000-emulator``
    (``docs/RE_DISPLAY_GPU.md`` §2.2-2.4, CC BY 4.0).
    """

    def __init__(
        self,
        memory_reader: Optional[Callable[[int, int], Optional[bytes]]] = None,
        memory_writer: Optional[Callable[[int, bytes], None]] = None,
    ) -> None:
        self._memory_reader = memory_reader
        self._memory_writer = memory_writer
        self.regs: Dict[int, int] = {}
        self.irq_status: int = 0
        self.p3d_results: List[P3dDecodeResult] = []
        self.ppf_events: List[Tuple[bool, str]] = []
        self.psc_fills: int = 0

    @property
    def irq_asserted(self) -> bool:
        """True while any completion bit is pending in ``+0x034``."""
        return self.irq_status != 0

    def read_reg(self, offset: int) -> int:
        if offset == SUGI_REG_IRQ_STATUS:
            return self.irq_status
        return self.regs.get(offset, 0)

    def write_reg(self, offset: int, value: int) -> None:
        val = value & 0xFFFFFFFF
        self.regs[offset] = val

        # ISR acks clear the corresponding status bit and drop IRQ when 0.
        if offset == SUGI_REG_P3D_ACK and val == 0:
            self.irq_status &= ~SUGI_IRQ_P3D_DONE
            return
        if offset == SUGI_REG_PPF_TRIGGER:
            if val == 0:
                self.irq_status &= ~SUGI_IRQ_PPF_DONE
            else:
                self._run_ppf()
                self.irq_status |= SUGI_IRQ_PPF_DONE
            return
        if offset == SUGI_REG_PSC_CTRL:
            if val == 0:
                self.irq_status &= ~SUGI_IRQ_PSC0_DONE
            elif val & 1:
                self._run_psc()
                self.irq_status |= SUGI_IRQ_PSC0_DONE
            return
        if offset == SUGI_REG_P3D_KICK and val > 0:
            list_pa = self.regs.get(SUGI_REG_P3D_LIST_PA, 0)
            decoder = P3dCommandListDecoder(memory_reader=self._memory_reader)
            self.p3d_results.append(decoder.decode_from_memory(list_pa, val))
            self.irq_status |= SUGI_IRQ_P3D_DONE

    def _run_ppf(self) -> None:
        if self._memory_reader is None or self._memory_writer is None:
            self.ppf_events.append((False, 'no-memory-hooks'))
            return
        src_pa = (self.regs.get(SUGI_REG_PPF_SRC, 0) << 2) & 0xFFFFFFFF
        dst_pa = (self.regs.get(SUGI_REG_PPF_DST, 0) << 2) & 0xFFFFFFFF
        dim0 = self.regs.get(SUGI_REG_PPF_DIM0, 0)
        width = dim0 & 0xFFFF
        height = (dim0 >> 16) & 0xFFFF
        flags = self.regs.get(SUGI_REG_PPF_FLAGS, 0)
        copy_size = self.regs.get(SUGI_REG_PPF_COPY_SIZE, 0)
        self.ppf_events.append(
            execute_ppf_transfer(
                self._memory_reader,
                self._memory_writer,
                src_pa,
                dst_pa,
                width,
                height,
                flags,
                copy_size=copy_size,
            )
        )

    def _run_psc(self) -> None:
        if self._memory_writer is None:
            return
        start_pa = (self.regs.get(SUGI_REG_PSC_START, 0) << 3) & 0xFFFFFFFF
        end_pa = (self.regs.get(SUGI_REG_PSC_END, 0) << 3) & 0xFFFFFFFF
        fill_val = self.regs.get(SUGI_REG_PSC_VALUE, 0)
        if end_pa > start_pa and (end_pa - start_pa) <= 0x02000000:
            length = end_pa - start_pa
            word = struct.pack('<I', fill_val)
            payload = (word * ((length + 3) // 4))[:length]
            self._memory_writer(start_pa, payload)
            self.psc_fills += 1

