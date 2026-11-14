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
    SUGI_IRQ_P3D_DONE,
    SUGI_IRQ_PPF_DONE,
    SUGI_IRQ_PSC0_DONE,
    SUGI_REG_IRQ_STATUS,
    SUGI_REG_P3D_ACK,
    SUGI_REG_P3D_KICK,
    SUGI_REG_P3D_LIST_PA,
    SUGI_REG_PPF_DIM0,
    SUGI_REG_PPF_DST,
    SUGI_REG_PPF_FLAGS,
    SUGI_REG_PPF_SRC,
    SUGI_REG_PPF_TRIGGER,
    SUGI_REG_PSC_CTRL,
    SUGI_REG_PSC_END,
    SUGI_REG_PSC_START,
    SUGI_REG_PSC_VALUE,
    SugiliteMmioModel,
    detile_morton_8x8,
    morton_index_8x8,
    tile_morton_8x8,
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

    def test_tile_and_detile_round_trip_rgba8(self) -> None:
        width, height, bpp = 8, 8, 4
        linear = bytes((i & 0xFF) for i in range(width * height * bpp))
        tiled = tile_morton_8x8(linear, width, height, bpp)
        self.assertEqual(detile_morton_8x8(tiled, width, height, bpp), linear)


class TestSugiliteMmioModel(unittest.TestCase):
    def test_ppf_tiled_to_linear_with_vertical_flip_and_irq_ack(self) -> None:
        # 8x8 RGBA4444 buffer where row 0 has 0x000F and row 7 has 0xF00F.
        width, height, bpp = 8, 8, 2
        gl_linear = bytearray(width * height * bpp)
        for x in range(width):
            struct.pack_into('<H', gl_linear, x * 2, 0x000F)
            struct.pack_into('<H', gl_linear, (7 * width + x) * 2, 0xF00F)
        tiled = tile_morton_8x8(bytes(gl_linear), width, height, bpp)

        src_pa = 0x202E0000
        dst_pa = 0x23A80000
        ram = bytearray(0x04000000)
        base = 0x20000000
        ram[src_pa - base : src_pa - base + len(tiled)] = tiled

        def reader(addr: int, size: int) -> bytes | None:
            off = addr - base
            if 0 <= off and off + size <= len(ram):
                return bytes(ram[off : off + size])
            return None

        def writer(addr: int, data: bytes) -> None:
            off = addr - base
            ram[off : off + len(data)] = data

        gpu = SugiliteMmioModel(memory_reader=reader, memory_writer=writer)
        gpu.write_reg(SUGI_REG_PPF_SRC, src_pa >> 2)
        gpu.write_reg(SUGI_REG_PPF_DST, dst_pa >> 2)
        gpu.write_reg(SUGI_REG_PPF_DIM0, width | (height << 16))
        gpu.write_reg(SUGI_REG_PPF_FLAGS, 0x4401)  # RGBA4 -> RGBA4 + flip-V
        gpu.write_reg(SUGI_REG_PPF_TRIGGER, 1)

        self.assertTrue(gpu.irq_asserted)
        self.assertEqual(gpu.read_reg(SUGI_REG_IRQ_STATUS), SUGI_IRQ_PPF_DONE)
        self.assertEqual(gpu.ppf_events[-1], (True, 'ppf-tiled-to-linear'))

        # After vertical flip, row 0 of dst_pa must be 0xF00F and row 7 must be 0x000F.
        out_row0 = struct.unpack_from('<H', ram, dst_pa - base)[0]
        out_row7 = struct.unpack_from('<H', ram, dst_pa - base + 7 * width * 2)[0]
        self.assertEqual(out_row0, 0xF00F)
        self.assertEqual(out_row7, 0x000F)

        # ISR ack clears bit 30 and drops IRQ.
        gpu.write_reg(SUGI_REG_PPF_TRIGGER, 0)
        self.assertFalse(gpu.irq_asserted)
        self.assertEqual(gpu.read_reg(SUGI_REG_IRQ_STATUS), 0)

    def test_p3d_and_psc_kicks_and_acks(self) -> None:
        base = 0x20000000
        ram = bytearray(0x10000)
        list_pa = base + 0x1000
        cmd_list = b''.join([
            _entry(P3D_REG_CULLING, 2),
            _entry(P3D_REG_FINALIZE, P3D_FINALIZE_MAGIC),
        ])
        ram[0x1000 : 0x1000 + len(cmd_list)] = cmd_list

        def reader(addr: int, size: int) -> bytes | None:
            off = addr - base
            return bytes(ram[off : off + size]) if 0 <= off and off + size <= len(ram) else None

        def writer(addr: int, data: bytes) -> None:
            off = addr - base
            ram[off : off + len(data)] = data

        gpu = SugiliteMmioModel(memory_reader=reader, memory_writer=writer)
        gpu.write_reg(SUGI_REG_P3D_LIST_PA, list_pa)
        gpu.write_reg(SUGI_REG_P3D_KICK, 2)
        self.assertEqual(gpu.read_reg(SUGI_REG_IRQ_STATUS), SUGI_IRQ_P3D_DONE)
        self.assertTrue(gpu.p3d_results[-1].finalized)

        gpu.write_reg(SUGI_REG_P3D_ACK, 0)
        self.assertFalse(gpu.irq_asserted)

        # PSC fill
        fill_start = base + 0x2000
        fill_end = base + 0x2040
        gpu.write_reg(SUGI_REG_PSC_START, fill_start >> 3)
        gpu.write_reg(SUGI_REG_PSC_END, fill_end >> 3)
        gpu.write_reg(SUGI_REG_PSC_VALUE, 0xCAFECAFE)
        gpu.write_reg(SUGI_REG_PSC_CTRL, 0x0F010201)
        self.assertEqual(gpu.read_reg(SUGI_REG_IRQ_STATUS), SUGI_IRQ_PSC0_DONE)
        self.assertEqual(struct.unpack_from('<I', ram, 0x2000)[0], 0xCAFECAFE)

        gpu.write_reg(SUGI_REG_PSC_CTRL, 0)
        self.assertFalse(gpu.irq_asserted)

    def test_guest_gles_poll_p3d_bar_opt_in(self) -> None:
        from src.a6400.execution.guest_gles import GlesBinding, GuestGles
        from src.a6400.execution.kernel_task_identity import KernelTaskObservation

        obs = KernelTaskObservation(
            thread_info=0x60000000,
            task=0x60001000,
            pid=100,
            tgid=100,
            address_limit=0x5F000000,
            cpu=0,
        )
        gles = GuestGles(GlesBinding(obs))
        gles.bar_virtual = 0x40000000

        bar_mem = bytearray(0x4000)
        base = 0x20000000
        ram = bytearray(0x10000)
        list_pa = base + 0x1000
        cmd_list = _entry(P3D_REG_FINALIZE, P3D_FINALIZE_MAGIC)
        ram[0x1000 : 0x1000 + len(cmd_list)] = cmd_list

        def bar_read(addr: int, size: int) -> bytes:
            off = addr - gles.bar_virtual
            return bytes(bar_mem[off : off + size])

        def bar_write(addr: int, data: bytes) -> None:
            off = addr - gles.bar_virtual
            bar_mem[off : off + len(data)] = data

        def phys_read(addr: int, size: int) -> bytes | None:
            off = addr - base
            return bytes(ram[off : off + size]) if 0 <= off and off + size <= len(ram) else None

        struct.pack_into('<I', bar_mem, SUGI_REG_P3D_LIST_PA, list_pa)
        struct.pack_into('<I', bar_mem, SUGI_REG_P3D_KICK, 1)

        # Default p3d_model=False leaves BAR untouched.
        self.assertEqual(gles.poll_p3d_bar(bar_read, bar_write, phys_read), 0)
        self.assertEqual(struct.unpack_from('<I', bar_mem, SUGI_REG_P3D_KICK)[0], 1)

        # Opt-in p3d_model=True executes list, updates BAR+0x34 & dev_a8, clears kick.
        gles.p3d_model = True
        status = gles.poll_p3d_bar(bar_read, bar_write, phys_read)
        self.assertEqual(status, SUGI_IRQ_P3D_DONE)
        self.assertEqual(gles.dev_a8, SUGI_IRQ_P3D_DONE)
        self.assertEqual(struct.unpack_from('<I', bar_mem, SUGI_REG_IRQ_STATUS)[0], SUGI_IRQ_P3D_DONE)
        self.assertEqual(struct.unpack_from('<I', bar_mem, SUGI_REG_P3D_KICK)[0], 0)
        self.assertTrue(gles._p3d_mmio.p3d_results[-1].finalized)


