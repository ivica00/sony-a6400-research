import os
import sys
import struct
import random
import math
import json
from legacy.execution_audit import UnsupportedBehavior
from legacy.elf_layout import load_span, symbol_relocation
from PIL import Image, ImageDraw, ImageFont
import unicorn
from unicorn.arm_const import *
from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_THUMB
from elftools.elf.elffile import ELFFile

from project_paths import PROJECT_ROOT as _PROJECT_ROOT, REFERENCE_ASSETS, legacy_output
PROJECT_ROOT = str(_PROJECT_ROOT)
EXTRACTED_DIR = os.path.join(PROJECT_ROOT, "firmware", "extracted_a6400")
LIB_DIR = os.path.join(
    EXTRACTED_DIR, "firmware.tar_unpacked", "0700_part_image", "dev", "nflasha15_unpacked", "lib"
)
BIN_DIR = os.path.join(
    EXTRACTED_DIR, "firmware.tar_unpacked", "0700_part_image", "dev", "nflasha15_unpacked", "bin"
)
APP_DIR = os.path.join(
    EXTRACTED_DIR, "firmware.tar_unpacked", "0700_part_image", "dev", "nflasha15_unpacked", "share", "app"
)

# Sony CXD90045 Memory Map
RAM_BASE       = 0x20000000  # 128 MB Main System RAM
RAM_SIZE       = 128 * 1024 * 1024
FRAMEBUFFER    = 0x60000000  # 16 MB High RAM / Display DMA Framebuffer
FB_SIZE        = 16 * 1024 * 1024
MMIO_BASE      = 0xA0000000  # 16 MB Sony BOSS Peripherals & Hardware Registers
MMIO_SIZE      = 16 * 1024 * 1024
HLE_STUB_BASE  = 0x10000000  # 4 MB HLE Function Trampoline Table
HLE_STUB_SIZE  = 4 * 1024 * 1024
STACK_BASE     = 0x27000000  # 8 MB Stack in RAM
STACK_SIZE     = 8 * 1024 * 1024
HEAP_BASE      = 0x21000000  # 32 MB Heap in RAM

# LCD Specifications (Sony 3.0" 16:9 LCD)
LCD_WIDTH      = 960
LCD_HEIGHT     = 540

# ARM Relocation Codes
R_ARM_ABS32     = 2
R_ARM_REL32     = 3
R_ARM_GLOB_DAT  = 21
R_ARM_JUMP_SLOT = 22
R_ARM_RELATIVE  = 23

# Sony Hardware Key Codes (verified from libObj.so key table)
KEY_TACT_POWER          = 0x0003  # 3
KEY_TACT_UP             = 0x0013  # 19 (D-Pad UP)
KEY_TACT_LEFT           = 0x0020  # 32 (D-Pad LEFT)
KEY_TACT_DOWN           = 0x0041  # 65 (D-Pad DOWN)
KEY_TACT_RIGHT          = 0x01bf  # 447 (D-Pad RIGHT)
KEY_TACT_ENTER          = 0x01ad  # 429 (D-Pad OK)
KEY_TACT_MENU           = 0x01ac  # 428 (MENU)
KEY_TACT_DISP           = 0x01fb  # 507 (DISP)
KEY_TACT_FN             = 0x7096  # 28822 (Fn)
KEY_TACT_PLAY           = 0x01f8  # 504 (PLAYBACK)
KEY_TACT_DELETE         = 0x01f9  # 505 (TRASH / C2)
KEY_TACT_CUSTOM         = 0x00a7  # 167 (C1)
KEY_TACT_CUSTOM2        = 0x70e8  # 28904 (C2)
KEY_OTHER_WHEEL_LEFT    = 0x10000004  # 268435460 (Rotary CCW)
KEY_OTHER_WHEEL_RIGHT   = 0x10000005  # 268435461 (Rotary CW)
KEY_OTHER_KURU_LEFT     = 0x10000001  # Top Dial Left
KEY_OTHER_KURU_RIGHT    = 0x10000003  # Top Dial Right
KEY_REMOTE_S1           = 0x1a00000e  # 436207630 (Shutter Half-press / AF)
KEY_REMOTE_S2           = 0x1a00000f  # 436207631 (Shutter Full-press / Release)

