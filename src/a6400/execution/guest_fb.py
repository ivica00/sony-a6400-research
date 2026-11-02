"""Experimental framebuffer model using standard Linux ioctl layouts.

Default geometry, backing address, identity and timing are not established camera
runtime state. A successful model transaction does not validate Sony fb0 hardware.
"""

from __future__ import annotations

import struct
from typing import Callable, Dict, List, Optional
from PIL import Image

# Linux framebuffer ioctl command codes (from <linux/fb.h>)
FBIOGET_VSCREENINFO = 0x4600
FBIOPUT_VSCREENINFO = 0x4601
FBIOGET_FSCREENINFO = 0x4602
FBIOPAN_DISPLAY     = 0x4606
FBIO_WAITFORVSYNC   = 0x40044620

# Linux framebuffer constants
FB_TYPE_PACKED_PIXELS = 0
FB_VISUAL_TRUECOLOR   = 2

# Sony ILCE-6400 LCD specifications (Quarter HD 16:9 widescreen display)
DEFAULT_WIDTH        = 960
DEFAULT_HEIGHT       = 540
DEFAULT_VIRT_HEIGHT  = 1080  # Double-buffered display
DEFAULT_BPP          = 32    # 32 bits per pixel (ARGB8888)
DEFAULT_FB_PHYS_BASE = 0x60000000
DEFAULT_FB_POOL_SIZE = 16 * 1024 * 1024  # 16 MiB VRAM buffer pool

# Binary structure formats for ARM EABI (32-bit Linux)
FMT_FB_FIX = '<16sIIIIIHHHHIIIH2H2x'   # 64 bytes (padded)
FMT_FB_VAR = '<IIIIIIII12I5I7I4I4I'    # 160 bytes


