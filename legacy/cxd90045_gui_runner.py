import os
import sys
import struct
import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk, ImageDraw, ImageFont

from project_paths import PROJECT_ROOT as _PROJECT_ROOT, REFERENCE_ASSETS, legacy_output
PROJECT_ROOT = str(_PROJECT_ROOT)
EXTRACTED_DIR = os.path.join(PROJECT_ROOT, "firmware", "extracted_a6400")
SHARE_APP = os.path.join(
    EXTRACTED_DIR, "firmware.tar_unpacked", "0700_part_image", "dev", "nflasha15_unpacked", "share", "app"
)
LIB_DIR = os.path.join(
    EXTRACTED_DIR, "firmware.tar_unpacked", "0700_part_image", "dev", "nflasha15_unpacked", "lib"
)

from legacy.cxd90045_hle_emulator import (
    CXD90045_HLE_Emulator, FRAMEBUFFER, FB_SIZE, LCD_WIDTH, LCD_HEIGHT,
    KEY_TACT_MENU, KEY_TACT_DISP, KEY_TACT_FN, KEY_TACT_PLAY,
    KEY_TACT_UP, KEY_TACT_DOWN, KEY_TACT_LEFT, KEY_TACT_RIGHT, KEY_TACT_ENTER,
    KEY_TACT_CUSTOM, KEY_REMOTE_S1, KEY_REMOTE_S2,
    KEY_OTHER_WHEEL_LEFT, KEY_OTHER_WHEEL_RIGHT
)

def load_cxd_palette():
    palette_path = os.path.join(SHARE_APP, "color_cmn.uxc")
    colors = {
        0x00: "#000000",
        0x01: "#DDDDDD",
        0x02: "#1A1A1A",
        0x07: "#DD0000",
        0x08: "#00DD00",
        0x09: "#0088DD",
        0x10: "#FF6600",
        0x13: "#DD5500",
        0x21: "#FFFFFF",
    }
    if os.path.exists(palette_path):
        try:
            with open(palette_path, 'rb') as f:
                data = f.read()
            for i in range(0x58, len(data) - 8, 8):
                cid = data[i]
                tag = data[i+1:i+4]
                if tag == b'\x40\x09\x3a':
                    r, g, b, a = data[i+4:i+8]
                    colors[cid] = f"#{r:02x}{g:02x}{b:02x}"
        except Exception:
            pass
    return colors