class CXD90045_HLE_Emulator:
    def __init__(self, mode="research"):
        if mode not in ("research", "strict"):
            raise ValueError("mode must be research or strict")
        self.mode = mode
        self.audit_events = []
        self.last_execution = None
        print("=" * 70)
        print(" SONY CXD90045 HIGH-LEVEL EMULATOR & TRANSLATION HARNESS (ARMv7)")
        print("=" * 70)
        
        # Initialize Unicorn ARM CPU Core (Cortex-A with VFP/NEON)
        self.mu = unicorn.Uc(unicorn.UC_ARCH_ARM, unicorn.UC_MODE_ARM)
        self.mu.ctl_set_cpu_model(unicorn.arm_const.UC_CPU_ARM_CORTEX_A9)
        self.mu.reg_write(unicorn.arm_const.UC_ARM_REG_FPEXC, 0x40000000)
        
        # Disassemblers
        self.cs_arm = Cs(CS_ARCH_ARM, CS_MODE_ARM)
        self.cs_thumb = Cs(CS_ARCH_ARM, CS_MODE_THUMB)

        # Dynamic Heap Allocation
        self.heap_ptr = HEAP_BASE
        
        # Virtual File System (VFS)
        self.open_files = {}
        self.next_fd = 10
        
        # HLE Stubs registry
        self.stubs = {}  # addr -> (name, handler)
        self.stub_by_name = {} # name -> addr
        self.next_stub_addr = HLE_STUB_BASE + 0x100
        
        # Symbol table of loaded libraries
        self.symbols = {} # name -> addr
        self.loaded_modules = {}

        # Screen & Navigation Manager
        self.active_screen = "LIVE_VIEW" # LIVE_VIEW, MENU, QUICK_NAVI, FN_MENU, PLAYBACK
        self.screen_instances = {}       # name -> heap_addr
        self.menu_tab = 1                # 1 to 6
        self.menu_item = 0               # 0 to 5
        self.menu_sub_active = False     # Whether an item's options popup is active
        self.menu_sub_index = 0          # Selected option index in sub-menu
        self.fn_index = 0                # 0 to 11
        self.liveview_disp_mode = 0      # 0=Graphic, 1=All Info, 2=No Info, 3=Histogram
        self.playback_index = 0          # Selected photo in playback
        self.playback_disp_mode = 0      # 0=Full Info + Histogram, 1=Minimal, 2=Clean
        self.playback_grid_view = False  # 9-photo contact sheet view
        self.af_locked = False           # Shutter S1 half-press lock
        self.shutter_flash = False       # Shutter capture flash
        self.backup_nvram = {}           # Persistent Backup EEPROM dictionary

        # Camera state matching user photo and physical controls
        self.camera_state = {
            "mode": "M",
            "shutter_num": 1,
            "shutter_den": 60,          # 1/60
            "aperture_val": 18,         # 18 / 10 = F1.8
            "aperture_div": 10,
            "iso_mode": 0,              # 0 = ISO AUTO
            "iso_val": 400,             # current metering ISO 400
            "exp_comp": "±0.0",         # +-0.0
            "picture_profile": 2,       # PP2
            "quality": "RAW",           # RAW, RAW & JPEG, JPEG Ekstra fino, JPEG Fino, JPEG Standardno
            "raw_type": "Kompresovan RAW",
            "jpeg_size": "L: 24M",
            "aspect_ratio": "3:2",      # 3:2, 16:9, 1:1
            "panorama": "Standardno",
            "long_exp_nr": "Ukljuceno",
            "shutter_type": "Mehanicki",
            "silent_shutter": "Iskljuceno",
            "release_w_o_lens": "Omoguceno",
            "steadyshot": "Ukljuceno",
            "color_space": "sRGB",
            "grid_line": "Rule of 3rds",
            "focus_mode": "AF-C",
            "focus_area": "Wide",
            "drive_mode": "Single",
            "metering": "Multi",
            "white_balance": "AWB",
            "dro_hdr": "Off",
            "peaking": "Mid/Yel",
            "card_remaining": 4882,
            "battery_pct": 100,
            "is_charging": True,
            "accent_color": "#FF6600"   # Sony Orange
        }

        # Load authentic user BIONZ X frame (20261015-_DSC0799 copy.jpg)
        self.sensor_live_frame = None
        self.sensor_card_thumb = None
        self.sensor_img_hist = None
        user_img_path = str(REFERENCE_ASSETS / "20261015-_DSC0799 copy.jpg")
        if os.path.exists(user_img_path):
            try:
                raw_img = Image.open(user_img_path)
                self.sensor_live_frame = raw_img.resize((LCD_WIDTH, LCD_HEIGHT), Image.Resampling.LANCZOS).convert("RGBA")
                self.sensor_3_2_frame = raw_img.resize((810, 540), Image.Resampling.LANCZOS).convert("RGBA")
                self.sensor_card_thumb = raw_img.resize((480, 320), Image.Resampling.LANCZOS).convert("RGBA")
                hist = raw_img.histogram()
                self.sensor_img_hist = (hist[0:256], hist[256:512], hist[512:768])
                print(f"[+] Uspesno ucitan autenticni BIONZ X senzorski feed: {os.path.basename(user_img_path)} (6000x4000 -> 810x540 3:2 pillar-box)")
            except Exception as e:
                print(f"[-] Nije moguce ucitati senzorski feed: {e}")

        # Load authentic Sony_DI_Icons.ttf and UI fonts
        font_ttf = os.path.join(PROJECT_ROOT, r"firmware\extracted_a6400\firmware.tar_unpacked\0800_appli\tmp\images\Sony_DI_Icons.ttf")
        try:
            self.f_icons_large = ImageFont.truetype(font_ttf, 32)
            self.f_icons_med   = ImageFont.truetype(font_ttf, 24)
            self.f_icons_small = ImageFont.truetype(font_ttf, 18)
            self.f_icons_tiny  = ImageFont.truetype(font_ttf, 14)
        except Exception:
            self.f_icons_large = self.f_icons_med = self.f_icons_small = self.f_icons_tiny = ImageFont.load_default()

        try:
            self.f_sans_huge   = ImageFont.truetype("arialbd.ttf", 36)
            self.f_sans_large  = ImageFont.truetype("arialbd.ttf", 24)
            self.f_sans_med    = ImageFont.truetype("arial.ttf", 19)
            self.f_sans_bold   = ImageFont.truetype("arialbd.ttf", 18)
            self.f_sans_small  = ImageFont.truetype("arial.ttf", 15)
            self.f_sans_tiny   = ImageFont.truetype("arial.ttf", 12)
        except Exception:
            self.f_sans_huge = self.f_sans_large = self.f_sans_med = self.f_sans_bold = self.f_sans_small = self.f_sans_tiny = ImageFont.load_default()

        # Authentic Sony a6400 Sample Playback Photos
        self.playback_photos = [
            {
                "id": "_DSC0799",
                "date": "2026/10/15 13:45",
                "format": "RAW 24M",
                "shutter": "1/60",
                "aperture": "F1.8",
                "iso": "ISO 200",
                "exp": "±0.0",
                "lens": "TTARTISAN 35mm F1.8",
                "profile": "PP2",
                "bg_color": (32, 45, 36),
                "title": "ILCE-6400 Authentic Shot",
                "image_obj": self.sensor_live_frame,
                "card_thumb": self.sensor_card_thumb
            },
            {
                "id": "100-0042",
                "date": "2026/10/18 09:25",
                "format": "RAW+JPEG",
                "shutter": "1/60",
                "aperture": "F1.8",
                "iso": "ISO 400",
                "exp": "±0.0",
                "lens": "Sony E 35mm F1.8 OSS",
                "profile": "PP2",
                "bg_color": (32, 40, 30),
                "title": "BIONZ X Dark Frame Sensor Test"
            },
            {
                "id": "100-0041",
                "date": "2026/10/18 09:12",
                "format": "RAW",
                "shutter": "1/250",
                "aperture": "F2.8",
                "iso": "ISO 100",
                "exp": "+0.3",
                "lens": "Sony E 35mm F1.8 OSS",
                "profile": "PP1",
                "bg_color": (25, 35, 50),
                "title": "Optics Calibration Target"
            },
            {
                "id": "100-0040",
                "date": "2026/10/18 08:50",
                "format": "JPEG Fine",
                "shutter": "1/1000",
                "aperture": "F4.0",
                "iso": "ISO 800",
                "exp": "-0.7",
                "lens": "Sony E 35mm F1.8 OSS",
                "profile": "Off",
                "bg_color": (45, 35, 25),
                "title": "Dynamic Range Daylight Scene"
            }
        ]

        # Detailed mapping of all 6 tabs and items to parameter options & backup tags
        self.menu_options_map = {
            # Tab 1: 1 Snimanje (Image Quality)
            (1, 0): {"name": "Format datoteke", "key": "quality", "options": ["RAW", "RAW & JPEG", "JPEG Ekstra fino", "JPEG Fino", "JPEG Standardno"], "tag": 0x0101},
            (1, 1): {"name": "Kvalitet slike", "key": "raw_type", "options": ["Kompresovan RAW", "Nekompresovan RAW"], "tag": 0x0102},
            (1, 2): {"name": "Velicina slike (JPEG)", "key": "jpeg_size", "options": ["L: 24M", "M: 12M", "S: 6.0M"], "tag": 0x0103},
            (1, 3): {"name": "Odnos stranica", "key": "aspect_ratio", "options": ["3:2", "16:9", "1:1"], "tag": 0x0104},
            (1, 4): {"name": "Format panorame", "key": "panorama", "options": ["Standardno", "Siroko"], "tag": 0x0105},
            (1, 5): {"name": "Dugotrajna ekspozicija NR", "key": "long_exp_nr", "options": ["Ukljuceno", "Iskljuceno"], "tag": 0x0106},

            # Tab 2: 2 Snimanje (Shooting Settings)
            (2, 0): {"name": "Tip okidaca", "key": "shutter_type", "options": ["Mehanicki", "Elektronska prva zavesica", "Potpuno elektronski"], "tag": 0x0201},
            (2, 1): {"name": "Tiho snimanje", "key": "silent_shutter", "options": ["Iskljuceno", "Ukljuceno"], "tag": 0x0202},
            (2, 2): {"name": "Release bez objektiva", "key": "release_w_o_lens", "options": ["Omoguceno", "Onemoguceno"], "tag": 0x0203},
            (2, 3): {"name": "SteadyShot", "key": "steadyshot", "options": ["Ukljuceno", "Iskljuceno"], "tag": 0x0204},
            (2, 4): {"name": "Color Space", "key": "color_space", "options": ["sRGB", "AdobeRGB"], "tag": 0x0205},
            (2, 5): {"name": "Grid Line", "key": "grid_line", "options": ["Rule of 3rds", "Square Grid", "Diag + Square", "Iskljuceno"], "tag": 0x0206},

            # Tab 3: Mreza
            (3, 0): {"name": "Funkcija Slanja na Smartfon", "key": "send_smart", "options": ["Ukljuceno", "Iskljuceno"], "tag": 0x0301},
            (3, 1): {"name": "Slanje na Racunar", "key": "send_pc", "options": ["Ukljuceno", "Iskljuceno"], "tag": 0x0302},
            (3, 2): {"name": "Prikaz na TV", "key": "tv_out", "options": ["Spreman", "Prekid"], "tag": 0x0303},
            (3, 3): {"name": "WLAN Podesavanja", "key": "wlan_mode", "options": ["WPS Push", "Access Point Povezivanje"], "tag": 0x0304},
            (3, 4): {"name": "Bluetooth Podesavanja", "key": "bt_mode", "options": ["Ukljuceno", "Iskljuceno"], "tag": 0x0305},
            (3, 5): {"name": "Uredjivanje naziva uredjaja", "key": "device_name", "options": ["ILCE-6400 (Sony α6400)"], "tag": 0x0306},

            # Tab 4: Reprodukcija
            (4, 0): {"name": "Zastita (Protect)", "key": "protect", "options": ["Pojedinacno", "Vise slika", "Sve slike"], "tag": 0x0401},
            (4, 1): {"name": "Rotiraj prikaz", "key": "rotate", "options": ["Automatski", "Rucno", "Iskljuceno"], "tag": 0x0402},
            (4, 2): {"name": "Brisanje (Delete)", "key": "delete", "options": ["Obrisi ovu sliku", "Obrisi oznacene", "Obrisi sve"], "tag": 0x0403},
            (4, 3): {"name": "Prikaz slajdova", "key": "slideshow", "options": ["3 sekunde", "5 sekundi", "10 sekundi"], "tag": 0x0404},
            (4, 4): {"name": "Indeks prikaz", "key": "index_disp", "options": ["9 slika", "25 slika"], "tag": 0x0405},
            (4, 5): {"name": "Kopiranje", "key": "copy", "options": ["Iskljuceno", "SD kartica -> Racunar"], "tag": 0x0406},

            # Tab 5: Podesavanja (Setup)
            (5, 0): {"name": "Osvetljenost monitora", "key": "lcd_bright", "options": ["Rucno: ±0", "Rucno: +1", "Rucno: +2", "Suncano vreme"], "tag": 0x0501},
            (5, 1): {"name": "Nacin prikaza tražila", "key": "evf_fps", "options": ["Standardno (60fps)", "Visoko (120fps)"], "tag": 0x0502},
            (5, 2): {"name": "Automatsko iskljucivanje", "key": "auto_power_off", "options": ["1 Minut", "2 Minuta", "5 Minuta", "30 Minuta"], "tag": 0x0503},
            (5, 3): {"name": "Verzija Firmware-a", "key": "fw_version", "options": ["Ver. 2.00 (CXD90045 BOSS ARMv7 HLE)"], "tag": 0x0504},
            (5, 4): {"name": "Resetovanje podesavanja", "key": "reset_action", "options": ["Spreman", "Potvrdi Reset Fabrickih Podesavanja"], "tag": 0x0505},
            (5, 5): {"name": "Formatiranje kartice", "key": "format_action", "options": ["Spreman [1] SD (256 GB)", "Izvrsi brzo formatiranje"], "tag": 0x0506},

            # Tab 6: Moj Meni (My Menu)
            (6, 0): {"name": "Dodaj stavku u Moj Meni", "key": "my_menu_add", "options": ["Izaberi...", "Format datoteke", "Tiho snimanje", "SteadyShot"], "tag": 0x0601},
            (6, 1): {"name": "Sortiraj stavke", "key": "my_menu_sort", "options": ["Normalno", "Prilagodjeno"], "tag": 0x0602},
            (6, 2): {"name": "Obrisi stavku", "key": "my_menu_del", "options": ["Izaberi..."], "tag": 0x0603},
            (6, 3): {"name": "Obrisi sve stavke", "key": "my_menu_del_all", "options": ["Ne", "Da, obrisi sve"], "tag": 0x0604},
            (6, 4): {"name": "Prikaz sa Moga Menija", "key": "my_menu_disp", "options": ["Iskljuceno", "Ukljuceno"], "tag": 0x0605},
            (6, 5): {"name": "Moj Meni Reset", "key": "my_menu_reset", "options": ["Spreman", "Resetuj Moj Meni"], "tag": 0x0606},
        }

        self.param_val_nodes = {}

        self.setup_memory_map()
        self.setup_hooks()
        self.register_core_hle_stubs()

    def unsupported(self, kind, **details):
        event = {"kind": kind, "pc": self.mu.reg_read(UC_ARM_REG_PC), **details}
        self.audit_events.append(event)
        if self.mode == "strict":
            raise UnsupportedBehavior(json.dumps(event))

    def write_execution_report(self, path):
        from pathlib import Path
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({"mode": self.mode, "firmware_fidelity_validated": False,
                                     "last_execution": self.last_execution,
                                     "events": self.audit_events}, indent=2), encoding="utf-8")

    def setup_memory_map(self):
        print("[*] Mapiranje virtuelnih memorijskih segmenata (BOSS Arhitektura)...")
        # 1. Main RAM
        self.mu.mem_map(RAM_BASE, RAM_SIZE)
        print(f"    - RAM Base:       0x{RAM_BASE:08x} - 0x{RAM_BASE + RAM_SIZE:08x} ({RAM_SIZE // (1024*1024)} MB)")
        
        # 2. Framebuffer / High RAM
        self.mu.mem_map(FRAMEBUFFER, FB_SIZE)
        print(f"    - Framebuffer:    0x{FRAMEBUFFER:08x} - 0x{FRAMEBUFFER + FB_SIZE:08x} ({FB_SIZE // (1024*1024)} MB)")

        # 3. MMIO Registers
        self.mu.mem_map(MMIO_BASE, MMIO_SIZE)
        print(f"    - MMIO Registri:  0xa0000000 - 0x{MMIO_BASE + MMIO_SIZE:08x} ({MMIO_SIZE // (1024*1024)} MB)")

        # 4. HLE Trampoline Table
        self.mu.mem_map(HLE_STUB_BASE, HLE_STUB_SIZE)
        print(f"    - HLE Trampolines:0x{HLE_STUB_BASE:08x} - 0x{HLE_STUB_BASE + HLE_STUB_SIZE:08x}")

        # Setup initial Stack Pointer (SP)
        initial_sp = STACK_BASE + STACK_SIZE - 0x100
        self.mu.reg_write(UC_ARM_REG_SP, initial_sp)
        print(f"[+] Stack Pointer (SP) postavljen na: 0x{initial_sp:08x}")

    def setup_hooks(self):
        self.mu.hook_add(unicorn.UC_HOOK_MEM_READ, self.hook_mmio_read, begin=MMIO_BASE, end=MMIO_BASE + MMIO_SIZE)
        self.mu.hook_add(unicorn.UC_HOOK_MEM_WRITE, self.hook_mmio_write, begin=MMIO_BASE, end=MMIO_BASE + MMIO_SIZE)
        self.mu.hook_add(unicorn.UC_HOOK_CODE, self.hook_code_execution, begin=HLE_STUB_BASE, end=HLE_STUB_BASE + HLE_STUB_SIZE)
        self.mu.hook_add(unicorn.UC_HOOK_MEM_READ_UNMAPPED, self.hook_unmapped_access)
        self.mu.hook_add(unicorn.UC_HOOK_MEM_WRITE_UNMAPPED, self.hook_unmapped_access)
        self.mu.hook_add(unicorn.UC_HOOK_MEM_FETCH_UNMAPPED, self.hook_unmapped_access)

    def hook_unmapped_access(self, uc, access, address, size, value, user_data):
        self.unsupported("unmapped_access", address=address, access=access, size=size)
        page_addr = address & ~0xFFFF
        page_size = 64 * 1024
        try:
            uc.mem_map(page_addr, page_size)
            return True
        except unicorn.UcError:
            return False

    def hook_mmio_read(self, uc, access, address, size, value, user_data):
        self.unsupported("mmio_read", address=address, size=size)
        return 0

    def hook_mmio_write(self, uc, access, address, size, value, user_data):
        self.unsupported("mmio_write", address=address, size=size, value=value)

    def hook_code_execution(self, uc, address, size, user_data):
        if address in self.stubs:
            name, handler = self.stubs[address]
            self.unsupported("hle_service", symbol=name)
            handler(self, uc)
            lr = uc.reg_read(UC_ARM_REG_LR)
            uc.reg_write(UC_ARM_REG_PC, lr)

    def register_hle_stub(self, name, handler):
        if name in self.stub_by_name:
            addr = self.stub_by_name[name]
            self.stubs[addr] = (name, handler)
            return addr

        addr = self.next_stub_addr
        self.next_stub_addr += 4
        self.mu.mem_write(addr, b'\x1e\xff\x2f\xe1')  # bx lr
        self.stubs[addr] = (name, handler)
        self.stub_by_name[name] = addr
        self.symbols[name] = addr
        return addr

    def register_default_stub(self, name):
        self.unsupported("unresolved_symbol", symbol=name)
        def default_handler(emu, uc):
            uc.reg_write(UC_ARM_REG_R0, 0)
        return self.register_hle_stub(name, default_handler)

    def register_core_hle_stubs(self):
        print("[*] Registrujem HLE sistemske i libc/C++ funkcije...")
        
        def hle_malloc(emu, uc):
            size = uc.reg_read(UC_ARM_REG_R0)
            aligned_size = (size + 7) & ~7
            ptr = emu.heap_ptr
            emu.heap_ptr += aligned_size
            uc.reg_write(UC_ARM_REG_R0, ptr)

        def hle_calloc(emu, uc):
            nmemb = uc.reg_read(UC_ARM_REG_R0)
            size = uc.reg_read(UC_ARM_REG_R1)
            total = (nmemb * size + 7) & ~7
            ptr = emu.heap_ptr
            emu.heap_ptr += total
            emu.mu.mem_write(ptr, b'\x00' * total)
            uc.reg_write(UC_ARM_REG_R0, ptr)

        def hle_free(emu, uc):
            pass

        def hle_new(emu, uc):
            size = uc.reg_read(UC_ARM_REG_R0)
            aligned_size = (size + 7) & ~7
            ptr = emu.heap_ptr
            emu.heap_ptr += aligned_size
            uc.reg_write(UC_ARM_REG_R0, ptr)

        def hle_printf(emu, uc):
            uc.reg_write(UC_ARM_REG_R0, 0)

        def hle_stella_log(emu, uc):
            uc.reg_write(UC_ARM_REG_R0, 0)

        def hle_open(emu, uc):
            path_ptr = uc.reg_read(UC_ARM_REG_R0)
            raw_path = emu.read_string(path_ptr)
            
            target_path = None
            if raw_path.startswith('/usr/share/app/'):
                rel = raw_path[len('/usr/share/app/'):]
                target_path = os.path.join(APP_DIR, rel)
            elif raw_path.startswith('/share/app/'):
                rel = raw_path[len('/share/app/'):]
                target_path = os.path.join(APP_DIR, rel)
            elif os.path.exists(raw_path):
                target_path = raw_path
            
            if target_path and os.path.exists(target_path):
                fd = emu.next_fd
                emu.next_fd += 1
                emu.open_files[fd] = open(target_path, 'rb')
                uc.reg_write(UC_ARM_REG_R0, fd)
            else:
                uc.reg_write(UC_ARM_REG_R0, 0xFFFFFFFF)

        def hle_read(emu, uc):
            fd = uc.reg_read(UC_ARM_REG_R0)
            buf = uc.reg_read(UC_ARM_REG_R1)
            count = uc.reg_read(UC_ARM_REG_R2)
            if fd in emu.open_files:
                data = emu.open_files[fd].read(count)
                emu.mu.mem_write(buf, data)
                uc.reg_write(UC_ARM_REG_R0, len(data))
            else:
                uc.reg_write(UC_ARM_REG_R0, 0)

        def hle_lseek(emu, uc):
            fd = uc.reg_read(UC_ARM_REG_R0)
            offset = uc.reg_read(UC_ARM_REG_R1)
            whence = uc.reg_read(UC_ARM_REG_R2)
            if fd in emu.open_files:
                emu.open_files[fd].seek(offset, whence)
                pos = emu.open_files[fd].tell()
                uc.reg_write(UC_ARM_REG_R0, pos)
            else:
                uc.reg_write(UC_ARM_REG_R0, 0xFFFFFFFF)

        def hle_close(emu, uc):
            fd = uc.reg_read(UC_ARM_REG_R0)
            if fd in emu.open_files:
                emu.open_files[fd].close()
                del emu.open_files[fd]
            uc.reg_write(UC_ARM_REG_R0, 0)

        def hle_mmap(emu, uc):
            length = uc.reg_read(UC_ARM_REG_R1)
            sp = uc.reg_read(UC_ARM_REG_SP)
            try:
                fd = struct.unpack('<I', emu.mu.mem_read(sp, 4))[0]
                offset = struct.unpack('<I', emu.mu.mem_read(sp + 4, 4))[0]
            except Exception:
                fd = 0; offset = 0
            
            aligned_len = (length + 0xFFFF) & ~0xFFFF
            mmap_ptr = emu.heap_ptr
            emu.heap_ptr += aligned_len
            emu.mu.mem_map(mmap_ptr, aligned_len)
            
            if fd in emu.open_files:
                emu.open_files[fd].seek(offset)
                data = emu.open_files[fd].read(length)
                emu.mu.mem_write(mmap_ptr, data)
            uc.reg_write(UC_ARM_REG_R0, mmap_ptr)

        def hle_ioctl(emu, uc):
            uc.reg_write(UC_ARM_REG_R0, 0)

        def hle_pthread_mutex(emu, uc):
            uc.reg_write(UC_ARM_REG_R0, 0)

        def hle_ux_log(emu, uc):
            uc.reg_write(UC_ARM_REG_R0, 0)

        # Register standard memory & C++ allocation
        self.register_hle_stub("malloc", hle_malloc)
        self.register_hle_stub("calloc", hle_calloc)
        self.register_hle_stub("free", hle_free)
        self.register_hle_stub("_Znwj", hle_new)
        self.register_hle_stub("_Znaj", hle_new)
        self.register_hle_stub("_ZdlPv", hle_free)
        self.register_hle_stub("_ZdaPv", hle_free)

        # Logging
        self.register_hle_stub("printf", hle_printf)
        self.register_hle_stub("stella_print_log", hle_stella_log)
        self.register_hle_stub("puts", hle_printf)
        self.register_hle_stub("_ZN2ux4core3Log5writeEjPKcz", hle_ux_log)

        # VFS & OS
        self.register_hle_stub("open", hle_open)
        self.register_hle_stub("open64", hle_open)
        self.register_hle_stub("read", hle_read)
        self.register_hle_stub("lseek", hle_lseek)
        self.register_hle_stub("lseek64", hle_lseek)
        self.register_hle_stub("close", hle_close)
        def hle_backup_read(emu, uc):
            tag = uc.reg_read(UC_ARM_REG_R0)
            buf = uc.reg_read(UC_ARM_REG_R1)
            size = uc.reg_read(UC_ARM_REG_R2)
            val = emu.backup_nvram.get(tag, b'\x00' * (size if size > 0 else 4))
            emu.mu.mem_write(buf, val[:size])
            uc.reg_write(UC_ARM_REG_R0, 0) # 0 = Success

        def hle_backup_read_4Byte(emu, uc):
            tag = uc.reg_read(UC_ARM_REG_R0)
            buf = uc.reg_read(UC_ARM_REG_R1)
            val = emu.backup_nvram.get(tag, struct.pack('<I', 0))
            emu.mu.mem_write(buf, val[:4])
            uc.reg_write(UC_ARM_REG_R0, 0)

        def hle_backup_write(emu, uc):
            tag = uc.reg_read(UC_ARM_REG_R0)
            buf = uc.reg_read(UC_ARM_REG_R1)
            size = uc.reg_read(UC_ARM_REG_R2)
            data = emu.mu.mem_read(buf, size)
            emu.backup_nvram[tag] = bytes(data)
            print(f"[SONY BACKUP NVRAM] Masinski kod upisao tag 0x{tag:04x} (velicina: {size}B)")
            uc.reg_write(UC_ARM_REG_R0, 0)

        self.register_hle_stub("mmap", hle_mmap)
        self.register_hle_stub("mmap2", hle_mmap)
        self.register_hle_stub("mcmn_mmap_do_mmap", hle_mmap)
        self.register_hle_stub("Backup_read", hle_backup_read)
        self.register_hle_stub("Backup_read_4Byte", hle_backup_read_4Byte)
        self.register_hle_stub("Backup_write", hle_backup_write)
        self.register_hle_stub("ioctl", hle_ioctl)
        self.register_hle_stub("pthread_mutex_init", hle_pthread_mutex)
        self.register_hle_stub("pthread_mutex_lock", hle_pthread_mutex)
        self.register_hle_stub("pthread_mutex_unlock", hle_pthread_mutex)
        self.register_hle_stub("pthread_mutex_destroy", hle_pthread_mutex)
        self.register_hle_stub("__cxa_atexit", lambda emu, uc: uc.reg_write(UC_ARM_REG_R0, 0))
        self.register_hle_stub("__cxa_pure_virtual", lambda emu, uc: None)
        self.register_hle_stub("__cxa_guard_acquire", lambda emu, uc: uc.reg_write(UC_ARM_REG_R0, 1))
        self.register_hle_stub("__cxa_guard_release", lambda emu, uc: None)

    def backup_write_param(self, tag, val_int, size=4):
        data = struct.pack('<I', val_int) if size == 4 else bytes([val_int])
        self.backup_nvram[tag] = data
        print(f"[SONY BACKUP NVRAM] Azurirana postavka: tag=0x{tag:04x}, vrednost={val_int}")

    def read_string(self, addr, max_len=256):
        try:
            data = self.mu.mem_read(addr, max_len)
            null_idx = data.find(b'\x00')
            if null_idx != -1:
                data = data[:null_idx]
            return data.decode('latin1', 'ignore')
        except Exception:
            return ""

    def load_elf_module(self, filepath, base_addr):
        filename = os.path.basename(filepath)
        print(f"[*] Ucitavanje ELF modula: {filename} na baznu adresu 0x{base_addr:08x}...")
        
        with open(filepath, 'rb') as f:
            elf = ELFFile(f)
            if elf.elfclass != 32 or not elf.little_endian or elf['e_machine'] != 'EM_ARM':
                raise ValueError("Research loader requires little-endian ELF32 ARM")
            if elf['e_type'] not in ('ET_DYN', 'ET_EXEC'):
                raise ValueError("Research loader does not load relocatable kernel modules")
            if any(segment['p_type'] == 'PT_TLS' for segment in elf.iter_segments()):
                self.unsupported("elf_tls", module=filename)
            segments = [seg for seg in elf.iter_segments() if seg['p_type'] == 'PT_LOAD']
            mapped_addr, total_size = load_span(segments, base_addr)
            saved_symbols = self.symbols.copy()
            saved_stubs = self.stubs.copy()
            saved_stub_names = self.stub_by_name.copy()
            saved_next_stub = self.next_stub_addr
            self.mu.mem_map(mapped_addr, total_size)
            try:

                for seg in elf.iter_segments():
                    if seg['p_type'] == 'PT_LOAD':
                        vaddr = seg['p_vaddr']
                        data = seg.data()
                        target_addr = base_addr + vaddr
                        self.mu.mem_write(target_addr, data)
                
                dynsym = elf.get_section_by_name('.dynsym')
                if dynsym:
                    for sym in dynsym.iter_symbols():
                        name = sym.name
                        if name and sym['st_shndx'] != 'SHN_UNDEF':
                            self.symbols[name] = (sym['st_value'] if sym['st_shndx'] == 'SHN_ABS'
                                                  else base_addr + sym['st_value'])

                self.apply_relocations(elf, base_addr, dynsym)
                self.loaded_modules[filename] = {'base': base_addr, 'mapped_address': mapped_addr,
                                                 'size': total_size, 'entry': base_addr + elf['e_entry'],
                                                 'initializers_executed': False}
                print(f"[+] {filename}: mapped and supported relocations applied; initializers not executed.")

            except Exception:
                self.mu.mem_unmap(mapped_addr, total_size)
                self.symbols = saved_symbols
                self.stubs = saved_stubs
                self.stub_by_name = saved_stub_names
                self.next_stub_addr = saved_next_stub
                raise

    def apply_relocations(self, elf, base_addr, dynsym):
        from elftools.elf.relocation import RelocationSection
        for section in elf.iter_sections():
            if isinstance(section, RelocationSection):
                allowed = ({R_ARM_RELATIVE, R_ARM_GLOB_DAT, R_ARM_ABS32}
                           if section.name == ".rel.dyn" else
                           {R_ARM_JUMP_SLOT} if section.name == ".rel.plt" else set())
                for relocation in section.iter_relocations():
                    if relocation["r_info_type"] not in allowed:
                        self.unsupported("unsupported_relocation", section=section.name,
                                         relocation_type=relocation["r_info_type"],
                                         offset=relocation["r_offset"])
        rel_dyn = elf.get_section_by_name('.rel.dyn')
        if rel_dyn:
            for rel in rel_dyn.iter_relocations():
                rel_type = rel['r_info_type']
                offset = rel['r_offset']
                target_addr = base_addr + offset

                if rel_type == R_ARM_RELATIVE:
                    val = struct.unpack('<I', self.mu.mem_read(target_addr, 4))[0]
                    new_val = (val + base_addr) & 0xFFFFFFFF
                    self.mu.mem_write(target_addr, struct.pack('<I', new_val))
                elif rel_type in (R_ARM_GLOB_DAT, R_ARM_ABS32):
                    sym_idx = rel['r_info_sym']
                    sym = dynsym.get_symbol(sym_idx)
                    sym_name = sym.name
                    if sym_name in self.symbols:
                        s_addr = self.symbols[sym_name]
                    else:
                        s_addr = self.register_default_stub(sym_name)
                    addend = struct.unpack('<I', self.mu.mem_read(target_addr, 4))[0]
                    relocated = symbol_relocation(s_addr, addend, sym['st_info']['type'] == 'STT_FUNC')
                    self.mu.mem_write(target_addr, struct.pack('<I', relocated))

        rel_plt = elf.get_section_by_name('.rel.plt')
        if rel_plt:
            for rel in rel_plt.iter_relocations():
                rel_type = rel['r_info_type']
                offset = rel['r_offset']
                target_addr = base_addr + offset
                
                if rel_type == R_ARM_JUMP_SLOT:
                    sym_idx = rel['r_info_sym']
                    sym = dynsym.get_symbol(sym_idx)
                    sym_name = sym.name
                    if sym_name in self.symbols:
                        s_addr = self.symbols[sym_name]
                    else:
                        s_addr = self.register_default_stub(sym_name)
                    self.mu.mem_write(target_addr, struct.pack('<I', s_addr))

    def setup_sony_subsystems(self):
        self.unsupported("mock_sony_subsystems")
        print("[*] Inicijalizacija Sony UX / Libra podsistema i model wrapper-a...")
        
        # 1. Mock Layer structure for WidgetSystem
        dummy_stub = self.register_hle_stub('UX_DummyMethod', lambda e, u: u.reg_write(UC_ARM_REG_R0, 0))
        vtable = self.heap_ptr; self.heap_ptr += 512
        for off in range(0, 512, 4):
            self.mu.mem_write(vtable + off, struct.pack('<I', dummy_stub))

        mock_subobj = self.heap_ptr; self.heap_ptr += 128
        self.mu.mem_write(mock_subobj, struct.pack('<I', vtable))

        mock_node = self.heap_ptr; self.heap_ptr += 128
        self.mu.mem_write(mock_node, struct.pack('<I', vtable))

        self.mock_layer = self.heap_ptr; self.heap_ptr += 256
        self.mu.mem_write(self.mock_layer, struct.pack('<I', vtable))
        self.mu.mem_write(self.mock_layer + 0x18, struct.pack('<I', mock_subobj))
        self.mu.mem_write(self.mock_layer + 0x34, struct.pack('<I', mock_node))

        # Hook WidgetSystem::getLayer
        sym_get_layer = '_ZNK2ux6wgtsys12WidgetSystem8getLayerERKNS_4core2IDE'
        if sym_get_layer in self.symbols:
            addr_gl = self.symbols[sym_get_layer] & ~1
            def hook_get_layer(uc, address, size, user_data):
                uc.reg_write(UC_ARM_REG_R0, self.mock_layer)
                lr = uc.reg_read(UC_ARM_REG_LR)
                uc.reg_write(UC_ARM_REG_PC, lr)
            self.mu.hook_add(unicorn.UC_HOOK_CODE, hook_get_layer, begin=addr_gl, end=addr_gl+2)

        # 2. ViewManager singleton & getModelInfo hook
        mock_vm = self.heap_ptr; self.heap_ptr += 128
        self.mu.mem_write(0x31424eac, struct.pack('<I', mock_vm)) # pViewManager in libObj.so

        sym_vm_get = '_ZN11ViewManager12getModelInfoEiiP9ParamListPKS0_'
        if sym_vm_get in self.symbols:
            addr_vm = self.symbols[sym_vm_get] & ~1
            def hook_vm_get(uc, address, size, user_data):
                uc.reg_write(UC_ARM_REG_R0, 1) # Return success status
                lr = uc.reg_read(UC_ARM_REG_LR)
                uc.reg_write(UC_ARM_REG_PC, lr)
            self.mu.hook_add(unicorn.UC_HOOK_CODE, hook_vm_get, begin=addr_vm, end=addr_vm+2)

        # 3. ParamList::get hook feeding simulated camera state
        self.update_param_val_nodes()
        sym_prm_get = '_ZNK9ParamList3getEmm'
        if sym_prm_get in self.symbols:
            addr_prm = self.symbols[sym_prm_get] & ~1
            def hook_prm_get(uc, address, size, user_data):
                tag = uc.reg_read(UC_ARM_REG_R1)
                default_val = uc.reg_read(UC_ARM_REG_R2)
                ret_ptr = self.param_val_nodes.get(tag, None)
                if not ret_ptr:
                    ret_ptr = self.heap_ptr; self.heap_ptr += 32
                    self.mu.mem_write(ret_ptr + 0x10, struct.pack('<I', default_val))
                uc.reg_write(UC_ARM_REG_R0, ret_ptr)
                lr = uc.reg_read(UC_ARM_REG_LR)
                uc.reg_write(UC_ARM_REG_PC, lr)
            self.mu.hook_add(unicorn.UC_HOOK_CODE, hook_prm_get, begin=addr_prm, end=addr_prm+2)

        print("[+] Sony UX podsustav i Model ParamList bridge uspesno aktivirani!")

    def update_param_val_nodes(self):
        tags = {
            0x27f: 1,                                   # Exposure Valid
            0x1b8: self.camera_state["shutter_num"],     # Shutter Num (1)
            0x1b9: self.camera_state["shutter_den"],     # Shutter Den (60 -> 1/60)
            0x1ba: self.camera_state["aperture_val"],    # Aperture Val (18 -> F1.8)
            0x1bb: self.camera_state["aperture_div"],    # Aperture Div (10)
            0x1bc: self.camera_state["iso_mode"],        # ISO Mode (0 = AUTO)
            0x1bd: 0,                                   # Exposure Comp (+-0.0)
            0x386: 1,                                   # Trinity Shoot Status
            0x2e4: 2 if self.camera_state["focus_mode"] == "AF-C" else (1 if self.camera_state["focus_mode"] == "AF-S" else 0),
            0x2e5: 1,                                   # Drive Mode (Single)
            0x320: self.camera_state["picture_profile"], # Picture Profile (PP2)
            0x350: self.camera_state["card_remaining"],  # Remaining shots (4882)
            0x380: self.camera_state["battery_pct"],     # Battery (100)
        }
        for tag, val in tags.items():
            if tag not in self.param_val_nodes:
                node = self.heap_ptr; self.heap_ptr += 32
                self.param_val_nodes[tag] = node
            node = self.param_val_nodes[tag]
            self.mu.mem_write(node + 0x10, struct.pack('<I', val))

    def instantiate_all_screens(self):
        print("\n[*] Instanciram sve glavne ekrane kamere u ARMv7 masinskom kodu...")
        screens_to_load = [
            ("LIVE_VIEW", "ViewStlrecToInstance"),
            ("MENU", "ViewSettingMenuToInstance"),
            ("QUICK_NAVI", "ViewShootingInfoDispToInstance"),
            ("PLAYBACK", "ViewSinglePbToInstance")
        ]
        sym_onload = '_ZN8ViewBase6onLoadEv'
        addr_onload = self.symbols.get(sym_onload, None)

        for screen_key, factory_name in screens_to_load:
            if factory_name in self.symbols:
                addr_fac = self.symbols[factory_name]
                inst = self.call_function(addr_fac, 0, 0, is_thumb=True)
                self.screen_instances[screen_key] = inst
                print(f"  [+] Ekran '{screen_key}' instanciran na 0x{inst:08x}")
                if addr_onload and screen_key == "LIVE_VIEW":
                    self.call_function(addr_onload, inst, is_thumb=True)
                    print(f"      - ViewBase::onLoad() izvrsen za {screen_key}")

        return True

    def send_hardware_key(self, key_code, action=0):
        self.unsupported("host_navigation", key_code=key_code, action=action)
        """
        Dispatches hardware key events into the active Sony camera screen.
        Handles physical buttons: MENU, DISP, FN, PLAY, D-Pad, Wheel Dials, Shutter.
        """
        key_names = {
            KEY_TACT_MENU: "MENU",
            KEY_TACT_DISP: "DISP",
            KEY_TACT_FN: "Fn",
            KEY_TACT_PLAY: "PLAYBACK",
            KEY_TACT_UP: "UP",
            KEY_TACT_DOWN: "DOWN",
            KEY_TACT_LEFT: "LEFT",
            KEY_TACT_RIGHT: "RIGHT",
            KEY_TACT_ENTER: "ENTER",
            KEY_TACT_CUSTOM: "C1",
            KEY_REMOTE_S1: "SHUTTER_S1 (Half-press)",
            KEY_REMOTE_S2: "SHUTTER_S2 (Full-press)",
            KEY_OTHER_WHEEL_LEFT: "WHEEL_LEFT (CCW)",
            KEY_OTHER_WHEEL_RIGHT: "WHEEL_RIGHT (CW)",
        }
        kname = key_names.get(key_code, f"0x{key_code:x}")
        print(f"[SONY HARDWARE INPUT] Pritisnuta fizicka tipka: {kname} (kod: 0x{key_code:x})")

        # 1. Screen Switchers (MENU, DISP, PLAY, FN)
        if key_code == KEY_TACT_MENU:
            if self.menu_sub_active:
                self.menu_sub_active = False
                print("  -> Zatvoren podizbor menija (Nazad na glavni meni)")
            elif self.active_screen == "MENU":
                self.active_screen = "LIVE_VIEW"
                print("  -> Ekran promenjen na: LIVE_VIEW")
            else:
                self.active_screen = "MENU"
                self.menu_sub_active = False
                print("  -> Ekran promenjen na: MENU")
            return self.render_active_screen()

        elif key_code == KEY_TACT_DISP:
            if self.active_screen == "LIVE_VIEW":
                self.liveview_disp_mode = (self.liveview_disp_mode + 1) % 4
                modes = ["Graphic Display (Merači)", "All Info (Sve informacije)", "No Disp Info (Čist prikaz)", "Histogram Overlay"]
                print(f"  -> DISP u Live View: {modes[self.liveview_disp_mode]}")
            elif self.active_screen == "QUICK_NAVI":
                self.active_screen = "LIVE_VIEW"
                print("  -> Ekran promenjen na: LIVE_VIEW")
            elif self.active_screen == "PLAYBACK":
                self.playback_disp_mode = (self.playback_disp_mode + 1) % 3
                modes = ["Detaljni prikaz (Histogram + EXIF)", "Minimalni prikaz", "Čista fotografija"]
                print(f"  -> DISP u Reprodukciji: {modes[self.playback_disp_mode]}")
            return self.render_active_screen()

        elif key_code == KEY_TACT_PLAY:
            self.active_screen = "LIVE_VIEW" if self.active_screen == "PLAYBACK" else "PLAYBACK"
            print(f"  -> Ekran promenjen na: {self.active_screen}")
            return self.render_active_screen()

        elif key_code == KEY_TACT_FN:
            self.active_screen = "LIVE_VIEW" if self.active_screen == "FN_MENU" else "FN_MENU"
            print(f"  -> Ekran promenjen na: {self.active_screen}")
            return self.render_active_screen()

        # 2. Shutter Release & Focus Locking
        elif key_code == KEY_REMOTE_S1:
            self.af_locked = not self.af_locked
            status = "ZAKLJUČAN (Zeleni AF okvir)" if self.af_locked else "OTKLJUČAN"
            print(f"  -> Okidač polu-pritisak (S1): Fokus {status}")
            return self.render_active_screen()

        elif key_code == KEY_REMOTE_S2:
            self.camera_state["card_remaining"] = max(0, self.camera_state["card_remaining"] - 1)
            new_id = f"100-{43 + len(self.playback_photos) - 3:04d}"
            new_photo = {
                "id": new_id,
                "date": "2026/10/18 09:35",
                "format": self.camera_state["quality"],
                "shutter": f"1/{self.camera_state['shutter_den']}",
                "aperture": f"F{self.camera_state['aperture_val']/10:.1f}",
                "iso": "ISO AUTO" if self.camera_state["iso_mode"] == 0 else f"ISO {self.camera_state['iso_val']}",
                "exp": self.camera_state["exp_comp"],
                "lens": "Sony E 35mm F1.8 OSS",
                "profile": f"PP{self.camera_state['picture_profile']}",
                "bg_color": (32, 45, 36),
                "title": f"Captured Shot ({self.camera_state['quality']})"
            }
            self.playback_photos.insert(0, new_photo)
            self.shutter_flash = True
            print(f"  [OKIDAČ S2] Snimljena fotografija {new_id}! Preostalo na kartici: {self.camera_state['card_remaining']}")
            return self.render_active_screen()

        # 3. Contextual Navigation per screen
        if self.active_screen == "MENU":
            item_info = self.menu_options_map.get((self.menu_tab, self.menu_item), None)
            if self.menu_sub_active:
                if key_code == KEY_TACT_UP:
                    if item_info:
                        self.menu_sub_index = max(0, self.menu_sub_index - 1)
                elif key_code == KEY_TACT_DOWN:
                    if item_info:
                        self.menu_sub_index = min(len(item_info["options"]) - 1, self.menu_sub_index + 1)
                elif key_code == KEY_TACT_ENTER:
                    if item_info:
                        selected_val = item_info["options"][self.menu_sub_index]
                        key_name = item_info["key"]
                        self.camera_state[key_name] = selected_val
                        self.backup_write_param(item_info["tag"], self.menu_sub_index)
                        self.update_param_val_nodes()
                        print(f"  [MENU ZAPIS] Potvrđena postavka '{item_info['name']}': {selected_val} (NVRAM Backup)")
                    self.menu_sub_active = False
                elif key_code in (KEY_TACT_LEFT, KEY_TACT_MENU):
                    self.menu_sub_active = False
            else:
                if key_code == KEY_TACT_LEFT:
                    self.menu_tab = max(1, self.menu_tab - 1)
                elif key_code == KEY_TACT_RIGHT:
                    self.menu_tab = min(6, self.menu_tab + 1)
                elif key_code == KEY_TACT_UP:
                    self.menu_item = max(0, self.menu_item - 1)
                elif key_code == KEY_TACT_DOWN:
                    self.menu_item = min(5, self.menu_item + 1)
                elif key_code == KEY_TACT_ENTER:
                    if item_info and len(item_info["options"]) > 1:
                        self.menu_sub_active = True
                        cur_val = self.camera_state.get(item_info["key"], None)
                        if cur_val in item_info["options"]:
                            self.menu_sub_index = item_info["options"].index(cur_val)
                        else:
                            self.menu_sub_index = 0
                        print(f"  -> Otvoren podizbor za '{item_info['name']}' ({len(item_info['options'])} opcija)")
                    else:
                        print(f"  -> Izvršena akcija: '{item_info['name'] if item_info else 'Stavka'}'")

        elif self.active_screen == "FN_MENU":
            if key_code == KEY_TACT_UP:
                self.fn_index = (self.fn_index - 6) % 12
            elif key_code == KEY_TACT_DOWN:
                self.fn_index = (self.fn_index + 6) % 12
            elif key_code == KEY_TACT_LEFT:
                row = self.fn_index // 6
                col = ((self.fn_index % 6) - 1) % 6
                self.fn_index = row * 6 + col
            elif key_code == KEY_TACT_RIGHT:
                row = self.fn_index // 6
                col = ((self.fn_index % 6) + 1) % 6
                self.fn_index = row * 6 + col
            elif key_code in (KEY_TACT_ENTER, KEY_OTHER_WHEEL_LEFT, KEY_OTHER_WHEEL_RIGHT):
                direction = -1 if key_code == KEY_OTHER_WHEEL_LEFT else 1
                self.cycle_fn_parameter(self.fn_index, direction)

        elif self.active_screen == "PLAYBACK":
            if key_code in (KEY_TACT_LEFT, KEY_OTHER_WHEEL_LEFT):
                self.playback_index = (self.playback_index + 1) % len(self.playback_photos)
                print(f"  -> Reprodukcija: Slika {self.playback_photos[self.playback_index]['id']}")
            elif key_code in (KEY_TACT_RIGHT, KEY_OTHER_WHEEL_RIGHT):
                self.playback_index = (self.playback_index - 1) % len(self.playback_photos)
                print(f"  -> Reprodukcija: Slika {self.playback_photos[self.playback_index]['id']}")
            elif key_code in (KEY_TACT_UP, KEY_TACT_DOWN):
                self.playback_grid_view = not self.playback_grid_view
                print(f"  -> Prikaz reprodukcije: {'9-Grid Indeks' if self.playback_grid_view else 'Jedna fotografija'}")

        elif self.active_screen in ("LIVE_VIEW", "QUICK_NAVI"):
            if key_code in (KEY_TACT_LEFT, KEY_OTHER_WHEEL_LEFT):
                speeds = [15, 30, 60, 125, 250, 500, 1000, 2000, 4000]
                curr = self.camera_state["shutter_den"]
                idx = (speeds.index(curr) - 1) % len(speeds) if curr in speeds else 2
                self.camera_state["shutter_den"] = speeds[idx]
                self.update_param_val_nodes()
                print(f"  -> Brzina zatvarača podešena na: 1/{self.camera_state['shutter_den']}")

            elif key_code in (KEY_TACT_RIGHT, KEY_OTHER_WHEEL_RIGHT):
                fstops = [14, 18, 28, 40, 56, 80, 110, 160, 220]
                curr = self.camera_state["aperture_val"]
                idx = (fstops.index(curr) + 1) % len(fstops) if curr in fstops else 1
                self.camera_state["aperture_val"] = fstops[idx]
                self.update_param_val_nodes()
                print(f"  -> Otvor blende podešen na: F{self.camera_state['aperture_val']/10:.1f}")

            elif key_code == KEY_TACT_DOWN:
                if self.camera_state["iso_mode"] == 0:
                    self.camera_state["iso_mode"] = 1
                    self.camera_state["iso_val"] = 100
                else:
                    isos = [100, 200, 400, 800, 1600, 3200, 6400, 12800]
                    curr = self.camera_state["iso_val"]
                    if curr in isos and isos.index(curr) < len(isos) - 1:
                        self.camera_state["iso_val"] = isos[isos.index(curr) + 1]
                    else:
                        self.camera_state["iso_mode"] = 0
                self.update_param_val_nodes()
                iso_disp = "AUTO" if self.camera_state["iso_mode"] == 0 else str(self.camera_state["iso_val"])
                print(f"  -> ISO osetljivost: {iso_disp}")

            elif key_code == KEY_TACT_CUSTOM:
                modes = ["AF-C", "AF-S", "MF"]
                curr = self.camera_state["focus_mode"]
                idx = (modes.index(curr) + 1) % len(modes)
                self.camera_state["focus_mode"] = modes[idx]
                self.update_param_val_nodes()
                print(f"  -> Focus mod (C1): {modes[idx]}")

        return self.render_active_screen()

    def cycle_fn_parameter(self, idx, direction=1):
        """Cycles parameters directly from the 12-block Fn menu"""
        if idx == 0:
            modes = ["Single", "Continuous: Hi", "Continuous: Mid", "Continuous: Lo", "Self-timer 10s"]
            curr = self.camera_state.get("drive_mode", "Single")
            cur_i = modes.index(curr) if curr in modes else 0
            self.camera_state["drive_mode"] = modes[(cur_i + direction) % len(modes)]
            self.backup_write_param(0x010d, (cur_i + direction) % len(modes))
            print(f"  [Fn] Drive Mode: {self.camera_state['drive_mode']}")
        elif idx == 1:
            modes = ["AF-C", "AF-S", "MF", "DMF", "AF-A"]
            curr = self.camera_state.get("focus_mode", "AF-C")
            cur_i = modes.index(curr) if curr in modes else 0
            self.camera_state["focus_mode"] = modes[(cur_i + direction) % len(modes)]
            self.update_param_val_nodes()
            print(f"  [Fn] Focus Mode: {self.camera_state['focus_mode']}")
        elif idx == 2:
            areas = ["Wide", "Zone", "Center", "Spot: S", "Tracking: Wide"]
            curr = self.camera_state.get("focus_area", "Wide")
            cur_i = areas.index(curr) if curr in areas else 0
            self.camera_state["focus_area"] = areas[(cur_i + direction) % len(areas)]
            print(f"  [Fn] Focus Area: {self.camera_state['focus_area']}")
        elif idx == 3:
            comps = ["-2.0", "-1.0", "±0.0", "+1.0", "+2.0"]
            curr = self.camera_state.get("exp_comp", "±0.0")
            cur_i = comps.index(curr) if curr in comps else 2
            self.camera_state["exp_comp"] = comps[(cur_i + direction) % len(comps)]
            print(f"  [Fn] Exp Comp: {self.camera_state['exp_comp']}")
        elif idx == 4:
            if self.camera_state["iso_mode"] == 0:
                self.camera_state["iso_mode"] = 1
                self.camera_state["iso_val"] = 100
            else:
                isos = [100, 200, 400, 800, 1600, 3200, 6400, 12800]
                cur = self.camera_state["iso_val"]
                if cur in isos:
                    idx_iso = isos.index(cur)
                    if 0 <= idx_iso + direction < len(isos):
                        self.camera_state["iso_val"] = isos[idx_iso + direction]
                    else:
                        self.camera_state["iso_mode"] = 0
                else:
                    self.camera_state["iso_mode"] = 0
            self.update_param_val_nodes()
            iso_disp = "AUTO" if self.camera_state["iso_mode"] == 0 else str(self.camera_state["iso_val"])
            print(f"  [Fn] ISO: {iso_disp}")
        elif idx == 5:
            modes = ["Multi", "Center", "Spot: Standard"]
            curr = self.camera_state.get("metering", "Multi")
            cur_i = modes.index(curr) if curr in modes else 0
            self.camera_state["metering"] = modes[(cur_i + direction) % len(modes)]
            print(f"  [Fn] Metering: {self.camera_state['metering']}")
        elif idx == 6:
            wbs = ["AWB", "Daylight", "Shade", "Cloudy", "Incandescent", "Flash"]
            curr = self.camera_state.get("white_balance", "AWB")
            cur_i = wbs.index(curr) if curr in wbs else 0
            self.camera_state["white_balance"] = wbs[(cur_i + direction) % len(wbs)]
            print(f"  [Fn] White Balance: {self.camera_state['white_balance']}")
        elif idx == 7:
            dros = ["Off", "D-Range Opt. (Auto)", "Auto HDR"]
            curr = self.camera_state.get("dro_hdr", "Off")
            cur_i = dros.index(curr) if curr in dros else 0
            self.camera_state["dro_hdr"] = dros[(cur_i + direction) % len(dros)]
            print(f"  [Fn] DRO/HDR: {self.camera_state['dro_hdr']}")
        elif idx == 8:
            pps = [0, 1, 2, 3, 4, 5, 6, 7, 8, 10]
            curr = self.camera_state["picture_profile"]
            cur_i = pps.index(curr) if curr in pps else 2
            self.camera_state["picture_profile"] = pps[(cur_i + direction) % len(pps)]
            self.update_param_val_nodes()
            print(f"  [Fn] Picture Profile: PP{self.camera_state['picture_profile']}")
        elif idx == 9:
            self.camera_state["steadyshot"] = "Off" if self.camera_state["steadyshot"] == "Ukljuceno" else "Ukljuceno"
            print(f"  [Fn] SteadyShot: {self.camera_state['steadyshot']}")
        elif idx == 10:
            self.camera_state["silent_shutter"] = "Ukljuceno" if self.camera_state["silent_shutter"] == "Iskljuceno" else "Iskljuceno"
            print(f"  [Fn] Silent Shoot: {self.camera_state['silent_shutter']}")
        elif idx == 11:
            peaking = ["Off", "Low/Whi", "Mid/Yel", "High/Red"]
            curr = self.camera_state.get("peaking", "Mid/Yel")
            cur_i = peaking.index(curr) if curr in peaking else 2
            self.camera_state["peaking"] = peaking[(cur_i + direction) % len(peaking)]
            print(f"  [Fn] Peaking: {self.camera_state['peaking']}")

    def call_function(self, func_addr, *args, is_thumb=False,
                      timeout_us=5000000, instruction_budget=1000000):
        if timeout_us <= 0 or instruction_budget <= 0:
            raise ValueError("Execution limits must be positive")
        regs = [UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3]
        for reg, arg in zip(regs, args[:4]):
            self.mu.reg_write(reg, arg)
        exit_addr = HLE_STUB_BASE + 4
        self.mu.reg_write(UC_ARM_REG_LR, exit_addr)
        pc = (func_addr | 1) if is_thumb else (func_addr & ~1)
        self.mu.reg_write(UC_ARM_REG_PC, pc)
        report = {"entry": pc, "status": "running", "instruction_budget": instruction_budget,
                  "timeout_us": timeout_us}
        self.last_execution = report
        event_start = len(self.audit_events)
        try:
            self.mu.emu_start(pc, exit_addr, timeout=timeout_us, count=instruction_budget)
            stopped_pc = self.mu.reg_read(UC_ARM_REG_PC)
            if stopped_pc == exit_addr:
                report["status"] = "returned"
                report["return_value"] = self.mu.reg_read(UC_ARM_REG_R0)
                return report["return_value"]
            report["status"] = ("timeout" if self.mu.query(unicorn.UC_QUERY_TIMEOUT)
                                else "instruction_budget_exhausted")
            return None
        except UnsupportedBehavior as error:
            report.update(status="unsupported", error=str(error))
            raise
        except unicorn.UcError as error:
            if self.mode == "strict" and len(self.audit_events) > event_start:
                report.update(status="unsupported", error=str(error))
                raise UnsupportedBehavior(json.dumps(self.audit_events[-1])) from error
            report.update(status="fault", error=str(error))
            return None
        finally:
            report["pc"] = self.mu.reg_read(UC_ARM_REG_PC)

    def render_active_screen(self):
        self.unsupported("host_rendering", renderer="render_active_screen")
        if self.active_screen == "LIVE_VIEW":
            return self.render_display_framebuffer()
        elif self.active_screen == "MENU":
            return self.render_menu_framebuffer()
        elif self.active_screen == "QUICK_NAVI":
            return self.render_quick_navi_framebuffer()
        elif self.active_screen == "PLAYBACK":
            return self.render_playback_framebuffer()
        elif self.active_screen == "FN_MENU":
            return self.render_fn_framebuffer()
        return self.render_display_framebuffer()

    def draw_battery(self, draw, x, y, pct=99):
        bw, bh = 34, 18
        draw.rectangle([x, y, x + bw, y + bh], outline="#FFFFFF", width=2)
        draw.rectangle([x + bw, y + 4, x + bw + 3, y + bh - 4], fill="#FFFFFF")
        bars_active = min(4, max(0, int((pct + 12) / 25)))
        for i in range(4):
            bx = x + 4 + i * 7
            if i < bars_active:
                poly = [(bx + 3, y + 3), (bx + 7, y + 3), (bx + 4, y + bh - 3), (bx, y + bh - 3)]
                draw.polygon(poly, fill="#FFFFFF")

    def draw_text_outline(self, draw, pos, text, font, fill_color, outline_color, width=2):
        x, y = pos
        for dx in range(-width, width + 1):
            for dy in range(-width, width + 1):
                if dx*dx + dy*dy <= width*width and (dx != 0 or dy != 0):
                    draw.text((x + dx, y + dy), text, fill=outline_color, font=font)
        draw.text((x, y), text, fill=fill_color, font=font)

    def render_display_framebuffer(self):
        self.unsupported("host_rendering", renderer="render_display_framebuffer")
        w, h = LCD_WIDTH, LCD_HEIGHT
        pillar_w = (w - 810) // 2  # 75 px each

        # Shutter capture flash
        if self.shutter_flash:
            self.shutter_flash = False
            img_flash = Image.new("RGBA", (w, h), (255, 255, 255, 255))
            self.mu.mem_write(FRAMEBUFFER, img_flash.tobytes())
            return img_flash

        # 1. Base 16:9 Canvas with black pillar boxes
        img = Image.new("RGBA", (w, h), (0, 0, 0, 255))

        # 2. Centered 3:2 Sensor Plane
        if self.sensor_3_2_frame:
            img.paste(self.sensor_3_2_frame, (pillar_w, 0))
        elif self.sensor_live_frame:
            sensor_scaled = self.sensor_live_frame.resize((810, 540), Image.Resampling.LANCZOS)
            img.paste(sensor_scaled, (pillar_w, 0))
        else:
            raw_rnd = os.urandom(810 * h)
            pixels = bytearray(810 * h * 4)
            for i in range(810 * h):
                r = raw_rnd[i]
                d = (r & 0x0f) - 8
                d2 = ((r >> 4) & 0x0f) - 8
                pixels[i*4 + 0] = max(0, min(255, 42 + d))
                pixels[i*4 + 1] = max(0, min(255, 46 + d2))
                pixels[i*4 + 2] = max(0, min(255, 35 + d))
                pixels[i*4 + 3] = 255
            noise_img = Image.frombytes('RGBA', (810, h), bytes(pixels))
            img.paste(noise_img, (pillar_w, 0))

        draw = ImageDraw.Draw(img)

        # In Mode 2 (No Disp Info), return clean view with brackets only
        cx, cy = w // 2, h // 2
        bracket_color = "#00FF00" if self.af_locked else "#687078"
        bw, bh, blen = 65, 45, 14
        draw.line([cx - bw, cy - bh, cx - bw + blen, cy - bh], fill=bracket_color, width=2)
        draw.line([cx - bw, cy - bh, cx - bw, cy - bh + blen], fill=bracket_color, width=2)
        draw.line([cx + bw, cy - bh, cx + bw - blen, cy - bh], fill=bracket_color, width=2)
        draw.line([cx + bw, cy - bh, cx + bw, cy - bh + blen], fill=bracket_color, width=2)
        draw.line([cx - bw, cy + bh, cx - bw + blen, cy + bh], fill=bracket_color, width=2)
        draw.line([cx - bw, cy + bh, cx - bw, cy + bh - blen], fill=bracket_color, width=2)
        draw.line([cx + bw, cy + bh, cx + bw - blen, cy + bh], fill=bracket_color, width=2)
        draw.line([cx + bw, cy + bh, cx + bw, cy + bh - blen], fill=bracket_color, width=2)

        if self.liveview_disp_mode == 2:
            self.mu.mem_write(FRAMEBUFFER, img.tobytes())
            return img

        # 3. Rule of thirds subtle grid
        grid_col = (255, 255, 255, 40)
        for gx in [pillar_w + 270, pillar_w + 540]:
            draw.line([gx, 0, gx, h], fill=grid_col, width=1)
        for gy in [180, 360]:
            draw.line([pillar_w, gy, pillar_w + 810, gy], fill=grid_col, width=1)

        # 4. Left Pillar OSD Icons
        lx = 18
        draw.text((lx + 6, 25), "M", fill="#FFFFFF", font=self.f_sans_large)
        draw.text((lx + 4, 85), chr(0xE24F), fill="#FFFFFF", font=self.f_icons_med)
        draw.text((lx + 2, 145), chr(0xE48B), fill="#00FF00" if self.af_locked else "#FFFFFF", font=self.f_icons_med)
        draw.text((lx + 2, 205), chr(0xE5AA), fill="#FFFFFF", font=self.f_icons_med)
        draw.text((lx + 2, 260), chr(0xE4C1), fill="#FFFFFF", font=self.f_icons_med)
        draw.text((lx + 30, 266), "AF", fill="#FFFFFF", font=self.f_sans_tiny)
        draw.text((lx + 30, 280), "ON", fill="#FFFFFF", font=self.f_sans_tiny)
        draw.rectangle([lx + 6, 325, lx + 44, 345], outline="#FFFFFF", width=1)
        draw.text((lx + 10, 327), "PP", fill="#FFFFFF", font=self.f_sans_tiny)
        draw.text((lx + 11, 348), "OFF" if self.camera_state.get("picture_profile", 0) == 0 else f"{self.camera_state['picture_profile']}", fill="#FFFFFF", font=self.f_sans_tiny)

        # 5. Top Bar over sensor
        draw.text((pillar_w + 15, 20), chr(0xE105), fill="#FFFFFF", font=self.f_icons_med)
        draw.text((pillar_w + 50, 22), str(self.camera_state["card_remaining"]), fill="#FFFFFF", font=self.f_sans_bold)
        draw.text((cx - 85, 22), chr(0xE2BE), fill="#FFFFFF", font=self.f_icons_med)
        draw.text((cx + 5, 22), chr(0xE48E), fill="#FFFFFF", font=self.f_icons_med)
        draw.text((cx + 12, 52), chr(0xE02C), fill="#FFFFFF", font=self.f_icons_med)
        self.draw_battery(draw, w - pillar_w - 120, 24, pct=self.camera_state["battery_pct"])
        draw.text((w - pillar_w - 75, 22), f"{self.camera_state['battery_pct']}%", fill="#FFFFFF", font=self.f_sans_large)

        # 6. Right Pillar OSD Icons
        rx = w - pillar_w + 12
        draw.text((rx + 2, 90), chr(0xE59F), fill="#FFFFFF", font=self.f_icons_med)
        draw.text((rx + 4, 155), "AWB", fill="#FFFFFF", font=self.f_sans_bold)
        draw.text((rx + 5, 205), "DRO", fill="#FFFFFF", font=self.f_sans_small)
        draw.text((rx + 2, 222), "AUTO", fill="#FFFFFF", font=self.f_sans_tiny)
        draw.rectangle([rx + 4, 260, rx + 48, 280], outline="#FFFFFF", width=1)
        draw.text((rx + 7, 262), "Std.", fill="#FFFFFF", font=self.f_sans_tiny)
        draw.text((rx + 2, 283), "±0±0±0", fill="#FFFFFF", font=self.f_sans_tiny)
        draw.text((rx + 2, 320), chr(0xE47F), fill="#FFFFFF", font=self.f_icons_med)
        draw.text((rx + 28, 332), "OFF", fill="#FFFFFF", font=self.f_sans_tiny)

        # 7. Mode 3: Live Histogram Overlay Box
        if self.liveview_disp_mode == 3 and self.sensor_img_hist:
            hx, hy = w - pillar_w - 200, h - 170
            draw.rectangle([hx, hy, hx + 190, hy + 90], fill=(8, 8, 8, 220), outline="#555555", width=1)
            draw.text((hx + 6, hy + 4), "HISTOGRAM (RGB)", fill="#AAAAAA", font=self.f_sans_tiny)
            r_b, g_b, b_b = self.sensor_img_hist
            max_c = max(max(r_b[2:253]), max(g_b[2:253]), max(b_b[2:253]), 1)
            for col_i in range(175):
                bi = int(col_i * 255 / 175)
                r_h = min(70, int((r_b[bi] / max_c) * 70))
                g_h = min(70, int((g_b[bi] / max_c) * 70))
                b_h = min(70, int((b_b[bi] / max_c) * 70))
                draw.line([hx + 8 + col_i, hy + 80, hx + 8 + col_i, hy + 80 - r_h], fill="#FF3333", width=1)
                draw.line([hx + 8 + col_i, hy + 80, hx + 8 + col_i, hy + 80 - g_h], fill="#33FF33", width=1)
                draw.line([hx + 8 + col_i, hy + 80, hx + 8 + col_i, hy + 80 - b_h], fill="#3388FF", width=1)

        # 8. Bottom Status Row
        by = 485
        shutter_str = f"1/{self.camera_state['shutter_den']}"
        draw.text((pillar_w + 40, by), shutter_str, fill="#FFFFFF", font=self.f_sans_huge)

        f_stop = self.camera_state['aperture_val'] / self.camera_state['aperture_div']
        draw.text((pillar_w + 210, by), f"F{f_stop:.1f}", fill="#FFFFFF", font=self.f_sans_huge)

        # Exposure Dials Av and Tv
        draw.text((cx - 20, by - 24), chr(0xE47D), fill="#D8D8D8", font=self.f_icons_med)
        draw.text((cx + 12, by - 22), "Av", fill="#FFFFFF", font=self.f_sans_bold)
        draw.text((cx + 80, by - 24), chr(0xE47E), fill="#D8D8D8", font=self.f_icons_med)
        draw.text((cx + 112, by - 22), "Tv", fill="#FFFFFF", font=self.f_sans_bold)

        draw.text((cx - 50, by + 4), chr(0xEB18), fill="#FFFFFF", font=self.f_icons_med)
        draw.text((cx - 15, by), self.camera_state["exp_comp"], fill="#FFFFFF", font=self.f_sans_huge)

        iso_str = "ISO AUTO" if self.camera_state["iso_mode"] == 0 else f"ISO {self.camera_state['iso_val']}"
        draw.text((w - pillar_w - 220, by), iso_str, fill="#FFFFFF", font=self.f_sans_huge)

        self.mu.mem_write(FRAMEBUFFER, img.tobytes())
        return img

    def render_fn_framebuffer(self):
        self.unsupported("host_rendering", renderer="render_fn_framebuffer")
        w, h = LCD_WIDTH, LCD_HEIGHT
        pillar_w = (w - 810) // 2

        # 1. Base Live View in background
        img = self.render_display_framebuffer()
        draw = ImageDraw.Draw(img)

        # 2. Translucent overlay on bottom 45% of screen
        overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        odraw = ImageDraw.Draw(overlay)
        odraw.rectangle([pillar_w - 10, 315, w - pillar_w + 10, 485], fill=(16, 24, 30, 190))
        odraw.rectangle([0, 485, w, h], fill=(0, 0, 0, 245))
        img.alpha_composite(overlay)
        draw = ImageDraw.Draw(img)

        # 3. Active Title glowing orange above grid with black outline
        fn_titles = [
            "Drive Mode", "Focus Mode", "Focus Area", "Exposure Comp.", "ISO", "Metering Mode",
            "Flash Mode", "Flash Comp.", "White Balance", "Creative Style", "File Format", "Shoot Mode"
        ]
        cur_title = fn_titles[self.fn_index] if self.fn_index < len(fn_titles) else "Focus Mode"
        t_bbox = draw.textbbox((0, 0), cur_title, font=self.f_sans_large)
        tx = w // 2 - (t_bbox[2] - t_bbox[0]) // 2
        self.draw_text_outline(draw, (tx, 275), cur_title, self.f_sans_large, fill_color="#FF8833", outline_color="#000000", width=3)

        # 4. 12 Fn Blocks (2 rows of 6)
        gx_start = pillar_w + 5
        gy_start = 320
        bw = (810 - 10) // 6  # ~133 px
        bh = 78

        iso_disp = "AUTO" if self.camera_state["iso_mode"] == 0 else str(self.camera_state["iso_val"])
        blocks = [
            {"type": "icon", "icon": chr(0xE24F), "val": ""},
            {"type": "badge", "text": self.camera_state["focus_mode"], "val": ""},
            {"type": "icon", "icon": chr(0xE5AA), "val": ""},
            {"type": "dual", "top": chr(0xEB18), "bot": self.camera_state["exp_comp"]},
            {"type": "dual", "top": "ISO", "bot": iso_disp},
            {"type": "icon", "icon": chr(0xE59F), "val": ""},
            {"type": "icon", "icon": chr(0xE00E), "val": ""},
            {"type": "dual", "top": chr(0xE487), "bot": "-3.0"},
            {"type": "text", "text": "AWB", "val": ""},
            {"type": "dual_badge", "top": "Std.", "bot": "±0 ±0 ±0"},
            {"type": "text", "text": self.camera_state["quality"], "val": ""},
            {"type": "text_gray", "text": "M", "val": ""}
        ]

        for i, blk in enumerate(blocks):
            r = i // 6
            c = i % 6
            bx = gx_start + c * bw
            by = gy_start + r * bh
            is_sel = (i == self.fn_index)

            if is_sel:
                draw.rectangle([bx, by, bx + bw - 2, by + bh - 2], fill="#D83010", outline="#FFAA77", width=2)
            else:
                draw.rectangle([bx, by, bx + bw - 2, by + bh - 2], fill=(20, 30, 40, 160), outline="#405060", width=1)

            cx_box = bx + bw // 2
            cy_box = by + bh // 2

            if blk["type"] == "badge":
                badge_w, badge_h = 56, 26
                draw.rectangle([cx_box - badge_w//2, cy_box - badge_h//2, cx_box + badge_w//2, cy_box + badge_h//2], fill="#FFFFFF", outline="#000000", width=1)
                draw.text((cx_box - 22, cy_box - 12), blk["text"], fill="#000000", font=self.f_sans_bold)

            elif blk["type"] == "icon":
                ibox = draw.textbbox((0, 0), blk["icon"], font=self.f_icons_large)
                draw.text((cx_box - (ibox[2]-ibox[0])//2, cy_box - (ibox[3]-ibox[1])//2), blk["icon"], fill="#FFFFFF", font=self.f_icons_large)

            elif blk["type"] == "dual":
                t_box = draw.textbbox((0, 0), blk["top"], font=self.f_icons_med if len(blk["top"]) == 1 else self.f_sans_bold)
                draw.text((cx_box - (t_box[2]-t_box[0])//2, by + 12), blk["top"], fill="#FFFFFF", font=self.f_icons_med if len(blk["top"]) == 1 else self.f_sans_bold)
                b_box = draw.textbbox((0, 0), blk["bot"], font=self.f_sans_bold)
                draw.text((cx_box - (b_box[2]-b_box[0])//2, by + 42), blk["bot"], fill="#FFFFFF", font=self.f_sans_bold)

            elif blk["type"] == "dual_badge":
                draw.rectangle([cx_box - 24, by + 12, cx_box + 24, by + 34], outline="#FFFFFF", width=1)
                draw.text((cx_box - 16, by + 14), blk["top"], fill="#FFFFFF", font=self.f_sans_tiny)
                draw.text((cx_box - 28, by + 44), blk["bot"], fill="#FFFFFF", font=self.f_sans_tiny)

            elif blk["type"] == "text":
                t_box = draw.textbbox((0, 0), blk["text"], font=self.f_sans_large)
                draw.text((cx_box - (t_box[2]-t_box[0])//2, cy_box - (t_box[3]-t_box[1])//2), blk["text"], fill="#FFFFFF", font=self.f_sans_large)

            elif blk["type"] == "text_gray":
                t_box = draw.textbbox((0, 0), blk["text"], font=self.f_sans_huge)
                draw.text((cx_box - (t_box[2]-t_box[0])//2, cy_box - (t_box[3]-t_box[1])//2), blk["text"], fill="#485868", font=self.f_sans_huge)

        # 5. Bottom Guide Bar matching Photo 2
        gy = 502
        gx = w // 2 - 250
        draw.text((gx, gy - 2), chr(0xE47D), fill="#FFFFFF", font=self.f_icons_med)
        gx += 34
        draw.text((gx, gy), "/", fill="#FFFFFF", font=self.f_sans_med)
        gx += 16
        draw.text((gx, gy - 2), chr(0xE47E), fill="#FFFFFF", font=self.f_icons_med)
        gx += 34
        draw.text((gx, gy), "Change", fill="#FFFFFF", font=self.f_sans_med)
        gx += 85

        draw.text((gx, gy - 2), chr(0xEB01), fill="#FFFFFF", font=self.f_icons_med)
        gx += 28
        draw.text((gx, gy), "More", fill="#FFFFFF", font=self.f_sans_med)
        gx += 70

        draw.text((gx, gy - 2), chr(0xEB00), fill="#FFFFFF", font=self.f_icons_med)
        gx += 30
        draw.text((gx, gy), "?", fill="#FFFFFF", font=self.f_sans_med)
        gx += 35

        draw.text((gx, gy - 2), chr(0xEB03), fill="#FFFFFF", font=self.f_icons_med)
        gx += 50
        draw.text((gx, gy - 2), chr(0xEB0D), fill="#FFFFFF", font=self.f_icons_med)

        self.mu.mem_write(FRAMEBUFFER, img.tobytes())
        return img

    def render_menu_framebuffer(self):
        self.unsupported("host_rendering", renderer="render_menu_framebuffer")
        w, h = LCD_WIDTH, LCD_HEIGHT
        img = Image.new("RGBA", (w, h), (16, 16, 16, 255))
        draw = ImageDraw.Draw(img)

        tab_w = w // 6  # 160 px
        th = 58

        # 1. Top 6 Tabs with authentic Sony colors
        tab_configs = [
            {"icon_type": "font", "code": 0xE594, "color": "#C82020"},
            {"icon_type": "font", "code": 0xE595, "color": "#8E388E"},
            {"icon_type": "globe", "color": "#2070C0"},
            {"icon_type": "font", "code": 0xE079, "color": "#189030"},
            {"icon_type": "briefcase", "color": "#D08010"},
            {"icon_type": "font", "code": 0xE5C2, "color": "#808080"}
        ]

        for i, cfg in enumerate(tab_configs):
            tx = i * tab_w
            is_cur = (i + 1 == self.menu_tab)
            if is_cur:
                draw.rectangle([tx, 0, tx + tab_w, th], fill=cfg["color"])
            else:
                draw.rectangle([tx, 0, tx + tab_w, th], fill="#121212")
                draw.line([tx, th - 3, tx + tab_w, th - 3], fill=cfg["color"], width=3)

            cx = tx + tab_w // 2
            cy = th // 2 - 2

            if cfg["icon_type"] == "font":
                ibox = draw.textbbox((0, 0), chr(cfg["code"]), font=self.f_icons_large)
                draw.text((cx - (ibox[2]-ibox[0])//2, cy - (ibox[3]-ibox[1])//2), chr(cfg["code"]), fill="#FFFFFF", font=self.f_icons_large)
            elif cfg["icon_type"] == "globe":
                gr = 14
                draw.ellipse([cx - gr, cy - gr, cx + gr, cy + gr], outline="#FFFFFF", width=2)
                draw.ellipse([cx - gr//2, cy - gr, cx + gr//2, cy + gr], outline="#FFFFFF", width=1)
                draw.line([cx - gr, cy, cx + gr, cy], fill="#FFFFFF", width=1)
                draw.line([cx, cy - gr, cx, cy + gr], fill="#FFFFFF", width=1)
            elif cfg["icon_type"] == "briefcase":
                bx = cx - 14
                by = cy - 9
                draw.line([bx + 8, by - 4, bx + 20, by - 4], fill="#FFFFFF", width=2)
                draw.line([bx + 8, by - 4, bx + 8, by], fill="#FFFFFF", width=2)
                draw.line([bx + 20, by - 4, bx + 20, by], fill="#FFFFFF", width=2)
                draw.rectangle([bx, by, bx + 28, by + 18], outline="#FFFFFF", width=2)
                draw.line([bx, by + 9, bx + 28, by + 9], fill="#FFFFFF", width=1)
                draw.rectangle([bx + 12, by + 7, bx + 16, by + 11], fill="#FFFFFF")

        # 2. Sub-tab title header bar: "Quality/Image Size1" and "1/14 ▶"
        sub_y = th + 8
        tab_names = ["Quality/Image Size1", "Movie/Shoot Settings2", "Network Settings", "Playback Settings", "Setup Settings", "My Menu1"]
        cur_tab_name = tab_names[self.menu_tab - 1] if self.menu_tab <= len(tab_names) else "Settings"
        draw.text((35, sub_y), cur_tab_name, fill="#FFFFFF", font=self.f_sans_bold)
        draw.text((w - 130, sub_y), "1/14", fill="#FFFFFF", font=self.f_sans_bold)
        draw.text((w - 75, sub_y - 2), chr(0xEB08), fill="#FFFFFF", font=self.f_icons_med)

        # 3. 6 Menu Item Rows
        menu_rows = []
        for it_idx in range(6):
            info = self.menu_options_map.get((self.menu_tab, it_idx), None)
            if info:
                name = info["name"]
                val = self.camera_state.get(info["key"], info["options"][0])
                has_icon = (it_idx < 4)
                menu_rows.append({"icon": chr(0xE08C) if has_icon else "", "name": name, "val": str(val)})
            else:
                menu_rows.append({"icon": "", "name": f"Stavka {it_idx+1}", "val": "--"})

        row_y_start = sub_y + 40
        row_h = 54

        for i, item in enumerate(menu_rows):
            ry = row_y_start + i * row_h
            is_active = (i == self.menu_item)

            if is_active:
                draw.rectangle([20, ry, w - 20, ry + row_h - 4], fill="#D83010", outline="#FF8855", width=1)
                name_col = "#FFFFFF"
                val_col = "#FFFFFF"
            else:
                name_col = "#E0E0E0"
                val_col = "#E0E0E0"

            draw.line([20, ry + row_h - 2, w - 20, ry + row_h - 2], fill="#262626", width=1)

            cur_x = 35
            if item["icon"]:
                draw.text((cur_x, ry + 10), item["icon"], fill="#FFFFFF", font=self.f_icons_med)
                cur_x += 35

            draw.text((cur_x, ry + 12), item["name"], fill=name_col, font=self.f_sans_large)

            v_box = draw.textbbox((0, 0), item["val"], font=self.f_sans_large)
            v_w = v_box[2] - v_box[0]
            draw.text((w - 50 - v_w, ry + 12), item["val"], fill=val_col, font=self.f_sans_large)

        # 4. Bottom Footer: 14 Pip Indicators + Trash + MENU
        fy = h - 42
        pip_start_x = 35
        for p in range(14):
            px = pip_start_x + p * 18
            if p == 0:
                draw.rectangle([px, fy + 4, px + 11, fy + 15], fill="#D83010")
            else:
                draw.rectangle([px, fy + 4, px + 11, fy + 15], fill="#707070")

        rx = w - 170
        draw.text((rx, fy), chr(0xEB00), fill="#FFFFFF", font=self.f_icons_med)
        draw.text((rx + 30, fy + 2), "?", fill="#FFFFFF", font=self.f_sans_med)
        draw.text((rx + 60, fy), chr(0xEB03), fill="#FFFFFF", font=self.f_icons_med)
        draw.text((rx + 110, fy), chr(0xEB0D), fill="#FFFFFF", font=self.f_icons_med)

        # 5. Modal Sub-Choice Popup if an item is opened
        if self.menu_sub_active:
            item_info = self.menu_options_map.get((self.menu_tab, self.menu_item), None)
            if item_info:
                overlay = Image.new("RGBA", (w, h), (0, 0, 0, 175))
                img.alpha_composite(overlay)
                draw = ImageDraw.Draw(img)

                pw_x1, pw_y1, pw_x2, pw_y2 = 220, 65, 740, h - 50
                draw.rectangle([pw_x1, pw_y1, pw_x2, pw_y2], fill="#1c1c1c", outline="#444444", width=2)
                draw.rectangle([pw_x1, pw_y1, pw_x2, pw_y1 + 45], fill="#282828")
                draw.rectangle([pw_x1, pw_y1 + 43, pw_x2, pw_y1 + 45], fill="#D83010")
                draw.text((pw_x1 + 20, pw_y1 + 12), item_info["name"].upper(), fill="#FFFFFF", font=self.f_sans_bold)

                options = item_info["options"]
                cur_val = self.camera_state.get(item_info["key"], None)
                for o_idx, opt in enumerate(options):
                    oy = pw_y1 + 60 + o_idx * 48
                    is_hover = (o_idx == self.menu_sub_index)
                    is_checked = (opt == cur_val)

                    if is_hover:
                        draw.rectangle([pw_x1 + 10, oy, pw_x2 - 10, oy + 42], fill="#2c2c2c", outline="#D83010", width=1)

                    draw.ellipse([pw_x1 + 25, oy + 12, pw_x1 + 43, oy + 30], outline="#888888" if not is_checked else "#D83010", width=2)
                    if is_checked:
                        draw.ellipse([pw_x1 + 29, oy + 16, pw_x1 + 39, oy + 26], fill="#D83010")

                    draw.text((pw_x1 + 55, oy + 11), opt, fill="#FFFFFF" if is_hover else "#CCCCCC", font=self.f_sans_med)

                draw.rectangle([pw_x1, pw_y2 - 35, pw_x2, pw_y2], fill="#161616")
                draw.text((pw_x1 + 20, pw_y2 - 26), "OK/ENTER: Potvrdi | MENU/◄: Odustani | ▲▼: Kretanje", fill="#888888", font=self.f_sans_tiny)

        self.mu.mem_write(FRAMEBUFFER, img.tobytes())
        return img

    def render_quick_navi_framebuffer(self):
        self.unsupported("host_rendering", renderer="render_quick_navi_framebuffer")
        w, h = LCD_WIDTH, LCD_HEIGHT
        img = Image.new("RGBA", (w, h), (16, 16, 16, 255))
        draw = ImageDraw.Draw(img)

        # Top Bar
        draw.rectangle([0, 0, w, 36], fill="#1c1c1c")
        draw.text((15, 8), "M", fill="#FFFFFF", font=self.f_sans_bold)
        draw.text((45, 8), self.camera_state["quality"], fill="#FFFFFF", font=self.f_sans_bold)
        draw.text((115, 8), self.camera_state["aspect_ratio"], fill="#AAAAAA", font=self.f_sans_small)
        draw.text((430, 8), "[1] SD", fill="#FFFFFF", font=self.f_sans_bold)
        draw.text((485, 8), f"{self.camera_state['card_remaining']} slika", fill="#CCCCCC", font=self.f_sans_small)
        draw.text((810, 8), f"{self.camera_state['battery_pct']}%", fill="#FFFFFF", font=self.f_sans_bold)
        self.draw_battery(draw, 875, 11, pct=self.camera_state["battery_pct"])

        # Digital Numbers
        shutter_str = f"1/{self.camera_state['shutter_den']}"
        aperture_str = f"F{self.camera_state['aperture_val']/10:.1f}"
        iso_str = "ISO AUTO" if self.camera_state["iso_mode"] == 0 else f"ISO {self.camera_state['iso_val']}"

        draw.text((40, 80), "BRZINA OKIDAČA", fill="#777777", font=self.f_sans_tiny)
        draw.text((40, 100), shutter_str, fill="#FFFFFF", font=self.f_sans_huge)

        draw.text((360, 80), "OTVOR BLENDE", fill="#777777", font=self.f_sans_tiny)
        draw.text((360, 100), aperture_str, fill="#FFFFFF", font=self.f_sans_huge)

        draw.text((680, 80), "ISO OSETLJIVOST", fill="#777777", font=self.f_sans_tiny)
        draw.text((680, 100), iso_str, fill="#D83010", font=self.f_sans_huge)

        draw.line([20, 175, w - 20, 175], fill="#282828", width=1)

        draw.text((40, 200), "EKSPOZICIJA (MM)", fill="#777777", font=self.f_sans_tiny)
        draw.text((40, 220), self.camera_state["exp_comp"], fill="#FFFFFF", font=self.f_sans_bold)

        draw.text((360, 200), "FOKUS MOD", fill="#777777", font=self.f_sans_tiny)
        draw.text((360, 220), self.camera_state["focus_mode"], fill="#00FF00" if self.af_locked else "#FFFFFF", font=self.f_sans_bold)

        draw.text((680, 200), "PROFIL SLIKE", fill="#777777", font=self.f_sans_tiny)
        draw.text((680, 220), f"PP{self.camera_state['picture_profile']}", fill="#FFFFFF", font=self.f_sans_bold)

        self.mu.mem_write(FRAMEBUFFER, img.tobytes())
        return img

    def render_playback_framebuffer(self):
        self.unsupported("host_rendering", renderer="render_playback_framebuffer")
        w, h = LCD_WIDTH, LCD_HEIGHT
        pillar_w = (w - 810) // 2

        img = Image.new("RGBA", (w, h), (0, 0, 0, 255))
        current_photo = self.playback_photos[self.playback_index]

        # 1. 9-Image Grid Contact Sheet View
        if self.playback_grid_view:
            draw = ImageDraw.Draw(img)
            draw.rectangle([0, 0, w, 36], fill="#181818")
            draw.text((20, 8), f"REPRODUKCIJA INDEKS ({current_photo['id']})", fill="#FFFFFF", font=self.f_sans_bold)
            draw.text((500, 8), f"{self.playback_index + 1} / {len(self.playback_photos)}", fill="#AAAAAA", font=self.f_sans_small)
            self.draw_battery(draw, w - 80, 10, pct=self.camera_state["battery_pct"])

            gw = (w - 120) // 3
            gh = (h - 130) // 3
            for gi in range(min(9, len(self.playback_photos))):
                p = self.playback_photos[gi]
                gx = 50 + (gi % 3) * (gw + 10)
                gy = 55 + (gi // 3) * (gh + 8)
                is_cur = (gi == self.playback_index)
                draw.rectangle([gx, gy, gx + gw, gy + gh], fill=p["bg_color"], outline="#D83010" if is_cur else "#333333", width=3 if is_cur else 1)
                draw.text((gx + 8, gy + 8), p["id"], fill="#FFFFFF" if is_cur else "#888888", font=self.f_sans_tiny)
                draw.text((gx + 8, gy + gh - 22), p["format"], fill="#D83010" if is_cur else "#666666", font=self.f_sans_tiny)

            draw.rectangle([0, h - 35, w, h], fill="#181818")
            draw.text((40, h - 26), "▲▼: Izlaz iz indeksa | ◄►: Odabir fotografije | OK: Prikaz pune slike", fill="#888888", font=self.f_sans_tiny)
            self.mu.mem_write(FRAMEBUFFER, img.tobytes())
            return img

        # 2. Authentic Single Photo View (Photo 4 Parity)
        if current_photo.get("image_obj") and self.sensor_3_2_frame:
            img.paste(self.sensor_3_2_frame, (pillar_w, 0))
        elif current_photo.get("image_obj"):
            img.paste(current_photo["image_obj"], (0, 0))
        else:
            draw = ImageDraw.Draw(img)
            draw.rectangle([pillar_w, 0, w - pillar_w, h], fill=current_photo["bg_color"])

        draw = ImageDraw.Draw(img)

        # Top Bar Overlay
        ty = 20
        draw.text((pillar_w + 15, ty), chr(0xE105), fill="#FFFFFF", font=self.f_icons_med)
        draw.text((pillar_w + 50, ty), chr(0xE079), fill="#FFFFFF", font=self.f_icons_med)

        count_str = f"{self.playback_index + 1}/{len(self.playback_photos)}"
        draw.text((w - pillar_w - 200, ty), count_str, fill="#FFFFFF", font=self.f_sans_large)
        draw.text((w - pillar_w - 120, ty), chr(0xE52A), fill="#FFFFFF", font=self.f_icons_med)
        self.draw_battery(draw, w - pillar_w - 65, ty + 2, pct=self.camera_state["battery_pct"])

        # Bottom Overlay
        by = h - 55
        draw.text((pillar_w + 15, by), current_photo["date"].split()[0], fill="#FFFFFF", font=self.f_sans_large)
        draw.text((pillar_w + 190, by), current_photo["date"].split()[1] if len(current_photo["date"].split()) > 1 else "", fill="#FFFFFF", font=self.f_sans_large)

        draw.text((375, by - 2), chr(0xE066), fill="#FFFFFF", font=self.f_icons_med)
        draw.text((410, by), current_photo["id"], fill="#FFFFFF", font=self.f_sans_large)

        ry_upper = by - 36
        draw.text((690, ry_upper), chr(0xE2BE), fill="#FFFFFF", font=self.f_icons_med)
        draw.text((770, ry_upper), chr(0xE48E), fill="#FFFFFF", font=self.f_icons_med)

        draw.text((585, by), f"{current_photo['shutter']}s", fill="#FFFFFF", font=self.f_sans_large)
        draw.text((685, by), current_photo["aperture"], fill="#FFFFFF", font=self.f_sans_large)
        draw.text((775, by), current_photo["iso"], fill="#FFFFFF", font=self.f_sans_large)

        self.mu.mem_write(FRAMEBUFFER, img.tobytes())
        return img

    def get_framebuffer_image(self):
        raw_rgba = self.mu.mem_read(FRAMEBUFFER, LCD_WIDTH * LCD_HEIGHT * 4)
        return Image.frombytes('RGBA', (LCD_WIDTH, LCD_HEIGHT), bytes(raw_rgba))

def main():
    emu = CXD90045_HLE_Emulator()
    libobj_path = os.path.join(LIB_DIR, "libObj.so")
    vu2_path = os.path.join(LIB_DIR, "viewUnified2.so")
    
    if os.path.exists(libobj_path) and os.path.exists(vu2_path):
        emu.load_elf_module(libobj_path, base_addr=0x30000000)
        emu.load_elf_module(vu2_path, base_addr=0x32000000)
        emu.setup_sony_subsystems()
        emu.instantiate_all_screens()
        
        # Test hardware key input
        print("\n[*] Testiram slanje hardverske tipke KEY_TACT_MENU...")
        img_menu = emu.send_hardware_key(KEY_TACT_MENU)
        img_menu.save(legacy_output("cxd90045_menu_test.png"))

        print("\n[*] Testiram povratak na LIVE_VIEW...")
        img_lv = emu.send_hardware_key(KEY_TACT_MENU)
        img_lv.save(legacy_output("cxd90045_liveview_authentic.png"))
        print("\n[+] Svi hardverski input testovi uspesno zavrseni!")
    else:
        print("[-] Biblioteke nisu pronadjene!")

if __name__ == '__main__':
    main()