class TestGicItargetsrPreRoute(unittest.TestCase):
    def _make_machine(self):
        from src.a6400.execution.machine_contract import build_atags
        from src.a6400.execution.unicorn_machine import UnicornMachine
        from tests.emulator.test_data_abort import tiny_kernel
        return UnicornMachine(
            tiny_kernel(),
            b'\x00' * 64,
            build_atags('console=ttyAM0', [(0, 0x40000000)]),
            machine_id=0x0DA9,
            instruction_limit=100,
        )

    def test_spis_default_to_cpu0(self) -> None:
        try:
            machine = self._make_machine()
        except ImportError as exc:
            self.skipTest(f'Unicorn/ctypes unavailable in this shell: {exc}')
        self.assertEqual(machine._gic_regs.get(('dist', 0x820)), 0x01010101)
        self.assertEqual(machine._gic_regs.get(('dist', 0xBFC)), 0x01010101)
        self.assertNotIn(('dist', 0x800), machine._gic_regs)

    def test_sugilite_clock_and_mmio_wired(self) -> None:
        try:
            from src.a6400.execution.unicorn_machine import SUGILITE_IRQ
            machine = self._make_machine()
        except ImportError as exc:
            self.skipTest(f'Unicorn/ctypes unavailable in this shell: {exc}')
        self.assertEqual(SUGILITE_IRQ, 76)
        self.assertIsNotNone(machine._sugilite_mmio)


if __name__ == '__main__':
    unittest.main()
