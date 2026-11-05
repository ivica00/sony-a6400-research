import struct
import unittest
from PIL import Image

from src.a6400.execution.dmp_rasterizer import (
    DmpPicaRasterizer, REG_VIEWPORT_SIZE, REG_COLOR_BUFFER_0, REG_COLOR_FORMAT_0
)


class TestDmpRasterizer(unittest.TestCase):
    def setUp(self):
        self.rasterizer = DmpPicaRasterizer(vram_base_phys=0x202e0000)

    def test_parse_viewport_and_color_buffer(self):
        # Pack viewport 336 x 448 (0x01c00150)
        hdr_vp = REG_VIEWPORT_SIZE << 16
        param_vp = 0x01c00150
        self.rasterizer.parse_packet(hdr_vp, param_vp)
        self.assertEqual(self.rasterizer.viewport_w, 336)
        self.assertEqual(self.rasterizer.viewport_h, 448)

        # Pack color buffer base 0x202ee100
        hdr_cb = REG_COLOR_BUFFER_0 << 16
        param_cb = 0x202ee100
        self.rasterizer.parse_packet(hdr_cb, param_cb)
        self.assertEqual(self.rasterizer.color_buffer_phys, 0x202ee100)

    def test_extract_vertices(self):
        # 4 vertices (16 floats)
        floats = [
            0.0, 1.0, -1.0, 1.0,
            0.0, 0.0, -1.0, -1.0,
            1.0, 1.0, 1.0, 1.0,
            1.0, 0.0, 1.0, -1.0,
        ]
        raw = struct.pack('<16f', *floats)
        self.rasterizer.extract_vertices(raw)
        self.assertEqual(len(self.rasterizer.vertices), 4)
        self.assertEqual(self.rasterizer.vertices[0], (0.0, 1.0, -1.0, 1.0))

    def test_render_surface_produces_image(self):
        buf = bytearray(1024 * 1024)
        img = self.rasterizer.render_surface(buf)
        self.assertIsInstance(img, Image.Image)
        self.assertEqual(img.size, (self.rasterizer.viewport_w, self.rasterizer.viewport_h))


if __name__ == '__main__':
    unittest.main()
