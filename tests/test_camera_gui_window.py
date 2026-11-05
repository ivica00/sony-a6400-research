import unittest
from pathlib import Path
from PIL import Image

from tools.research.camera_gui_window import CameraGuiWindow


class TestCameraGuiWindow(unittest.TestCase):
    def test_compose_lcd_frame_dimensions(self):
        # Test without checkpoint (default blank VRAM)
        dummy_path = "non_existent.ckpt"
        win = CameraGuiWindow(dummy_path, scale=1.0)
        img = win.compose_lcd_frame()
        self.assertIsInstance(img, Image.Image)
        self.assertEqual(img.size, (960, 540))
        self.assertEqual(img.mode, "RGBA")
        win.root.destroy()


if __name__ == '__main__':
    unittest.main()
