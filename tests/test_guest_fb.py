"""Unit tests for GuestFramebuffer Linux character device contract."""

import struct
import unittest
from PIL import Image

from src.a6400.execution.guest_fb import (
    GuestFramebuffer,
    FBIOGET_VSCREENINFO,
    FBIOPUT_VSCREENINFO,
    FBIOGET_FSCREENINFO,
    FBIOPAN_DISPLAY,
    FBIO_WAITFORVSYNC,
    FB_TYPE_PACKED_PIXELS,
    FB_VISUAL_TRUECOLOR,
    DEFAULT_WIDTH,
    DEFAULT_HEIGHT,
    DEFAULT_VIRT_HEIGHT,
    DEFAULT_BPP,
    DEFAULT_FB_PHYS_BASE,
    FMT_FB_FIX,
    FMT_FB_VAR,
)


class GuestFramebufferTests(unittest.TestCase):
    def setUp(self):
        self.fb = GuestFramebuffer()
        self.memory = {}

    def _memory_reader(self, addr: int, size: int) -> bytes:
        data = bytearray()
        for i in range(size):
            data.append(self.memory.get(addr + i, 0))
        return bytes(data)

    def _memory_writer(self, addr: int, data: bytes) -> None:
        for i, b in enumerate(data):
            self.memory[addr + i] = b

    def test_fb_fix_screeninfo_layout_and_fields(self):
        arg_ptr = 0x1000
        ret = self.fb.handle_ioctl(self._memory_reader, self._memory_writer, FBIOGET_FSCREENINFO, arg_ptr)
        self.assertEqual(ret, 0)

        raw = self._memory_reader(arg_ptr, 64)
        fields = struct.unpack(FMT_FB_FIX, raw)
        driver_id = fields[0].split(b'\x00')[0]
        smem_start = fields[1]
        smem_len = fields[2]
        fb_type = fields[3]
        visual = fields[5]
        line_length = fields[9]

        self.assertEqual(driver_id, b'sugilite')
        self.assertEqual(smem_start, DEFAULT_FB_PHYS_BASE)
        self.assertEqual(smem_len, DEFAULT_WIDTH * DEFAULT_VIRT_HEIGHT * 4)
        self.assertEqual(fb_type, FB_TYPE_PACKED_PIXELS)
        self.assertEqual(visual, FB_VISUAL_TRUECOLOR)
        self.assertEqual(line_length, DEFAULT_WIDTH * 4)

    def test_fb_var_screeninfo_layout_and_fields(self):
        arg_ptr = 0x2000
        ret = self.fb.handle_ioctl(self._memory_reader, self._memory_writer, FBIOGET_VSCREENINFO, arg_ptr)
        self.assertEqual(ret, 0)

        raw = self._memory_reader(arg_ptr, 160)
        fields = struct.unpack(FMT_FB_VAR, raw)
        xres, yres, vxres, vyres, xoff, yoff, bpp = fields[:7]
        red_off, red_len = fields[8], fields[9]
        green_off, green_len = fields[11], fields[12]
        blue_off, blue_len = fields[14], fields[15]
        transp_off, transp_len = fields[17], fields[18]

        self.assertEqual(xres, 960)
        self.assertEqual(yres, 540)
        self.assertEqual(vxres, 960)
        self.assertEqual(vyres, 1080)
        self.assertEqual(xoff, 0)
        self.assertEqual(yoff, 0)
        self.assertEqual(bpp, 32)

        self.assertEqual(red_off, 16)
        self.assertEqual(red_len, 8)
        self.assertEqual(green_off, 8)
        self.assertEqual(green_len, 8)
        self.assertEqual(blue_off, 0)
        self.assertEqual(blue_len, 8)
        self.assertEqual(transp_off, 24)
        self.assertEqual(transp_len, 8)

    def test_fb_put_vscreeninfo_updates_offsets(self):
        arg_ptr = 0x3000
        # Write new var info requesting yoffset = 540 (second buffer page)
        new_var = struct.pack(
            FMT_FB_VAR,
            960, 540,
            960, 1080,
            0, 540,
            32, 0,
            16, 8, 0,
            8, 8, 0,
            0, 8, 0,
            24, 8, 0,
            0, 0, 0, 0, 0,
            0, 0, 0, 0, 0, 0, 0,
            0, 0, 0, 0,
            0, 0, 0, 0
        )
        self._memory_writer(arg_ptr, new_var)

        ret = self.fb.handle_ioctl(self._memory_reader, self._memory_writer, FBIOPUT_VSCREENINFO, arg_ptr)
        self.assertEqual(ret, 0)
        self.assertEqual(self.fb.yoffset, 540)

        # Confirm read back reflects yoffset = 540
        read_back = self._memory_reader(arg_ptr, 160)
        fields = struct.unpack(FMT_FB_VAR, read_back)
        self.assertEqual(fields[5], 540)

    def test_fb_pan_display(self):
        arg_ptr = 0x4000
        pan_var = struct.pack('<IIIIII', 960, 540, 960, 1080, 0, 540)
        self._memory_writer(arg_ptr, pan_var)

        ret = self.fb.handle_ioctl(self._memory_reader, self._memory_writer, FBIOPAN_DISPLAY, arg_ptr)
        self.assertEqual(ret, 0)
        self.assertEqual(self.fb.yoffset, 540)

    def test_fb_wait_vsync(self):
        ret = self.fb.handle_ioctl(self._memory_reader, self._memory_writer, FBIO_WAITFORVSYNC, 0)
        self.assertEqual(ret, 0)
        self.assertEqual(len(self.fb.transactions), 1)
        self.assertEqual(self.fb.transactions[0]['type'], 'wait_vsync')

    def test_fb_fstat64_contract(self):
        buf_ptr = 0x5000
        ret = self.fb.handle_fstat64(self._memory_writer, buf_ptr)
        self.assertEqual(ret, 0)

        raw = self._memory_reader(buf_ptr, 104)
        st_dev = struct.unpack_from('<Q', raw, 0)[0]
        st_rdev = struct.unpack_from('<Q', raw, 36)[0]
        st_mode = struct.unpack_from('<I', raw, 20)[0]

        # Major 29, minor 0 -> (29 << 8) | 0 = 0x1d00
        self.assertEqual(st_dev, 0x1d00)
        self.assertEqual(st_rdev, 0x1d00)
        # S_IFCHR (0o20000) | 0o660 = 0o20660
        self.assertEqual(st_mode, 0o20660)

    def test_fb_image_extraction(self):
        self.fb.vram_base = 0x60000000
        self.fb.vram_length = 960 * 540 * 4

        # Fill top-left 10x10 pixel area with solid red (BGRA: B=0, G=0, R=255, A=255)
        red_pixel = b'\x00\x00\xff\xff'
        for y in range(10):
            for x in range(10):
                offset = (y * 960 * 4) + (x * 4)
                self._memory_writer(0x60000000 + offset, red_pixel)

        image = self.fb.extract_image(self._memory_reader)
        self.assertIsNotNone(image)
        self.assertEqual(image.size, (960, 540))
        self.assertEqual(image.mode, 'RGBA')

        # Check top-left pixel is Red (255, 0, 0, 255)
        pixel = image.getpixel((0, 0))
        self.assertEqual(pixel, (255, 0, 0, 255))
        # Check background pixel is Black / transparent (0, 0, 0, 0)
        pixel_bg = image.getpixel((500, 300))
        self.assertEqual(pixel_bg, (0, 0, 0, 0))


if __name__ == '__main__':
    unittest.main()
