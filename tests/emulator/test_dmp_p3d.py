"""Unit tests for the clean-room DMP SMAPH/P3D decoder, Morton detiler, and GIC SPI routing."""

from __future__ import annotations

import struct
import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.a6400.execution.dmp_p3d import (
    P3D_FINALIZE_MAGIC,
    P3D_HEADER_AUTO_INC_BIT,
    P3D_HEADER_BURST_BIT,
    P3D_HEADER_CALL_BIT,
    P3D_REG_CULLING,
    P3D_REG_DRAW_KICK,
    P3D_REG_FB_FORMAT,
    P3D_REG_FINALIZE,
    P3D_REG_TEX_USE,
    P3dCommandListDecoder,
    detile_morton_8x8,
    morton_index_8x8,
)


def _entry(reg: int, value: int, *, be: int = 0xF, flags: int = 0, count: int = 0) -> bytes:
    header = ((reg & 0xFFF) << 16) | ((be & 0xF) << 12) | ((count & 0x1FF) << 3) | (flags & 0x7)
    return struct.pack('<II', header, value & 0xFFFFFFFF)


class TestP3dCommandListDecoder(unittest.TestCase):
    def test_single_writes_byte_enable_and_finalize(self) -> None:
        buf = b''.join([
            _entry(P3D_REG_CULLING, 0x00000002),
            _entry(P3D_REG_FB_FORMAT, 0x00000004),
            _entry(0x100, 0x11223344),
            _entry(0x100, 0xAABBCCDD, be=0x3),  # low 2 bytes only
            _entry(0x100, 0xFFFFFFFF, be=0x0),  # no-op padding
            _entry(P3D_REG_FINALIZE, P3D_FINALIZE_MAGIC),
        ])
        res = P3dCommandListDecoder().decode_bytes(buf)
        self.assertIsNone(res.stop_reason)
        self.assertTrue(res.finalized)
        self.assertEqual(res.entries_executed, 6)
        self.assertEqual(res.registers[P3D_REG_CULLING], 2)
        self.assertEqual(res.registers[P3D_REG_FB_FORMAT], 4)
        self.assertEqual(res.registers[0x100], 0x1122CCDD)

    def test_burst_auto_inc_with_odd_padding_and_draw_kick(self) -> None:
        # Burst to 0x450 with auto-inc: first word -> 0x450, plus 3 extra words -> 0x451..0x453.
        # 3 extra words take 16 bytes (padded with trailing 0).
        burst_hdr = _entry(
            0x450,
            0x00000010,
            flags=P3D_HEADER_BURST_BIT | P3D_HEADER_AUTO_INC_BIT,
            count=3,
        )
        burst_tail = struct.pack('<IIII', 0x00000011, 0x00000012, 0x00000013, 0)
        buf = b''.join([
            _entry(P3D_REG_CULLING, 2),
            _entry(P3D_REG_FB_FORMAT, 4),
            _entry(P3D_REG_TEX_USE, 9),
            burst_hdr,
            burst_tail,
            _entry(P3D_REG_DRAW_KICK, 1),
        ])
        res = P3dCommandListDecoder().decode_bytes(buf)
        self.assertIsNone(res.stop_reason)
        self.assertEqual(res.registers[0x450], 0x10)
        self.assertEqual(res.registers[0x451], 0x11)
        self.assertEqual(res.registers[0x452], 0x12)
        self.assertEqual(res.registers[0x453], 0x13)
        self.assertEqual(len(res.draws), 1)
        self.assertEqual(res.draws[0].culling, 2)
        self.assertEqual(res.draws[0].fb_format, 4)
        self.assertEqual(res.draws[0].tex_use, 9)

    def test_sublist_call_and_depth_guard(self) -> None:
        sublist_pa = 0x8D7A1000
        sublist = b''.join([
            _entry(0x458, 0xCAFEBABE),
            _entry(0x459, 0xDEAD0001),
        ])
        main_pa = 0x8D7A0000
        main_list = b''.join([
            _entry(0, sublist_pa, flags=P3D_HEADER_CALL_BIT, count=2),
            _entry(P3D_REG_FINALIZE, P3D_FINALIZE_MAGIC),
        ])
        mem = {
            main_pa: main_list,
            sublist_pa: sublist,
        }

        def reader(addr: int, size: int) -> bytes | None:
            blob = mem.get(addr)
            return blob[:size] if blob is not None and len(blob) >= size else None

        res = P3dCommandListDecoder(memory_reader=reader).decode_from_memory(main_pa, 2)
        self.assertIsNone(res.stop_reason)
        self.assertTrue(res.finalized)
        self.assertEqual(res.sublist_calls, 1)
        self.assertEqual(res.registers[0x458], 0xCAFEBABE)
        self.assertEqual(res.registers[0x459], 0xDEAD0001)

        # Self-recursive sublist must stop cleanly at max_call_depth.
        loop_pa = 0x8D7A2000
        mem[loop_pa] = _entry(0, loop_pa, flags=P3D_HEADER_CALL_BIT, count=1)
        loop_res = P3dCommandListDecoder(memory_reader=reader, max_call_depth=2).decode_from_memory(loop_pa, 1)
        self.assertEqual(loop_res.stop_reason, 'call-depth-exceeded:3')


class TestMortonDetiler(unittest.TestCase):
    def test_detile_8x8_rgba4444_round_trip(self) -> None:
        width, height, bpp = 8, 8, 2
        tiled = bytearray(64 * bpp)
        expected = bytearray(width * height * bpp)
        for y in range(height):
            for x in range(width):
                val = ((y << 8) | x) & 0xFFFF
                pixel = struct.pack('<H', val)
                expected[(y * width + x) * bpp : (y * width + x + 1) * bpp] = pixel
                m_idx = morton_index_8x8(x, y)
                tiled[m_idx * bpp : (m_idx + 1) * bpp] = pixel

        self.assertEqual(detile_morton_8x8(bytes(tiled), width, height, bpp), bytes(expected))

    def test_detile_non_multiple_of_8_crops_cleanly(self) -> None:
        # 10x9 A8 image requires 2x2 tiles = 256 bytes of tiled input.
        width, height, bpp = 10, 9, 1
        tiled = bytearray(2 * 2 * 64 * bpp)
        # Pixel (9, 8) -> tile (1, 1), local (1, 0) -> morton index 1.
        tile_1_1_base = (1 * 2 + 1) * 64
        tiled[tile_1_1_base + morton_index_8x8(1, 0)] = 0xA5
        linear = detile_morton_8x8(bytes(tiled), width, height, bpp)
        self.assertEqual(len(linear), width * height)
        self.assertEqual(linear[8 * width + 9], 0xA5)


class TestGicItargetsrPreRoute(unittest.TestCase):
    def test_spis_default_to_cpu0(self) -> None:
        try:
            from src.a6400.execution.unicorn_machine import UnicornMachine
        except ImportError as exc:
            self.skipTest(f'Unicorn/ctypes unavailable in this shell: {exc}')
        machine = UnicornMachine()
        self.assertEqual(machine._gic_regs.get(('dist', 0x820)), 0x01010101)
        self.assertEqual(machine._gic_regs.get(('dist', 0xBFC)), 0x01010101)
        self.assertNotIn(('dist', 0x800), machine._gic_regs)


if __name__ == '__main__':
    unittest.main()