class SonyA6400EmulatorGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Sony a6400 (CXD90045) HLE Firmware & Hardware Input Emulator")
        self.root.geometry("1220x790")
        self.root.configure(bg="#181818")

        self.palette = load_cxd_palette()
        self.accent_color = self.palette.get(0x10, "#FF6600")

        # Camera LCD Dimensions
        self.lcd_w = LCD_WIDTH   # 960
        self.lcd_h = LCD_HEIGHT  # 540

        # Initialize ARM HLE Emulator & Hardware Components
        self.emu = None
        self.init_emulator()

        self.build_ui()
        self.bind_keyboard_controls()
        self.refresh_display()

    def init_emulator(self):
        try:
            print("[*] Inicijalizacija Unicorn CXD90045 ARMv7 HLE jezgra...")
            self.emu = CXD90045_HLE_Emulator()
            libobj_path = os.path.join(LIB_DIR, "libObj.so")
            vu2_path = os.path.join(LIB_DIR, "viewUnified2.so")
            
            if os.path.exists(libobj_path) and os.path.exists(vu2_path):
                self.emu.load_elf_module(libobj_path, base_addr=0x30000000)
                self.emu.load_elf_module(vu2_path, base_addr=0x32000000)
                self.emu.setup_sony_subsystems()
                self.emu.instantiate_all_screens()
                print("[+] Svi Sony ekrani i hardware input pipeline uspesno povezani!")
        except Exception as e:
            print(f"[-] Greska pri ucitavanju HLE emulatora: {e}")

    def bind_keyboard_controls(self):
        """Maps physical PC keyboard and mouse wheel to Sony hardware key codes"""
        self.root.bind("<Key-m>", lambda e: self.send_key(KEY_TACT_MENU))
        self.root.bind("<Key-M>", lambda e: self.send_key(KEY_TACT_MENU))
        self.root.bind("<Key-d>", lambda e: self.send_key(KEY_TACT_DISP))
        self.root.bind("<Key-D>", lambda e: self.send_key(KEY_TACT_DISP))
        self.root.bind("<Key-f>", lambda e: self.send_key(KEY_TACT_FN))
        self.root.bind("<Key-F>", lambda e: self.send_key(KEY_TACT_FN))
        self.root.bind("<Key-p>", lambda e: self.send_key(KEY_TACT_PLAY))
        self.root.bind("<Key-P>", lambda e: self.send_key(KEY_TACT_PLAY))
        self.root.bind("<Key-c>", lambda e: self.send_key(KEY_TACT_CUSTOM))
        self.root.bind("<Key-C>", lambda e: self.send_key(KEY_TACT_CUSTOM))
        self.root.bind("<space>", lambda e: self.send_key(KEY_REMOTE_S1))
        self.root.bind("<Key-s>", lambda e: self.send_key(KEY_REMOTE_S2))
        self.root.bind("<Key-S>", lambda e: self.send_key(KEY_REMOTE_S2))
        
        # D-Pad
        self.root.bind("<Up>", lambda e: self.send_key(KEY_TACT_UP))
        self.root.bind("<Down>", lambda e: self.send_key(KEY_TACT_DOWN))
        self.root.bind("<Left>", lambda e: self.send_key(KEY_TACT_LEFT))
        self.root.bind("<Right>", lambda e: self.send_key(KEY_TACT_RIGHT))
        self.root.bind("<Return>", lambda e: self.send_key(KEY_TACT_ENTER))

        # Mouse Wheel (Rotary Dial)
        self.root.bind("<MouseWheel>", self.on_mouse_wheel)

    def on_mouse_wheel(self, event):
        if event.delta > 0:
            self.send_key(KEY_OTHER_WHEEL_RIGHT) # CW
        else:
            self.send_key(KEY_OTHER_WHEEL_LEFT)  # CCW

    def send_key(self, key_code):
        if self.emu:
            self.emu.send_hardware_key(key_code)
            self.refresh_display()

    def build_ui(self):
        # Top Header Bar
        header = tk.Frame(self.root, bg="#222222", height=45)
        header.pack(fill=tk.X, side=tk.TOP)
        
        lbl_title = tk.Label(
            header, text="SONY α6400 (ILCE-6400) HARDWARE INPUT & FIRMWARE EMULATOR",
            font=("Arial", 12, "bold"), fg="#FF6600", bg="#222222"
        )
        lbl_title.pack(side=tk.LEFT, padx=15, pady=8)

        self.lbl_status = tk.Label(
            header, text="SCREEN: LIVE_VIEW | ARMv7 Cortex-A9 | Framebuffer: 0x60000000",
            font=("Consolas", 10), fg="#00E5FF", bg="#222222"
        )
        self.lbl_status.pack(side=tk.RIGHT, padx=15, pady=8)

        # Main Layout: Left = LCD Display, Right = Physical Buttons
        main_frame = tk.Frame(self.root, bg="#181818")
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # LCD Display Frame
        lcd_container = tk.Frame(main_frame, bg="#0a0a0a", bd=3, relief=tk.SOLID)
        lcd_container.pack(side=tk.LEFT, padx=10, pady=5)

        self.canvas = tk.Canvas(
            lcd_container, width=self.lcd_w, height=self.lcd_h,
            bg="#000000", highlightthickness=0
        )
        self.canvas.pack()

        # Camera Controls Panel (Right Side)
        ctrl_panel = tk.Frame(main_frame, bg="#202020", width=210, bd=1, relief=tk.GROOVE)
        ctrl_panel.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=5, pady=5)

        lbl_ctrl = tk.Label(ctrl_panel, text="PHYSICAL CAMERA CONTROLS", font=("Arial", 10, "bold"), fg="#DDDDDD", bg="#202020")
        lbl_ctrl.pack(pady=4)

        # Dual Shutter Buttons (S1 AF Lock & S2 Capture)
        shutter_box = tk.LabelFrame(ctrl_panel, text="SHUTTER BUTTON", font=("Arial", 8, "bold"), fg="#FF3333", bg="#202020")
        shutter_box.pack(fill=tk.X, padx=10, pady=4)
        
        s_row = tk.Frame(shutter_box, bg="#202020")
        s_row.pack(fill=tk.X, pady=2, padx=2)

        btn_s1 = tk.Button(
            s_row, text="AF LOCK (S1)\n[Space]",
            font=("Arial", 8, "bold"), bg="#333333", fg="#00FF66",
            activebackground="#00DD55", width=11, command=lambda: self.send_key(KEY_REMOTE_S1)
        )
        btn_s1.pack(side=tk.LEFT, padx=2)

        btn_s2 = tk.Button(
            s_row, text="CAPTURE (S2)\n[Key 'S']",
            font=("Arial", 8, "bold"), bg="#B22222", fg="#FFFFFF",
            activebackground="#FF3333", width=11, command=lambda: self.send_key(KEY_REMOTE_S2)
        )
        btn_s2.pack(side=tk.RIGHT, padx=2)

        # Direct Screen Buttons (MENU, DISP, Fn, PLAY)
        btn_grid = tk.LabelFrame(ctrl_panel, text="MAIN BUTTONS", font=("Arial", 8, "bold"), fg="#00E5FF", bg="#202020")
        btn_grid.pack(fill=tk.X, padx=10, pady=4)

        r1 = tk.Frame(btn_grid, bg="#202020")
        r1.pack(fill=tk.X, pady=2)
        btn_menu = tk.Button(r1, text="MENU (M)", font=("Arial", 8, "bold"), bg="#333333", fg="#FFFFFF", command=lambda: self.send_key(KEY_TACT_MENU), width=10)
        btn_menu.pack(side=tk.LEFT, padx=2)
        btn_fn = tk.Button(r1, text="Fn (F)", font=("Arial", 8, "bold"), bg="#333333", fg="#FFFFFF", command=lambda: self.send_key(KEY_TACT_FN), width=10)
        btn_fn.pack(side=tk.RIGHT, padx=2)

        r2 = tk.Frame(btn_grid, bg="#202020")
        r2.pack(fill=tk.X, pady=2)
        btn_disp = tk.Button(r2, text="DISP (D)", font=("Arial", 8, "bold"), bg="#333333", fg="#FFFFFF", command=lambda: self.send_key(KEY_TACT_DISP), width=10)
        btn_disp.pack(side=tk.LEFT, padx=2)
        btn_play = tk.Button(r2, text="▶ PLAY (P)", font=("Arial", 8, "bold"), bg="#333333", fg="#FFFFFF", command=lambda: self.send_key(KEY_TACT_PLAY), width=10)
        btn_play.pack(side=tk.RIGHT, padx=2)

        # D-Pad (Navigation)
        dpad_frame = tk.LabelFrame(ctrl_panel, text="D-PAD (Wheel / Navigation)", font=("Arial", 8, "bold"), fg="#888888", bg="#202020")
        dpad_frame.pack(fill=tk.X, padx=10, pady=6)

        btn_up = tk.Button(dpad_frame, text="▲ UP", font=("Arial", 8, "bold"), bg="#2c2c2c", fg="#DDDDDD", command=lambda: self.send_key(KEY_TACT_UP))
        btn_up.pack(pady=2, fill=tk.X, padx=4)

        dpad_mid = tk.Frame(dpad_frame, bg="#202020")
        dpad_mid.pack(pady=2)
        btn_left = tk.Button(dpad_mid, text="◄ LEFT", font=("Arial", 8), bg="#2c2c2c", fg="#DDDDDD", command=lambda: self.send_key(KEY_TACT_LEFT), width=7)
        btn_left.pack(side=tk.LEFT, padx=2)
        btn_center = tk.Button(dpad_mid, text="OK", font=("Arial", 8, "bold"), bg="#FF6600", fg="#000000", command=lambda: self.send_key(KEY_TACT_ENTER), width=5)
        btn_center.pack(side=tk.LEFT, padx=2)
        btn_right = tk.Button(dpad_mid, text="RIGHT ►", font=("Arial", 8), bg="#2c2c2c", fg="#DDDDDD", command=lambda: self.send_key(KEY_TACT_RIGHT), width=7)
        btn_right.pack(side=tk.LEFT, padx=2)

        btn_down = tk.Button(dpad_frame, text="▼ DOWN (ISO)", font=("Arial", 8), bg="#2c2c2c", fg="#DDDDDD", command=lambda: self.send_key(KEY_TACT_DOWN))
        btn_down.pack(pady=2, fill=tk.X, padx=4)

        # Rotary Wheel (Dial)
        wheel_frame = tk.LabelFrame(ctrl_panel, text="CONTROL WHEEL (Wheel Dial)", font=("Arial", 8, "bold"), fg="#FFD700", bg="#202020")
        wheel_frame.pack(fill=tk.X, padx=10, pady=4)
        r_wheel = tk.Frame(wheel_frame, bg="#202020")
        r_wheel.pack(fill=tk.X, pady=2)
        btn_ccw = tk.Button(r_wheel, text="↺ CCW (-)", font=("Arial", 8), bg="#333333", fg="#DDDDDD", command=lambda: self.send_key(KEY_OTHER_WHEEL_LEFT), width=10)
        btn_ccw.pack(side=tk.LEFT, padx=2)
        btn_cw = tk.Button(r_wheel, text="CW (+) ↻", font=("Arial", 8), bg="#333333", fg="#DDDDDD", command=lambda: self.send_key(KEY_OTHER_WHEEL_RIGHT), width=10)
        btn_cw.pack(side=tk.RIGHT, padx=2)

        # Custom Buttons C1
        btn_c1 = tk.Button(ctrl_panel, text="C1 (Fokus Mod: AF-C/AF-S/MF)", font=("Arial", 8, "bold"), bg="#333333", fg="#00FF66", command=lambda: self.send_key(KEY_TACT_CUSTOM))
        btn_c1.pack(fill=tk.X, padx=10, pady=4)

        # Firmware Theme Customizer (Modifikacija Boje)
        theme_frame = tk.LabelFrame(ctrl_panel, text="IZMENA BOJE TEME (MOD)", font=("Arial", 8, "bold"), fg="#FF6600", bg="#202020")
        theme_frame.pack(fill=tk.X, padx=10, pady=4)

        theme_colors = [
            ("Sony Orange (Fabricki)", "#FF6600"),
            ("Cyber Cyan", "#00E5FF"),
            ("Matrix Green", "#00FF66"),
            ("Crimson Red", "#FF1744"),
            ("Deep Gold", "#FFD700")
        ]
        for name, col in theme_colors:
            btn_t = tk.Button(
                theme_frame, text=name, font=("Arial", 8), bg=col, fg="#000000" if col != "#FF1744" else "#FFFFFF",
                command=lambda c=col: self.change_accent_color(c)
            )
            btn_t.pack(fill=tk.X, pady=1, padx=4)

    def change_accent_color(self, new_color):
        print(f"[*] Primena izmene boje u firmware memoriji: {new_color}")
        self.accent_color = new_color
        if self.emu:
            self.emu.camera_state["accent_color"] = new_color
            self.emu.update_param_val_nodes()
        self.refresh_display()

    def refresh_display(self):
        if not self.emu: return
        img = self.emu.render_active_screen()
        self.tk_img = ImageTk.PhotoImage(img)
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.tk_img)
        
        sub_info = ""
        if self.emu.active_screen == "MENU" and self.emu.menu_sub_active:
            cur_item = self.emu.menu_options_map.get((self.emu.menu_tab, self.emu.menu_item), {})
            sub_info = f" [SUBMENU: {cur_item.get('name', '')}]"
            
        af_txt = "LOCK" if self.emu.af_locked else "UNLOCKED"
        iso_txt = "AUTO" if self.emu.camera_state["iso_mode"] == 0 else str(self.emu.camera_state["iso_val"])
        self.lbl_status.configure(
            text=f"SCREEN: {self.emu.active_screen}{sub_info} | {self.emu.camera_state['quality']} ({self.emu.camera_state['aspect_ratio']}) | AF: {self.emu.camera_state['focus_mode']} [{af_txt}] | 1/{self.emu.camera_state['shutter_den']}s F{self.emu.camera_state['aperture_val']/10:.1f} ISO {iso_txt} | SD: {self.emu.camera_state['card_remaining']}"
        )

def main():
    root = tk.Tk()
    app = SonyA6400EmulatorGUI(root)
    root.mainloop()

if __name__ == '__main__':
    main()
