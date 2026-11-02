import os
import sys
import io
import wave
import struct
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from PIL import Image, ImageDraw, ImageFont, ImageTk

# Base paths
from project_paths import PROJECT_ROOT as _PROJECT_ROOT, REFERENCE_ASSETS, legacy_output
PROJECT_ROOT = str(_PROJECT_ROOT)
EXTRACTED_DIR = os.path.join(PROJECT_ROOT, "firmware", "extracted_a6400")
NFLASHA15_APP = os.path.join(
    EXTRACTED_DIR, "firmware.tar_unpacked", "0700_part_image", "dev", "nflasha15_unpacked", "share", "app"
)
SOUND_DIR = os.path.join(
    EXTRACTED_DIR, "firmware.tar_unpacked", "0700_part_image", "dev", "nflasha15_unpacked", "share", "avsystemsound"
)
FONT_PATH = os.path.join(NFLASHA15_APP, "Sony_DI_Icons.ttf")

try:
    import winsound
    HAS_WINSOUND = True
except ImportError:
    HAS_WINSOUND = False

class SonyCameraApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Sony a6400 Firmware GUI Simulator & Asset Explorer")
        self.geometry("1100x750")
        self.minsize(980, 680)
        self.configure(bg="#121212")

        # Camera state
        self.current_screen = "liveview"  # "liveview" or "menu"
        self.mode = "M"
        self.shutter = "1/250"
        self.aperture = "F2.8"
        self.iso = "400"
        self.ev = "+0.0"
        self.battery = 84
        self.focus_mode = "AF-C"
        self.focus_area = "Wide"
        self.profile = "PP10 (HLG)"
        self.wb = "AWB"
        self.menu_tab = 0 # 0..5
        self.menu_page = 1

        # Check font
        self.has_sony_font = os.path.exists(FONT_PATH)
        if self.has_sony_font:
            try:
                self.sony_icon_font = ImageFont.truetype(FONT_PATH, 22)
                self.sony_icon_large = ImageFont.truetype(FONT_PATH, 48)
            except Exception:
                self.sony_icon_font = None
                self.sony_icon_large = None
        else:
            self.sony_icon_font = None
            self.sony_icon_large = None

        self.setup_ui()

    def setup_ui(self):
        # Top banner
        header = tk.Frame(self, bg="#1e1e1e", height=45)
        header.pack(fill=tk.X)
        title_lbl = tk.Label(
            header,
            text="SONY \u03b16400 (ILCE-6400) FIRMWARE GUI SIMULATOR",
            font=("Segoe UI", 12, "bold"),
            fg="#ff7700",
            bg="#1e1e1e"
        )
        title_lbl.pack(side=tk.LEFT, padx=15, pady=8)
        
        status_lbl = tk.Label(
            header,
            text="Firmware: Ver 2.00 | SoC: CXD90045 | Model: 0x81030011",
            font=("Segoe UI", 9),
            fg="#999999",
            bg="#1e1e1e"
        )
        status_lbl.pack(side=tk.RIGHT, padx=15, pady=10)

        # Tabs notebook
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TNotebook", background="#121212", borderwidth=0)
        style.configure("TNotebook.Tab", background="#2a2a2a", foreground="#cccccc", padding=[15, 6], font=("Segoe UI", 9, "bold"))
        style.map("TNotebook.Tab", background=[("selected", "#ff7700")], foreground=[("selected", "#ffffff")])

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Tab 1: LCD Camera Simulator
        self.tab_lcd = tk.Frame(self.notebook, bg="#181818")
        self.notebook.add(self.tab_lcd, text="  LCD Ekran Kamere  ")
        self.build_lcd_tab()

        # Tab 2: Sony Icons Browser (1482 icons)
        self.tab_icons = tk.Frame(self.notebook, bg="#181818")
        self.notebook.add(self.tab_icons, text="  Pregleda\u010d Ikona (1,482)  ")
        self.build_icons_tab()

        # Tab 3: UXC Scene Explorer
        self.tab_uxc = tk.Frame(self.notebook, bg="#181818")
        self.notebook.add(self.tab_uxc, text="  UXC Ekrani (Layouts)  ")
        self.build_uxc_tab()

        # Tab 4: Audio Soundboard
        self.tab_sound = tk.Frame(self.notebook, bg="#181818")
        self.notebook.add(self.tab_sound, text="  Zvu\u010dni Efekti  ")
        self.build_sound_tab()

    # =========================================================================
    # TAB 1: LCD SCREEN SIMULATOR
    # =========================================================================
    def build_lcd_tab(self):
        container = tk.Frame(self.tab_lcd, bg="#181818")
        container.pack(fill=tk.BOTH, expand=True, padx=15, pady=15)

        # Left: 640x480 LCD Screen
        screen_frame = tk.Frame(container, bg="#000000", bd=3, relief=tk.SUNKEN)
        screen_frame.pack(side=tk.LEFT, padx=10, pady=10)

        self.lcd_canvas = tk.Canvas(screen_frame, width=640, height=480, bg="#000000", highlightthickness=0)
        self.lcd_canvas.pack()

        # Right: Hardware Controls & Controls Panel
        ctrl_frame = tk.Frame(container, bg="#222222", bd=2, relief=tk.GROOVE)
        ctrl_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=10, pady=10)

        ctrl_title = tk.Label(ctrl_frame, text="KONTROLE KAMERE", font=("Segoe UI", 10, "bold"), fg="#ff7700", bg="#222222")
        ctrl_title.pack(anchor=tk.W, padx=12, pady=10)

        # Buttons
        btn_box1 = tk.Frame(ctrl_frame, bg="#222222")
        btn_box1.pack(fill=tk.X, padx=12, pady=5)

        tk.Button(
            btn_box1, text="[ SHUTTER ]", font=("Segoe UI", 10, "bold"), bg="#d9534f", fg="#ffffff",
            activebackground="#c9302c", activeforeground="#ffffff", relief=tk.RAISED, cursor="hand2",
            command=self.on_shutter
        ).pack(fill=tk.X, pady=4)

        btn_box2 = tk.Frame(ctrl_frame, bg="#222222")
        btn_box2.pack(fill=tk.X, padx=12, pady=5)

        tk.Button(
            btn_box2, text="MENU", font=("Segoe UI", 9, "bold"), bg="#3a3a3a", fg="#ffffff", width=12,
            command=self.toggle_menu
        ).pack(side=tk.LEFT, padx=2)

        tk.Button(
            btn_box2, text="DISP", font=("Segoe UI", 9, "bold"), bg="#3a3a3a", fg="#ffffff", width=12,
            command=self.on_disp
        ).pack(side=tk.RIGHT, padx=2)

        btn_box3 = tk.Frame(ctrl_frame, bg="#222222")
        btn_box3.pack(fill=tk.X, padx=12, pady=5)

        tk.Button(
            btn_box3, text="Fn (Function)", font=("Segoe UI", 9, "bold"), bg="#3a3a3a", fg="#ffaa00", width=12,
            command=self.on_fn
        ).pack(side=tk.LEFT, padx=2)

        tk.Button(
            btn_box3, text="Eye-AF Track", font=("Segoe UI", 9, "bold"), bg="#3a3a3a", fg="#44ff44", width=12,
            command=self.on_focus
        ).pack(side=tk.RIGHT, padx=2)

        # Parameter Adjusters
        adj_frame = tk.LabelFrame(ctrl_frame, text=" Brza Pode\u0161avanja ", font=("Segoe UI", 9), fg="#cccccc", bg="#222222")
        adj_frame.pack(fill=tk.X, padx=12, pady=15)

        # Shutter
        shutter_row = tk.Frame(adj_frame, bg="#222222")
        shutter_row.pack(fill=tk.X, padx=8, pady=4)
        tk.Label(shutter_row, text="Shutter Speed:", font=("Segoe UI", 8), fg="#aaaaaa", bg="#222222", width=13, anchor=tk.W).pack(side=tk.LEFT)
        self.shutter_combo = ttk.Combobox(shutter_row, values=["1/4000", "1/2000", "1/1000", "1/500", "1/250", "1/125", "1/60", "1/30", "1/4", "1\""], width=10, state="readonly")
        self.shutter_combo.set(self.shutter)
        self.shutter_combo.bind("<<ComboboxSelected>>", lambda e: self.update_param('shutter', self.shutter_combo.get()))
        self.shutter_combo.pack(side=tk.RIGHT)

        # Aperture
        ap_row = tk.Frame(adj_frame, bg="#222222")
        ap_row.pack(fill=tk.X, padx=8, pady=4)
        tk.Label(ap_row, text="Aperture:", font=("Segoe UI", 8), fg="#aaaaaa", bg="#222222", width=13, anchor=tk.W).pack(side=tk.LEFT)
        self.ap_combo = ttk.Combobox(ap_row, values=["F1.4", "F1.8", "F2.8", "F4.0", "F5.6", "F8.0", "F11", "F16", "F22"], width=10, state="readonly")
        self.ap_combo.set(self.aperture)
        self.ap_combo.bind("<<ComboboxSelected>>", lambda e: self.update_param('aperture', self.ap_combo.get()))
        self.ap_combo.pack(side=tk.RIGHT)

        # ISO
        iso_row = tk.Frame(adj_frame, bg="#222222")
        iso_row.pack(fill=tk.X, padx=8, pady=4)
        tk.Label(iso_row, text="ISO Osetljivost:", font=("Segoe UI", 8), fg="#aaaaaa", bg="#222222", width=13, anchor=tk.W).pack(side=tk.LEFT)
        self.iso_combo = ttk.Combobox(iso_row, values=["AUTO", "100", "200", "400", "800", "1600", "3200", "6400", "12800", "25600", "32000"], width=10, state="readonly")
        self.iso_combo.set(self.iso)
        self.iso_combo.bind("<<ComboboxSelected>>", lambda e: self.update_param('iso', self.iso_combo.get()))
        self.iso_combo.pack(side=tk.RIGHT)

        # Mode Dial
        mode_row = tk.Frame(adj_frame, bg="#222222")
        mode_row.pack(fill=tk.X, padx=8, pady=4)
        tk.Label(mode_row, text="Mode Dial:", font=("Segoe UI", 8), fg="#aaaaaa", bg="#222222", width=13, anchor=tk.W).pack(side=tk.LEFT)
        self.mode_combo = ttk.Combobox(mode_row, values=["M", "A", "S", "P", "AUTO", "MOVIE", "S&Q"], width=10, state="readonly")
        self.mode_combo.set(self.mode)
        self.mode_combo.bind("<<ComboboxSelected>>", lambda e: self.update_param('mode', self.mode_combo.get()))
        self.mode_combo.pack(side=tk.RIGHT)

        # Draw initial screen
        self.render_screen()

    def update_param(self, name, val):
        setattr(self, name, val)
        self.render_screen()

    def render_screen(self):
        self.lcd_canvas.delete("all")
        if self.current_screen == "liveview":
            self.draw_liveview()
        elif self.current_screen == "menu":
            self.draw_menu()

    def draw_liveview(self):
        c = self.lcd_canvas
        w, h = 640, 480

        # Background (viewfinder dark gradient)
        c.create_rectangle(0, 0, w, h, fill="#0a0a0a", outline="")

        # Rule of thirds grid
        c.create_line(w * 0.33, 0, w * 0.33, h, fill="#1c1c1c", dash=(2, 4))
        c.create_line(w * 0.66, 0, w * 0.66, h, fill="#1c1c1c", dash=(2, 4))
        c.create_line(0, h * 0.33, w, h * 0.33, fill="#1c1c1c", dash=(2, 4))
        c.create_line(0, h * 0.66, w, h * 0.66, fill="#1c1c1c", dash=(2, 4))

        # TOP BAR
        c.create_rectangle(0, 0, w, 40, fill="#111111", outline="")
        c.create_text(25, 20, text=f"[{self.mode}]", fill="#ff9900", font=("Helvetica", 13, "bold"))
        c.create_text(75, 20, text="3:2  24M", fill="#ffffff", font=("Helvetica", 10, "bold"))
        c.create_text(150, 20, text="RAW+J", fill="#ffffff", font=("Helvetica", 10, "bold"))
        c.create_text(220, 20, text="\u25a0 [1] 9999", fill="#ffffff", font=("Helvetica", 10))
        c.create_text(540, 20, text=f"{self.battery}%", fill="#ffffff", font=("Helvetica", 10, "bold"))
        # Battery icon
        c.create_rectangle(575, 12, 605, 26, outline="#ffffff", width=2)
        c.create_rectangle(577, 14, 577 + int(26 * (self.battery/100)), 24, fill="#44ff44", outline="")
        c.create_rectangle(605, 16, 608, 22, fill="#ffffff", outline="")

        # CENTER AF FRAME (Eye-AF tracker)
        cx, cy = w // 2, h // 2
        # Center target
        c.create_rectangle(cx - 30, cy - 30, cx + 30, cy + 30, outline="#555555", width=1, dash=(3, 3))
        # Green active tracking box
        c.create_rectangle(cx - 15, cy - 15, cx + 15, cy + 15, outline="#00ff00", width=2)
        c.create_text(cx, cy - 25, text="[ EYE-AF ]", fill="#00ff00", font=("Helvetica", 8, "bold"))

        # RIGHT FUNCTION OVERLAY
        rx = w - 45
        c.create_rectangle(w - 75, 55, w - 10, 420, fill="#141414", outline="#282828")
        items = [
            ("AF", self.focus_mode),
            ("AREA", self.focus_area),
            ("DRIVE", "Single"),
            ("WB", self.wb),
            ("COLOR", "Std"),
            ("PP", "PP10"),
            ("METER", "Multi")
        ]
        for i, (k, v) in enumerate(items):
            y = 75 + i * 50
            c.create_text(rx, y - 8, text=k, fill="#888888", font=("Helvetica", 8, "bold"))
            c.create_text(rx, y + 8, text=v, fill="#ffffff", font=("Helvetica", 9, "bold"))
            if i < len(items) - 1:
                c.create_line(w - 70, y + 22, w - 15, y + 22, fill="#252525")

        # BOTTOM EXPOSURE BAR
        c.create_rectangle(0, h - 50, w, h, fill="#111111", outline="")
        c.create_text(60, h - 25, text=self.shutter, fill="#ffffff", font=("Helvetica", 16, "bold"))
        c.create_text(160, h - 25, text=self.aperture, fill="#ffffff", font=("Helvetica", 16, "bold"))
        c.create_text(280, h - 25, text=f"MM {self.ev}", fill="#ffffff", font=("Helvetica", 14))
        # Meter scale
        c.create_line(340, h - 25, 430, h - 25, fill="#888888", width=2)
        c.create_line(385, h - 32, 385, h - 18, fill="#ff9900", width=2) # Center 0
        c.create_text(520, h - 25, text=f"ISO {self.iso}", fill="#ffffff", font=("Helvetica", 16, "bold"))

    def draw_menu(self):
        c = self.lcd_canvas
        w, h = 640, 480

        # Background
        c.create_rectangle(0, 0, w, h, fill="#0c0c0c", outline="")

        # Top 6 Tabs Bar
        tab_colors = ["#d93829", "#9b51e0", "#27ae60", "#2f80ed", "#f2994a", "#e2b93b"]
        tab_names = ["1. Foto", "2. Movie", "3. Mre\u017ea", "4. Play", "5. Setup", "\u2605 Meni"]
        tab_w = w // 6

        for i in range(6):
            x1 = i * tab_w
            x2 = x1 + tab_w
            color = tab_colors[i] if self.menu_tab == i else "#222222"
            fg = "#ffffff" if self.menu_tab == i else "#777777"
            c.create_rectangle(x1, 0, x2, 45, fill=color, outline="#111111")
            c.create_text((x1 + x2) // 2, 22, text=tab_names[i], fill=fg, font=("Helvetica", 9, "bold"))

        # Sub-header page number
        c.create_rectangle(0, 45, w, 75, fill="#1a1a1a", outline="")
        c.create_text(50, 60, text=f"Stranica {self.menu_page}/7", fill="#ffffff", font=("Helvetica", 10, "bold"))

        # Menu content based on tab
        menus = {
            0: [
                ("Format slike (Aspect Ratio)", "3:2"),
                ("Kvalitet fotografije", "RAW & JPEG"),
                ("Tip fokusa (Focus Mode)", self.focus_mode),
                ("Fokusna oblast (Focus Area)", self.focus_area),
                ("Pode\u0161avanje AF lica/o\u010diju", "Uklju\u010deno (Animal & Human)"),
                ("ISO osetljivost", self.iso)
            ],
            1: [
                ("Format video zapisa", "XAVC S 4K (25p 100M)"),
                ("Dvostruko snimanje", "Isklju\u010deno"),
                ("S&Q Pode\u0161avanje", "100fps (4x Usporeno)"),
                ("Picture Profile", self.profile),
                ("Zebra prikaz", "Isklju\u010deno"),
                ("Nivo snimanja zvuka", "26 dB")
            ],
            2: [
                ("Slanje na pametni telefon", "Povezivanje preko Wi-Fi"),
                ("Kontrola sa pametnog telefona", "Uklju\u010deno"),
                ("Bluetooth postavke", "Uparivanje (RMT-P1BT)"),
                ("Ure\u0111ivanje naziva ure\u0111aja", "ILCE-6400"),
                ("Poni\u0161ti Wi-Fi postavke", "Enter"),
                ("Prikaz MAC adrese", "BC:6E:BF:.. (Broadcom)")
            ],
            3: [
                ("Za\u0161tita slika (Protect)", "Izaberi sliku"),
                ("Rotiranje prikaza", "Automatski"),
                ("Ocena (Rating)", "\u2605\u2605\u2605\u2605\u2605"),
                ("Pove\u0107avanje (Enlarge Image)", "2.0x"),
                ("Slajd \u0161ou", "Pokreni"),
                ("Prikaz na TV ure\u0111aju", "HDMI 4K izlaz")
            ],
            4: [
                ("Osvetljenje monitora", "Ru\u010dno (+2)"),
                ("Jezik (Language)", "OTKLJU\u010cANO: English / Srpski / Deutsch"),
                ("USB Povezivanje (USB Mode)", "Mass Storage (MSC)"),
                ("USB Napajanje (Power Supply)", "Uklju\u010deno"),
                ("PAL / NTSC Izbor", "PAL (50Hz)"),
                ("Verzija (Version)", "ILCE-6400 Ver. 2.00")
            ],
            5: [
                ("Dodaj stavku u My Menu", "+ Dodaj"),
                ("Sortiraj pre\u010dice", "Izmeni"),
                ("Izbri\u0161i stavku", "Izaberi"),
                ("Izbri\u0161i sve", "Poni\u0161ti"),
                ("Prikaz sa My Menu", "Uklju\u010deno"),
                ("Prazno polje", "-")
            ]
        }

        current_items = menus.get(self.menu_tab, menus[0])
        for idx, (title, val) in enumerate(current_items):
            y = 105 + idx * 52
            bg_col = "#242424" if idx == 0 else "#151515" # highlight first item
            c.create_rectangle(15, y - 20, w - 15, y + 25, fill=bg_col, outline="#333333")
            c.create_text(35, y + 2, text=title, fill="#ffffff", font=("Helvetica", 10), anchor=tk.W)
            c.create_text(w - 35, y + 2, text=val, fill="#ff9900" if idx == 0 else "#aaaaaa", font=("Helvetica", 9, "bold"), anchor=tk.E)

        # Footer Help
        c.create_rectangle(0, h - 35, w, h, fill="#111111", outline="")
        c.create_text(w // 2, h - 18, text="[DISP] Promena kartice | [Fn] Prethodna | [OK] Izaberi | [MENU] Nazad", fill="#777777", font=("Helvetica", 8))

    # Controls handlers
    def on_shutter(self):
        self.play_sound("Dslr_Emnt_Shutter_Ka.bin")
        # Flash animation
        self.lcd_canvas.create_rectangle(0, 0, 640, 480, fill="#ffffff", outline="")
        self.after(60, self.render_screen)

    def on_focus(self):
        self.play_sound("Dslr_Emnt_FocusLock.bin")
        # Beep animation
        self.render_screen()

    def toggle_menu(self):
        self.play_sound("Dslr_Emnt_T_Menu_Open.bin")
        self.current_screen = "menu" if self.current_screen == "liveview" else "liveview"
        self.render_screen()

    def on_disp(self):
        self.play_sound("Dslr_Emnt_Select_SwitchMode.bin")
        if self.current_screen == "menu":
            self.menu_tab = (self.menu_tab + 1) % 6
        self.render_screen()

    def on_fn(self):
        self.play_sound("Dslr_Emnt_T_Select.bin")
        if self.current_screen == "menu":
            self.menu_tab = (self.menu_tab - 1) % 6
        self.render_screen()

    def play_sound(self, filename):
        if not HAS_WINSOUND:
            return
        sound_path = os.path.join(SOUND_DIR, filename)
        if os.path.exists(sound_path):
            try:
                with open(sound_path, 'rb') as f:
                    raw = f.read()
                # 64-byte header skip, 8-bit unsigned PCM at 16000 Hz
                pcm = raw[64:]
                wav_buffer = io.BytesIO()
                with wave.open(wav_buffer, 'wb') as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(1)
                    wf.setframerate(16000)
                    wf.writeframes(pcm)
                wav_buffer.seek(0)
                winsound.PlaySound(wav_buffer.read(), winsound.SND_MEMORY | winsound.SND_ASYNC)
            except Exception:
                pass

    # =========================================================================
    # TAB 2: SONY ICONS BROWSER
    # =========================================================================
    def build_icons_tab(self):
        top_bar = tk.Frame(self.tab_icons, bg="#181818")
        top_bar.pack(fill=tk.X, padx=15, pady=10)

        info_lbl = tk.Label(
            top_bar,
            text=f"Izvu\u010deni fajl: Sony_DI_Icons.ttf (Ukupno 1,482 glifa)",
            font=("Segoe UI", 10, "bold"),
            fg="#ff7700",
            bg="#181818"
        )
        info_lbl.pack(side=tk.LEFT)

        export_btn = tk.Button(
            top_bar, text="Izvezi Prikazane Ikone u PNG", font=("Segoe UI", 9), bg="#333333", fg="#ffffff",
            command=self.export_icon_sheet
        )
        export_btn.pack(side=tk.RIGHT)

        # Scrollable icon canvas
        self.icon_canvas = tk.Canvas(self.tab_icons, bg="#0d0d0d", highlightthickness=0)
        scrollbar = ttk.Scrollbar(self.tab_icons, orient=tk.VERTICAL, command=self.icon_canvas.yview)
        self.scroll_frame = tk.Frame(self.icon_canvas, bg="#0d0d0d")

        self.scroll_frame.bind(
            "<Configure>", lambda e: self.icon_canvas.configure(scrollregion=self.icon_canvas.bbox("all"))
        )
        self.icon_canvas.create_window((0, 0), window=self.scroll_frame, anchor="nw")
        self.icon_canvas.configure(yscrollcommand=scrollbar.set)

        self.icon_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=15, pady=5)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y, pady=5)

        self.load_icons_preview()

    def load_icons_preview(self):
        if not self.sony_icon_font:
            lbl = tk.Label(self.scroll_frame, text="Sony_DI_Icons.ttf font nije pronađen.", fg="#ff4444", bg="#0d0d0d")
            lbl.pack(pady=20)
            return

        # Render first 120 icons in a grid
        self.icon_images = [] # keep ref
        cols = 10
        base_code = 0xE000
        for i in range(100):
            r = i // cols
            c = i % cols
            code = base_code + i

            # Render glyph to image using PIL
            im = Image.new("RGBA", (50, 50), (25, 25, 25, 255))
            draw = ImageDraw.Draw(im)
            draw.text((10, 8), chr(code), font=self.sony_icon_font, fill=(255, 255, 255, 255))
            photo = ImageTk.PhotoImage(im)
            self.icon_images.append(photo)

            cell = tk.Frame(self.scroll_frame, bg="#1a1a1a", bd=1, relief=tk.SOLID)
            cell.grid(row=r*2, column=c, padx=4, pady=4)
            img_lbl = tk.Label(cell, image=photo, bg="#1a1a1a")
            img_lbl.pack()
            code_lbl = tk.Label(cell, text=f"U+{code:04X}", font=("Segoe UI", 7), fg="#888888", bg="#1a1a1a")
            code_lbl.pack()

    def export_icon_sheet(self):
        out_dir = legacy_output("exported_icons")
        os.makedirs(out_dir, exist_ok=True)
        count = 0
        for code in range(0xE000, 0xE000 + 150):
            im = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
            draw = ImageDraw.Draw(im)
            draw.text((12, 10), chr(code), font=self.sony_icon_large, fill=(255, 119, 0, 255))
            if im.getbbox():
                im.save(os.path.join(out_dir, f"icon_{code:04X}.png"))
                count += 1
        messagebox.showinfo("Uspeh", f"Uspešno izvezeno {count} ikona u folder:\n{out_dir}")

    # =========================================================================
    # TAB 3: UXC SCENE EXPLORER
    # =========================================================================
    def build_uxc_tab(self):
        container = tk.Frame(self.tab_uxc, bg="#181818")
        container.pack(fill=tk.BOTH, expand=True, padx=15, pady=10)

        left = tk.Frame(container, bg="#181818", width=350)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=5)

        tk.Label(left, text="Spisak .uxc Ekrana (Scene Layouts):", font=("Segoe UI", 9, "bold"), fg="#ffffff", bg="#181818").pack(anchor=tk.W, pady=5)
        
        self.uxc_listbox = tk.Listbox(left, bg="#111111", fg="#ffffff", selectbackground="#ff7700", font=("Consolas", 9), width=35)
        self.uxc_listbox.pack(fill=tk.BOTH, expand=True)
        self.uxc_listbox.bind("<<ListboxSelect>>", self.on_select_uxc)

        right = tk.Frame(container, bg="#181818")
        right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=10)

        self.uxc_details = tk.Text(right, bg="#0d0d0d", fg="#44ff44", font=("Consolas", 9), insertbackground="#ffffff")
        self.uxc_details.pack(fill=tk.BOTH, expand=True)

        # Populate
        if os.path.exists(NFLASHA15_APP):
            uxc_files = sorted([f for f in os.listdir(NFLASHA15_APP) if f.endswith(".uxc")])
            for f in uxc_files:
                self.uxc_listbox.insert(tk.END, f)

    def on_select_uxc(self, event):
        sel = self.uxc_listbox.curselection()
        if not sel:
            return
        fn = self.uxc_listbox.get(sel[0])
        fp = os.path.join(NFLASHA15_APP, fn)
        with open(fp, "rb") as f:
            data = f.read()

        import re
        strings = re.findall(rb'[a-zA-Z0-9_\-\.]{3,}', data)

        self.uxc_details.delete("1.0", tk.END)
        self.uxc_details.insert(tk.END, f"=====================================================\n")
        self.uxc_details.insert(tk.END, f" FAJL: {fn}\n")
        self.uxc_details.insert(tk.END, f" Veličina: {len(data):,} bajtova\n")
        self.uxc_details.insert(tk.END, f" Zaglavlje: {data[:16].hex()}\n")
        self.uxc_details.insert(tk.END, f"=====================================================\n\n")
        self.uxc_details.insert(tk.END, f"--- Pronađeni tekstualni stringovi / Reference ---\n")
        for s in strings[:40]:
            self.uxc_details.insert(tk.END, f"  > {s.decode('latin1', 'ignore')}\n")

    # =========================================================================
    # TAB 4: AUDIO SOUNDBOARD
    # =========================================================================
    def build_sound_tab(self):
        container = tk.Frame(self.tab_sound, bg="#181818")
        container.pack(fill=tk.BOTH, expand=True, padx=20, pady=15)

        tk.Label(
            container, text="FABRI\u010cKI AUDIO EFEKTI KAMERE (avsystemsound)",
            font=("Segoe UI", 11, "bold"), fg="#ff7700", bg="#181818"
        ).pack(anchor=tk.W, pady=5)

        grid_frame = tk.Frame(container, bg="#181818")
        grid_frame.pack(fill=tk.BOTH, expand=True, pady=10)

        # Parse beeplist.txt
        beeplist_path = os.path.join(SOUND_DIR, "beeplist.txt")
        sounds = []
        if os.path.exists(beeplist_path):
            with open(beeplist_path, "r", encoding="latin1") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("BEEP_ID_") and ".bin" in line:
                        parts = line.split()
                        name = parts[0].replace("BEEP_ID_", "")
                        for p in parts:
                            if p.endswith(".bin"):
                                sounds.append((name, p))
                                break

        for i, (name, fn) in enumerate(sounds[:18]):
            r = i // 3
            col = i % 3
            card = tk.Frame(grid_frame, bg="#222222", bd=1, relief=tk.RAISED)
            card.grid(row=r, column=col, padx=8, pady=8, sticky="nsew")

            tk.Label(card, text=name, font=("Segoe UI", 9, "bold"), fg="#ffffff", bg="#222222").pack(anchor=tk.W, padx=10, pady=4)
            tk.Label(card, text=fn, font=("Segoe UI", 7), fg="#888888", bg="#222222").pack(anchor=tk.W, padx=10)

            tk.Button(
                card, text="\u25b6 Pusti Zvuk", font=("Segoe UI", 8), bg="#333333", fg="#44ff44",
                command=lambda f=fn: self.play_sound(f)
            ).pack(anchor=tk.E, padx=10, pady=6)

        for c in range(3):
            grid_frame.grid_columnconfigure(c, weight=1)

if __name__ == '__main__':
    app = SonyCameraApp()
    app.mainloop()
