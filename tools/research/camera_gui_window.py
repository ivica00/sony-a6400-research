"""Interactive Sony ILCE-6400 Virtual LCD Display & GUI Window.

Visualizes the camera's active framebuffer surfaces, DMP GPU rendering,
and live UI state in an authentic 16:9 LCD window using Tkinter and Pillow.
"""

import argparse
import pickle
import sys
import zlib
from pathlib import Path
import tkinter as tk
from PIL import Image, ImageTk, ImageDraw, ImageFont

from src.a6400.execution.dmp_rasterizer import DmpPicaRasterizer


class CameraGuiWindow:
    """Sony ILCE-6400 Virtual LCD Display Window."""

    def __init__(self, checkpoint_path: str, scale: float = 1.0):
        self.checkpoint_path = Path(checkpoint_path)
        self.scale = scale
        self.rasterizer = DmpPicaRasterizer(vram_base_phys=0x202e0000)

        # Standard Sony ILCE-6400 LCD specifications: 960 x 540 (16:9 qHD)
        self.lcd_w = 960
        self.lcd_h = 540
        self.win_w = int(self.lcd_w * scale)
        self.win_h = int(self.lcd_h * scale)

        self.root = tk.Tk()
        self.root.title("Sony ILCE-6400 Virtual LCD Display - Antigravity")
        self.root.geometry(f"{self.win_w}x{self.win_h + 40}")
        self.root.resizable(False, False)
        self.root.configure(bg="#121214")

        # Canvas for LCD display
        self.canvas = tk.Canvas(self.root, width=self.win_w, height=self.win_h,
                                bg="#0a0a0c", highlightthickness=0)
        self.canvas.pack(side=tk.TOP)

        # Bottom status bar
        self.status_bar = tk.Label(
            self.root,
            text=f"Checkpoint: {self.checkpoint_path.name} | Res: {self.lcd_w}x{self.lcd_h} | Status: Ready",
            bg="#1c1c20", fg="#a0a0b0", font=("Consolas", 9), anchor=tk.W, padx=10
        )
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X, ipady=4)

        # Static checkpoint diagnostic only.  It intentionally exposes no
        # host-written camera navigation; live guest frames are presented by
        # tools.research.emulator_gui.
        self.root.bind("s", lambda e: self.save_screenshot())

        self.stream_data: Optional[bytes] = None
        self.load_checkpoint()
        self.update_display()

    def load_checkpoint(self):
        if not self.checkpoint_path.exists():
            print(f"Checkpoint not found: {self.checkpoint_path}")
            return

        with open(self.checkpoint_path, 'rb') as f:
            payload = pickle.load(f)

        for r in payload['regions']:
            if r['begin'] == 0x53f50000 or (r['size'] == 32 * 1024 * 1024 and 'stream' in str(r)):
                self.stream_data = zlib.decompress(r['data'])
                print(f"Loaded {len(self.stream_data) // (1024*1024)} MB stream VRAM from checkpoint.")
                break

    def compose_lcd_frame(self) -> Image.Image:
        """Composes the full 960x540 camera display strictly from authentic rendered surfaces.
        
        Zero synthetic OSD overlays or host-simulated camera graphics are applied.
        Only authentic DMP PICA200 rasterized framebuffers or firmware display buffers are shown.
        """
        # Base LCD screen in deep camera black (uninitialized / standby LCD state)
        frame = Image.new("RGBA", (self.lcd_w, self.lcd_h), (0, 0, 0, 255))

        # 1. Render active authentic DMP GLES surface if available
        if self.stream_data:
            self.rasterizer.parse_stream(self.stream_data)
            surf = self.rasterizer.render_surface(bytearray(self.stream_data))
            if surf.width > 0 and surf.height > 0:
                sx = (self.lcd_w - surf.width) // 2
                sy = (self.lcd_h - surf.height) // 2
                frame.paste(surf, (sx, sy), surf)

        return frame

    def update_display(self):
        lcd_image = self.compose_lcd_frame()
        if self.scale != 1.0:
            lcd_image = lcd_image.resize((self.win_w, self.win_h), Image.Resampling.BILINEAR)

        self.tk_image = ImageTk.PhotoImage(lcd_image)
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.tk_image)

    def save_screenshot(self):
        out_dir = Path("artifacts/gui")
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / "camera_virtual_lcd.png"
        img = self.compose_lcd_frame()
        img.save(out_file)
        print(f"[GUI] Saved screenshot to: {out_file}")
        self.status_bar.config(text=f"Saved screenshot: {out_file.name}")


def main():
    parser = argparse.ArgumentParser(description="Sony ILCE-6400 Virtual LCD Display")
    parser.add_argument("--checkpoint", default="artifacts/checkpoints/boot-110m.ckpt",
                        help="Path to emulator snapshot checkpoint")
    parser.add_argument("--scale", type=float, default=1.0, help="Display scaling factor")
    parser.add_argument("--headless", action="store_true",
                        help="Export screenshot without opening interactive window")
    args = parser.parse_args()

    if args.headless:
        win = CameraGuiWindow(args.checkpoint, scale=args.scale)
        win.save_screenshot()
        print("Headless render complete.")
        return

    win = CameraGuiWindow(args.checkpoint, scale=args.scale)
    win.root.mainloop()


if __name__ == "__main__":
    main()
