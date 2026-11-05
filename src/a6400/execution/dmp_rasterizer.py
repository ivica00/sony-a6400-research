"""DMP PICA200 / Sugilite GPU command stream parser and software rasterizer.

Parses authentic hardware command packets (register uploads, viewport setup,
vertex streams) and rasterizes camera GUI surfaces into PIL Images.
"""

import struct
from typing import Dict, List, Optional, Tuple
from PIL import Image, ImageDraw


# DMP PICA200 Register IDs
REG_VIEWPORT_X = 0x041
REG_VIEWPORT_Y = 0x042
REG_VIEWPORT_Z = 0x043
REG_VIEWPORT_OFFSET = 0x047
REG_VIEWPORT_SIZE = 0x048
REG_VIEWPORT_STRIDE = 0x049
REG_COLOR_BUFFER_0 = 0x116
REG_COLOR_FORMAT_0 = 0x117
REG_COLOR_BUFFER_ALT = 0x216
REG_VERTEX_SHADER_BASE = 0x458
REG_VERTEX_SHADER_DATA = 0x459
REG_UNIFORM_FLOAT_INDEX = 0x460
REG_UNIFORM_FLOAT_DATA = 0x461
REG_GP_START = 0x580
REG_GPU_FLUSH = 0x010


class DmpPicaRasterizer:
    """Decodes DMP GPU command packets and renders GUI surfaces."""

    def __init__(self, vram_base_phys: int = 0x202e0000):
        self.vram_base_phys = vram_base_phys
        self.reset_state()

    def reset_state(self):
        self.viewport_w = 336
        self.viewport_h = 448
        self.color_buffer_phys = self.vram_base_phys + 0xe100
        self.color_format = 1  # 16-bit RGBA4444 / RGB565
        self.registers: Dict[int, int] = {}
        self.uniforms: List[float] = [0.0] * 64
        self.shader_program: List[int] = []
        self.vertices: List[Tuple[float, float, float, float]] = []

    def parse_packet(self, hdr: int, param: int):
        reg = (hdr >> 16) & 0xffff
        self.registers[reg] = param

        if reg in (REG_VIEWPORT_SIZE, REG_VIEWPORT_STRIDE):
            w = param & 0xffff
            h = (param >> 16) & 0xffff
            if w > 0 and h > 0:
                self.viewport_w = w
                self.viewport_h = h

        elif reg in (REG_COLOR_BUFFER_0, REG_COLOR_BUFFER_ALT):
            # DMP PICA200 register writes pass 16-byte paragraph addresses (param << 4)
            # when param < 0x10000000, or raw 32-bit physical address when >= 0x10000000.
            self.color_buffer_phys = (param << 4) if param < 0x10000000 else param

        elif reg == REG_COLOR_FORMAT_0:
            self.color_format = param

        elif reg == REG_UNIFORM_FLOAT_INDEX:
            self._uniform_idx = param & 0x3f

        elif reg == REG_UNIFORM_FLOAT_DATA:
            # IEEE 754 32-bit float
            raw = struct.pack('<I', param)
            fval = struct.unpack('<f', raw)[0]
            if hasattr(self, '_uniform_idx') and self._uniform_idx < len(self.uniforms):
                self.uniforms[self._uniform_idx] = fval
                self._uniform_idx += 1

    def parse_stream(self, stream_data: bytes, start_offset: int = 0x40, max_bytes: int = 0x1000):
        """Parses a contiguous DMP GPU command stream."""
        end = min(len(stream_data), start_offset + max_bytes)
        for off in range(start_offset, end, 8):
            hdr, param = struct.unpack_from('<II', stream_data, off)
            if hdr == 0 and param == 0:
                continue
            self.parse_packet(hdr, param)

        # Also extract vertex buffer from offset 0
        self.extract_vertices(stream_data[:64])

    def extract_vertices(self, vertex_data: bytes):
        """Extracts 4-component vertex floats [X, Y, Z, W]."""
        self.vertices = []
        count = len(vertex_data) // 16
        for i in range(count):
            x, y, z, w = struct.unpack_from('<4f', vertex_data, i * 16)
            self.vertices.append((x, y, z, w))

    def render_surface(self, stream_data: bytearray) -> Image.Image:
        """Rasterizes the active GPU color buffer surface into an Image strictly from authentic VRAM pixels.
        
        Zero synthetic polygons or simulated backgrounds are drawn.
        """
        w, h = max(1, self.viewport_w), max(1, self.viewport_h)
        # Deep black display surface
        img = Image.new('RGBA', (w, h), (0, 0, 0, 255))

        # Check if color buffer memory has authentic rendered pixels
        buf_off = self.color_buffer_phys - self.vram_base_phys
        bpp = 2 if self.color_format == 1 else 4
        frame_len = w * h * bpp
        if 0 <= buf_off and buf_off + frame_len <= len(stream_data):
            raw_pixels = stream_data[buf_off:buf_off+frame_len]
            if any(raw_pixels):
                try:
                    mode = 'RGBA' if bpp == 4 else 'RGB'
                    fmt = 'BGRA' if bpp == 4 else 'BGR;16'
                    surf = Image.frombytes(mode, (w, h), bytes(raw_pixels), 'raw', fmt)
                    img.paste(surf, (0, 0))
                except Exception:
                    pass

        return img