class GuestFramebuffer:
    """Linux framebuffer (/dev/fb0) character device implementation for guest execution."""

    def __init__(self,
                 width: int = DEFAULT_WIDTH,
                 height: int = DEFAULT_HEIGHT,
                 virtual_height: int = DEFAULT_VIRT_HEIGHT,
                 bpp: int = DEFAULT_BPP,
                 phys_base: int = DEFAULT_FB_PHYS_BASE,
                 pool_size: int = DEFAULT_FB_POOL_SIZE,
                 driver_id: bytes = b'sugilite'):
        self.width = width
        self.height = height
        self.virtual_height = virtual_height
        self.bpp = bpp
        self.phys_base = phys_base
        self.pool_size = pool_size
        self.driver_id = driver_id[:15] + b'\x00'

        self.bytes_per_pixel = bpp // 8
        self.line_length = self.width * self.bytes_per_pixel
        self.screen_size = self.line_length * self.virtual_height

        self.xoffset = 0
        self.yoffset = 0

        # Memory mapping state
        self.vram_base: Optional[int] = None
        self.vram_length: int = 0
        self.transactions: List[Dict[str, object]] = []

    def handle_ioctl(self,
                     memory_reader: Callable[[int, int], bytes],
                     memory_writer: Callable[[int, bytes], None],
                     cmd: int,
                     arg_ptr: int) -> Optional[int]:
        """Dispatches framebuffer ioctl commands."""
        if cmd == FBIOGET_FSCREENINFO:
            return self._handle_get_fscreeninfo(memory_writer, arg_ptr)
        if cmd == FBIOGET_VSCREENINFO:
            return self._handle_get_vscreeninfo(memory_writer, arg_ptr)
        if cmd == FBIOPUT_VSCREENINFO:
            return self._handle_put_vscreeninfo(memory_reader, memory_writer, arg_ptr)
        if cmd == FBIOPAN_DISPLAY:
            return self._handle_pan_display(memory_reader, arg_ptr)
        if cmd == FBIO_WAITFORVSYNC:
            self.transactions.append({'type': 'wait_vsync', 'returned': 0})
            return 0
        return None

    def _handle_get_fscreeninfo(self, memory_writer: Callable[[int, bytes], None], arg_ptr: int) -> int:
        packed = struct.pack(
            FMT_FB_FIX,
            self.driver_id,
            self.phys_base,
            self.screen_size,
            FB_TYPE_PACKED_PIXELS,
            0,
            FB_VISUAL_TRUECOLOR,
            1, 1, 0,
            self.line_length,
            0, 0,
            0,
            0, 0, 0
        )
        memory_writer(arg_ptr, packed)
        self.transactions.append({
            'type': 'get_fscreeninfo',
            'driver_id': self.driver_id.decode('latin1', 'replace').rstrip('\x00'),
            'smem_len': self.screen_size,
            'line_length': self.line_length,
            'returned': 0
        })
        return 0

    def _handle_get_vscreeninfo(self, memory_writer: Callable[[int, bytes], None], arg_ptr: int) -> int:
        packed = struct.pack(
            FMT_FB_VAR,
            self.width, self.height,
            self.width, self.virtual_height,
            self.xoffset, self.yoffset,
            self.bpp, 0,
            16, 8, 0,    # Red bitfield (offset 16, length 8)
            8, 8, 0,     # Green bitfield (offset 8, length 8)
            0, 8, 0,     # Blue bitfield (offset 0, length 8)
            24, 8, 0,    # Transp bitfield (offset 24, length 8)
            0, 0, 0, 0, 0,
            0, 0, 0, 0, 0, 0, 0,
            0, 0, 0, 0,
            0, 0, 0, 0
        )
        memory_writer(arg_ptr, packed)
        self.transactions.append({
            'type': 'get_vscreeninfo',
            'width': self.width,
            'height': self.height,
            'bpp': self.bpp,
            'xoffset': self.xoffset,
            'yoffset': self.yoffset,
            'returned': 0
        })
        return 0

    def _handle_put_vscreeninfo(self,
                                memory_reader: Callable[[int, int], bytes],
                                memory_writer: Callable[[int, bytes], None],
                                arg_ptr: int) -> int:
        raw = memory_reader(arg_ptr, struct.calcsize(FMT_FB_VAR))
        fields = struct.unpack(FMT_FB_VAR, raw)
        new_xres, new_yres, new_vxres, new_vyres, new_xoff, new_yoff = fields[:6]
        new_bpp = fields[6]

        self.xoffset = new_xoff
        self.yoffset = new_yoff
        self.transactions.append({
            'type': 'put_vscreeninfo',
            'xres': new_xres,
            'yres': new_yres,
            'xoffset': new_xoff,
            'yoffset': new_yoff,
            'bpp': new_bpp,
            'returned': 0
        })
        # Reflect back the verified supported geometry
        return self._handle_get_vscreeninfo(memory_writer, arg_ptr)

    def _handle_pan_display(self, memory_reader: Callable[[int, int], bytes], arg_ptr: int) -> int:
        raw = memory_reader(arg_ptr, 24)
        _, _, _, _, xoff, yoff = struct.unpack('<IIIIII', raw)
        self.xoffset = xoff
        self.yoffset = yoff
        self.transactions.append({
            'type': 'pan_display',
            'xoffset': xoff,
            'yoffset': yoff,
            'returned': 0
        })
        return 0

    def handle_fstat64(self, memory_writer: Callable[[int, bytes], None], buf_ptr: int) -> int:
        """Returns standard Linux character device stat64 for major 29, minor 0 (/dev/fb0)."""
        # dev: major 29, minor 0 -> (29 << 8) | 0 = 0x1d00
        st_dev = 0x1d00
        st_rdev = 0x1d00
        st_ino = 1000
        st_mode = 0o20660  # S_IFCHR | 0660

        stat_bytes = bytearray(104)
        struct.pack_into('<Q', stat_bytes, 0, st_dev)
        struct.pack_into('<I', stat_bytes, 12, 0)
        struct.pack_into('<I', stat_bytes, 16, st_ino)
        struct.pack_into('<I', stat_bytes, 20, st_mode)
        struct.pack_into('<I', stat_bytes, 24, 1)          # nlink = 1
        struct.pack_into('<I', stat_bytes, 28, 0)          # uid = 0
        struct.pack_into('<I', stat_bytes, 32, 0)          # gid = 0
        struct.pack_into('<Q', stat_bytes, 36, st_rdev)
        struct.pack_into('<q', stat_bytes, 48, 0)          # size = 0
        struct.pack_into('<I', stat_bytes, 56, 4096)       # blksize = 4096
        struct.pack_into('<q', stat_bytes, 64, 0)          # blocks = 0
        memory_writer(buf_ptr, bytes(stat_bytes))
        return 0

    def extract_frame_bytes(self, memory_reader: Callable[[int, int], bytes]) -> Optional[bytes]:
        """Extracts the active visible frame buffer bytes from guest VRAM memory."""
        if self.vram_base is None:
            return None
        active_offset = (self.yoffset * self.line_length) + (self.xoffset * self.bytes_per_pixel)
        frame_len = self.width * self.height * self.bytes_per_pixel
        return memory_reader(self.vram_base + active_offset, frame_len)

    def extract_image(self, memory_reader: Callable[[int, int], bytes]) -> Optional[Image.Image]:
        """Converts the active visible guest VRAM into a PIL Image."""
        raw = self.extract_frame_bytes(memory_reader)
        if raw is None:
            return None
        if self.bpp == 32:
            return Image.frombytes('RGBA', (self.width, self.height), raw, 'raw', 'BGRA')
        if self.bpp == 16:
            return Image.frombytes('RGB', (self.width, self.height), raw, 'raw', 'BGR;16')
        return None
