import os
import math
from PIL import Image, ImageDraw, ImageFont

from project_paths import PROJECT_ROOT as _PROJECT_ROOT, REFERENCE_ASSETS, legacy_output
PROJECT_ROOT = str(_PROJECT_ROOT)
FONT_PATH = os.path.join(PROJECT_ROOT, r"firmware\extracted_a6400\firmware.tar_unpacked\0800_appli\tmp\images\Sony_DI_Icons.ttf")
USER_IMG_PATH = str(REFERENCE_ASSETS / "20261015-_DSC0799 copy.jpg")

LCD_W, LCD_H = 960, 540
SENSOR_W, SENSOR_H = 810, 540
PILLAR_W = (LCD_W - SENSOR_W) // 2  # 75 px each

# Load fonts
f_icons_large = ImageFont.truetype(FONT_PATH, 32)
f_icons_med   = ImageFont.truetype(FONT_PATH, 24)
f_icons_small = ImageFont.truetype(FONT_PATH, 18)
f_icons_tiny  = ImageFont.truetype(FONT_PATH, 14)

f_sans_huge   = ImageFont.truetype("arialbd.ttf", 36)
f_sans_large  = ImageFont.truetype("arialbd.ttf", 24)
f_sans_med    = ImageFont.truetype("arial.ttf", 19)
f_sans_bold   = ImageFont.truetype("arialbd.ttf", 18)
f_sans_small  = ImageFont.truetype("arial.ttf", 15)
f_sans_tiny   = ImageFont.truetype("arial.ttf", 12)

# Load and prepare sensor image
raw_photo = Image.open(USER_IMG_PATH)
sensor_img = raw_photo.resize((SENSOR_W, SENSOR_H), Image.Resampling.LANCZOS)

def draw_battery(draw, x, y, pct=99):
    bw, bh = 34, 18
    # Outer rectangle
    draw.rectangle([x, y, x + bw, y + bh], outline="#FFFFFF", width=2)
    # Right nipple
    draw.rectangle([x + bw, y + 4, x + bw + 3, y + bh - 4], fill="#FFFFFF")
    # 4 diagonal bars (slanted at ~65 deg)
    bars_active = min(4, max(0, int((pct + 12) / 25)))
    for i in range(4):
        bx = x + 4 + i * 7
        if i < bars_active:
            poly = [(bx + 3, y + 3), (bx + 7, y + 3), (bx + 4, y + bh - 3), (bx, y + bh - 3)]
            draw.polygon(poly, fill="#FFFFFF")

def draw_text_outline(draw, pos, text, font, fill_color, outline_color, width=2):
    x, y = pos
    for dx in range(-width, width + 1):
        for dy in range(-width, width + 1):
            if dx*dx + dy*dy <= width*width and (dx != 0 or dy != 0):
                draw.text((x + dx, y + dy), text, fill=outline_color, font=font)
    draw.text((x, y), text, fill=fill_color, font=font)

# ---------------------------------------------------------
# 1. LIVE VIEW (Photo 1 Visual Parity)
# ---------------------------------------------------------
def render_liveview():
    img = Image.new("RGBA", (LCD_W, LCD_H), (0, 0, 0, 255))
    # Paste centered sensor image
    img.paste(sensor_img, (PILLAR_W, 0))
    draw = ImageDraw.Draw(img)

    # 1. Left & Right black pillar backgrounds
    draw.rectangle([0, 0, PILLAR_W, LCD_H], fill="#000000")
    draw.rectangle([LCD_W - PILLAR_W, 0, LCD_W, LCD_H], fill="#000000")

    # 2. Rule of thirds grid on sensor plane (subtle)
    grid_col = (255, 255, 255, 40)
    for gx in [PILLAR_W + SENSOR_W // 3, PILLAR_W + 2 * SENSOR_W // 3]:
        draw.line([gx, 0, gx, LCD_H], fill=grid_col, width=1)
    for gy in [LCD_H // 3, 2 * LCD_H // 3]:
        draw.line([PILLAR_W, gy, PILLAR_W + SENSOR_W, gy], fill=grid_col, width=1)

    # 3. Center focus brackets [   ]
    cx, cy = LCD_W // 2, LCD_H // 2
    b_col = "#687078"
    bw, bh, blen = 65, 45, 14
    # Top-Left
    draw.line([cx - bw, cy - bh, cx - bw + blen, cy - bh], fill=b_col, width=2)
    draw.line([cx - bw, cy - bh, cx - bw, cy - bh + blen], fill=b_col, width=2)
    # Top-Right
    draw.line([cx + bw, cy - bh, cx + bw - blen, cy - bh], fill=b_col, width=2)
    draw.line([cx + bw, cy - bh, cx + bw, cy - bh + blen], fill=b_col, width=2)
    # Bottom-Left
    draw.line([cx - bw, cy + bh, cx - bw + blen, cy + bh], fill=b_col, width=2)
    draw.line([cx - bw, cy + bh, cx - bw, cy + bh - blen], fill=b_col, width=2)
    # Bottom-Right
    draw.line([cx + bw, cy + bh, cx + bw - blen, cy + bh], fill=b_col, width=2)
    draw.line([cx + bw, cy + bh, cx + bw, cy + bh - blen], fill=b_col, width=2)

    # 4. Left Pillar OSD Icons
    lx = 18
    # 'M'
    draw.text((lx + 6, 25), "M", fill="#FFFFFF", font=f_sans_large)
    # Single drive mode icon E24F
    draw.text((lx + 4, 85), chr(0xE24F), fill="#FFFFFF", font=f_icons_med)
    # AF-C in rounded box E48B
    draw.text((lx + 2, 145), chr(0xE48B), fill="#FFFFFF", font=f_icons_med)
    # Wide focus area E5AA
    draw.text((lx + 2, 205), chr(0xE5AA), fill="#FFFFFF", font=f_icons_med)
    # Face AF E4C1 + AF ON
    draw.text((lx + 2, 260), chr(0xE4C1), fill="#FFFFFF", font=f_icons_med)
    draw.text((lx + 30, 266), "AF", fill="#FFFFFF", font=f_sans_tiny)
    draw.text((lx + 30, 280), "ON", fill="#FFFFFF", font=f_sans_tiny)
    # Picture Profile PP OFF
    draw.rectangle([lx + 6, 325, lx + 44, 345], outline="#FFFFFF", width=1)
    draw.text((lx + 10, 327), "PP", fill="#FFFFFF", font=f_sans_tiny)
    draw.text((lx + 11, 348), "OFF", fill="#FFFFFF", font=f_sans_tiny)

    # 5. Top Bar over sensor
    # Left: SD slot 1 & remaining frames
    draw.text((PILLAR_W + 15, 20), chr(0xE105), fill="#FFFFFF", font=f_icons_med)
    draw.text((PILLAR_W + 50, 22), "4865", fill="#FFFFFF", font=f_sans_bold)

    # Center: 3:2 and RAW and SteadyShot OFF
    draw.text((cx - 85, 22), chr(0xE2BE), fill="#FFFFFF", font=f_icons_med)
    draw.text((cx + 5, 22), chr(0xE48E), fill="#FFFFFF", font=f_icons_med)
    draw.text((cx + 12, 52), chr(0xE02C), fill="#FFFFFF", font=f_icons_med)

    # Right: Battery gauge & 99%
    draw_battery(draw, LCD_W - PILLAR_W - 120, 24, pct=99)
    draw.text((LCD_W - PILLAR_W - 75, 22), "99%", fill="#FFFFFF", font=f_sans_large)

    # 6. Right Pillar OSD Icons
    rx = LCD_W - PILLAR_W + 12
    # Metering Multi E59F
    draw.text((rx + 2, 90), chr(0xE59F), fill="#FFFFFF", font=f_icons_med)
    # AWB
    draw.text((rx + 4, 155), "AWB", fill="#FFFFFF", font=f_sans_bold)
    # DRO AUTO
    draw.text((rx + 5, 205), "DRO", fill="#FFFFFF", font=f_sans_small)
    draw.text((rx + 2, 222), "AUTO", fill="#FFFFFF", font=f_sans_tiny)
    # Creative Style Std. +-0 +-0 +-0
    draw.rectangle([rx + 4, 260, rx + 48, 280], outline="#FFFFFF", width=1)
    draw.text((rx + 7, 262), "Std.", fill="#FFFFFF", font=f_sans_tiny)
    draw.text((rx + 2, 283), "±0±0±0", fill="#FFFFFF", font=f_sans_tiny)
    # Picture Effect OFF
    draw.text((rx + 2, 320), chr(0xE47F), fill="#FFFFFF", font=f_icons_med)
    draw.text((rx + 28, 332), "OFF", fill="#FFFFFF", font=f_sans_tiny)

    # 7. Bottom Status Row
    by = 485
    # Shutter speed 1/60
    draw.text((PILLAR_W + 40, by), "1/60", fill="#FFFFFF", font=f_sans_huge)
    # Aperture F1.8
    draw.text((PILLAR_W + 210, by), "F1.8", fill="#FFFFFF", font=f_sans_huge)

    # Exposure Dials Av and Tv (exact Sony glyphs)
    # Av dial (top dial E47D)
    draw.text((cx - 20, by - 24), chr(0xE47D), fill="#D8D8D8", font=f_icons_med)
    draw.text((cx + 12, by - 22), "Av", fill="#FFFFFF", font=f_sans_bold)
    # Tv dial (control wheel E47E)
    draw.text((cx + 80, by - 24), chr(0xE47E), fill="#D8D8D8", font=f_icons_med)
    draw.text((cx + 112, by - 22), "Tv", fill="#FFFFFF", font=f_sans_bold)

    # Exposure comp [+/-] +-0.0
    draw.text((cx - 50, by + 4), chr(0xEB18), fill="#FFFFFF", font=f_icons_med)
    draw.text((cx - 15, by), "±0.0", fill="#FFFFFF", font=f_sans_huge)

    # ISO AUTO
    draw.text((LCD_W - PILLAR_W - 220, by), "ISO AUTO", fill="#FFFFFF", font=f_sans_huge)

    return img

# ---------------------------------------------------------
# 2. FN MENU (Photo 2 Visual Parity)
# ---------------------------------------------------------
def render_fn_menu(selected_idx=1):
    # Base: Live View in background
    img = render_liveview()

    # Dark translucent gradient/overlay on bottom 45% of screen
    overlay = Image.new("RGBA", (LCD_W, LCD_H), (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    # Translucent band for Fn grid
    odraw.rectangle([PILLAR_W - 10, 315, LCD_W - PILLAR_W + 10, 485], fill=(16, 24, 30, 190))
    odraw.rectangle([0, 485, LCD_W, LCD_H], fill=(0, 0, 0, 245))
    img.alpha_composite(overlay)
    draw = ImageDraw.Draw(img)

    # Active title glowing orange above grid with black outline
    # For selected_idx = 1 ("Focus Mode"):
    fn_titles = [
        "Drive Mode", "Focus Mode", "Focus Area", "Exposure Comp.", "ISO", "Metering Mode",
        "Flash Mode", "Flash Comp.", "White Balance", "Creative Style", "File Format", "Shoot Mode"
    ]
    cur_title = fn_titles[selected_idx]
    # Center title above grid
    t_bbox = draw.textbbox((0, 0), cur_title, font=f_sans_large)
    tx = LCD_W // 2 - (t_bbox[2] - t_bbox[0]) // 2
    draw_text_outline(draw, (tx, 275), cur_title, f_sans_large, fill_color="#FF8833", outline_color="#000000", width=3)

    # 12 Fn Blocks (2 rows of 6)
    gx_start = PILLAR_W + 5
    gy_start = 320
    bw = (SENSOR_W - 10) // 6  # ~133 px
    bh = 78

    # Block definitions matching Photo 2
    blocks = [
        # Row 1
        {"type": "icon", "icon": chr(0xE24F), "val": ""},
        {"type": "badge", "text": "AF-C", "val": ""},
        {"type": "icon", "icon": chr(0xE5AA), "val": ""},
        {"type": "dual", "top": chr(0xEB18), "bot": "±0.0"},
        {"type": "dual", "top": "ISO", "bot": "AUTO"},
        {"type": "icon", "icon": chr(0xE59F), "val": ""},
        # Row 2
        {"type": "icon", "icon": chr(0xE00E), "val": ""},
        {"type": "dual", "top": chr(0xE487), "bot": "-3.0"},
        {"type": "text", "text": "AWB", "val": ""},
        {"type": "dual_badge", "top": "Std.", "bot": "±0 ±0 ±0"},
        {"type": "text", "text": "RAW", "val": ""},
        {"type": "text_gray", "text": "M", "val": ""}
    ]

    for i, blk in enumerate(blocks):
        r = i // 6
        c = i % 6
        bx = gx_start + c * bw
        by = gy_start + r * bh
        is_sel = (i == selected_idx)

        # Draw box outline / fill
        if is_sel:
            # Solid bright orange/red fill exactly as in Photo 2
            draw.rectangle([bx, by, bx + bw - 2, by + bh - 2], fill="#D83010", outline="#FFAA77", width=2)
        else:
            draw.rectangle([bx, by, bx + bw - 2, by + bh - 2], fill=(20, 30, 40, 160), outline="#405060", width=1)

        # Draw content
        cx_box = bx + bw // 2
        cy_box = by + bh // 2

        if blk["type"] == "badge":
            # AF-C in white box with black text
            badge_w, badge_h = 56, 26
            draw.rectangle([cx_box - badge_w//2, cy_box - badge_h//2, cx_box + badge_w//2, cy_box + badge_h//2], fill="#FFFFFF", outline="#000000", width=1)
            draw.text((cx_box - 22, cy_box - 12), blk["text"], fill="#000000", font=f_sans_bold)

        elif blk["type"] == "icon":
            ibox = draw.textbbox((0, 0), blk["icon"], font=f_icons_large)
            draw.text((cx_box - (ibox[2]-ibox[0])//2, cy_box - (ibox[3]-ibox[1])//2), blk["icon"], fill="#FFFFFF", font=f_icons_large)

        elif blk["type"] == "dual":
            # Top icon/text
            t_box = draw.textbbox((0, 0), blk["top"], font=f_icons_med if len(blk["top"]) == 1 else f_sans_bold)
            draw.text((cx_box - (t_box[2]-t_box[0])//2, by + 12), blk["top"], fill="#FFFFFF", font=f_icons_med if len(blk["top"]) == 1 else f_sans_bold)
            # Bottom text
            b_box = draw.textbbox((0, 0), blk["bot"], font=f_sans_bold)
            draw.text((cx_box - (b_box[2]-b_box[0])//2, by + 42), blk["bot"], fill="#FFFFFF", font=f_sans_bold)

        elif blk["type"] == "dual_badge":
            draw.rectangle([cx_box - 24, by + 12, cx_box + 24, by + 34], outline="#FFFFFF", width=1)
            draw.text((cx_box - 16, by + 14), blk["top"], fill="#FFFFFF", font=f_sans_tiny)
            draw.text((cx_box - 28, by + 44), blk["bot"], fill="#FFFFFF", font=f_sans_tiny)

        elif blk["type"] == "text":
            t_box = draw.textbbox((0, 0), blk["text"], font=f_sans_large)
            draw.text((cx_box - (t_box[2]-t_box[0])//2, cy_box - (t_box[3]-t_box[1])//2), blk["text"], fill="#FFFFFF", font=f_sans_large)

        elif blk["type"] == "text_gray":
            t_box = draw.textbbox((0, 0), blk["text"], font=f_sans_huge)
            draw.text((cx_box - (t_box[2]-t_box[0])//2, cy_box - (t_box[3]-t_box[1])//2), blk["text"], fill="#485868", font=f_sans_huge)

    # Bottom Guide Bar matching Photo 2
    gy = 502
    gx = LCD_W // 2 - 250
    # [Dial] / [Wheel] Change
    draw.text((gx, gy - 2), chr(0xE47D), fill="#FFFFFF", font=f_icons_med)
    gx += 34
    draw.text((gx, gy), "/", fill="#FFFFFF", font=f_sans_med)
    gx += 16
    draw.text((gx, gy - 2), chr(0xE47E), fill="#FFFFFF", font=f_icons_med)
    gx += 34
    draw.text((gx, gy), "Change", fill="#FFFFFF", font=f_sans_med)
    gx += 85

    # Center dot More
    draw.text((gx, gy - 2), chr(0xEB01), fill="#FFFFFF", font=f_icons_med)
    gx += 28
    draw.text((gx, gy), "More", fill="#FFFFFF", font=f_sans_med)
    gx += 70

    # Trash ?
    draw.text((gx, gy - 2), chr(0xEB00), fill="#FFFFFF", font=f_icons_med)
    gx += 30
    draw.text((gx, gy), "?", fill="#FFFFFF", font=f_sans_med)
    gx += 35

    # MENU Return
    draw.text((gx, gy - 2), chr(0xEB03), fill="#FFFFFF", font=f_icons_med)
    gx += 50
    draw.text((gx, gy - 2), chr(0xEB0D), fill="#FFFFFF", font=f_icons_med)

    return img

# ---------------------------------------------------------
# 3. SETTINGS MENU (Photo 3 Visual Parity)
# ---------------------------------------------------------
def render_settings_menu(active_tab=1, active_row=0):
    img = Image.new("RGBA", (LCD_W, LCD_H), (16, 16, 16, 255))
    draw = ImageDraw.Draw(img)

    tab_w = LCD_W // 6  # 160 px
    th = 58

    # 1. Top 6 Tabs with authentic Sony colors
    # Tab 1: Camera 1 (Red)
    # Tab 2: Camera 2 (Purple)
    # Tab 3: Globe (Blue)
    # Tab 4: Playback (Green)
    # Tab 5: Briefcase / Setup (Yellow/Amber)
    # Tab 6: My Menu Star (Gray)
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
        is_cur = (i + 1 == active_tab)
        if is_cur:
            # Active tab has solid color block fill (e.g. Red for Tab 1)
            draw.rectangle([tx, 0, tx + tab_w, th], fill=cfg["color"])
        else:
            # Inactive tabs have dark background with colored bottom underline
            draw.rectangle([tx, 0, tx + tab_w, th], fill="#121212")
            draw.line([tx, th - 3, tx + tab_w, th - 3], fill=cfg["color"], width=3)

        cx = tx + tab_w // 2
        cy = th // 2 - 2

        if cfg["icon_type"] == "font":
            ibox = draw.textbbox((0, 0), chr(cfg["code"]), font=f_icons_large)
            draw.text((cx - (ibox[2]-ibox[0])//2, cy - (ibox[3]-ibox[1])//2), chr(cfg["code"]), fill="#FFFFFF", font=f_icons_large)
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
    draw.text((35, sub_y), "Quality/Image Size1", fill="#FFFFFF", font=f_sans_bold)
    # Right page counter: "1/14 ▶"
    draw.text((LCD_W - 130, sub_y), "1/14", fill="#FFFFFF", font=f_sans_bold)
    draw.text((LCD_W - 75, sub_y - 2), chr(0xEB08), fill="#FFFFFF", font=f_icons_med)

    # 3. 6 Menu Item Rows
    menu_rows = [
        {"icon": chr(0xE08C), "name": "File Format", "val": "RAW"},
        {"icon": chr(0xE08C), "name": "JPEG Quality", "val": "Extra fine"},
        {"icon": chr(0xE08C), "name": "JPEG Image Size", "val": "L: 24M"},
        {"icon": chr(0xE08C), "name": "Aspect Ratio", "val": "3:2"},
        {"icon": "", "name": "Panorama: Size", "val": "-"},
        {"icon": "", "name": "Panorama: Direction", "val": "-"}
    ]

    row_y_start = sub_y + 40
    row_h = 54

    for i, item in enumerate(menu_rows):
        ry = row_y_start + i * row_h
        is_active = (i == active_row)

        if is_active:
            # Active orange/red gradient bar across full width matching Photo 3
            draw.rectangle([20, ry, LCD_W - 20, ry + row_h - 4], fill="#D83010", outline="#FF8855", width=1)
            name_col = "#FFFFFF"
            val_col = "#FFFFFF"
        else:
            name_col = "#E0E0E0"
            val_col = "#E0E0E0"

        # Thin separator line underneath
        draw.line([20, ry + row_h - 2, LCD_W - 20, ry + row_h - 2], fill="#262626", width=1)

        # Draw row icon if present
        cur_x = 35
        if item["icon"]:
            draw.text((cur_x, ry + 10), item["icon"], fill="#FFFFFF", font=f_icons_med)
            cur_x += 35

        # Row Name
        draw.text((cur_x, ry + 12), item["name"], fill=name_col, font=f_sans_large)

        # Row Value right-aligned
        v_box = draw.textbbox((0, 0), item["val"], font=f_sans_large)
        v_w = v_box[2] - v_box[0]
        draw.text((LCD_W - 50 - v_w, ry + 12), item["val"], fill=val_col, font=f_sans_large)

    # 4. Bottom Footer: 14 Pip Indicators + Trash + MENU
    fy = LCD_H - 42
    # 14 indicator squares (pips)
    pip_start_x = 35
    for p in range(14):
        px = pip_start_x + p * 18
        if p == 0:
            # Active subpage: RED/ORANGE square
            draw.rectangle([px, fy + 4, px + 11, fy + 15], fill="#D83010")
        else:
            # Other subpages: gray squares
            draw.rectangle([px, fy + 4, px + 11, fy + 15], fill="#707070")

    # Right footer guide: [Trash] ? [MENU] ↩
    rx = LCD_W - 170
    draw.text((rx, fy), chr(0xEB00), fill="#FFFFFF", font=f_icons_med)
    draw.text((rx + 30, fy + 2), "?", fill="#FFFFFF", font=f_sans_med)
    draw.text((rx + 60, fy), chr(0xEB03), fill="#FFFFFF", font=f_icons_med)
    draw.text((rx + 110, fy), chr(0xEB0D), fill="#FFFFFF", font=f_icons_med)

    return img

# ---------------------------------------------------------
# 4. PLAYBACK SINGLE PHOTO (Photo 4 Visual Parity)
# ---------------------------------------------------------
def render_playback():
    img = Image.new("RGBA", (LCD_W, LCD_H), (0, 0, 0, 255))
    # Centered 3:2 image with black pillars
    img.paste(sensor_img, (PILLAR_W, 0))
    draw = ImageDraw.Draw(img)

    # Top Bar Overlay
    ty = 20
    # Left: SD slot 1 & grid playback icon
    draw.text((PILLAR_W + 15, ty), chr(0xE105), fill="#FFFFFF", font=f_icons_med)
    draw.text((PILLAR_W + 50, ty), chr(0xE079), fill="#FFFFFF", font=f_icons_med)

    # Right: "22/31", NFC icon [N], Battery gauge [ZZZZ]
    draw.text((LCD_W - PILLAR_W - 200, ty), "22/31", fill="#FFFFFF", font=f_sans_large)
    draw.text((LCD_W - PILLAR_W - 120, ty), chr(0xE52A), fill="#FFFFFF", font=f_icons_med)
    draw_battery(draw, LCD_W - PILLAR_W - 65, ty + 2, pct=99)

    # Bottom Overlay
    by = LCD_H - 55
    # Left: Date & Time: "17-10-2026   2:12"
    draw.text((PILLAR_W + 15, by), "17-10-2026", fill="#FFFFFF", font=f_sans_large)
    draw.text((PILLAR_W + 200, by), "2:12", fill="#FFFFFF", font=f_sans_large)

    # Center: Folder icon + "100-0896"
    draw.text((LCD_W // 2 - 60, by - 2), chr(0xE066), fill="#FFFFFF", font=f_icons_med)
    draw.text((LCD_W // 2 - 25, by), "100-0896", fill="#FFFFFF", font=f_sans_large)

    # Right: 3:2, RAW, 1/60, F1.8, ISO 800
    ry_upper = by - 36
    draw.text((LCD_W - PILLAR_W - 270, ry_upper), chr(0xE2BE), fill="#FFFFFF", font=f_icons_med)
    draw.text((LCD_W - PILLAR_W - 200, ry_upper), chr(0xE48E), fill="#FFFFFF", font=f_icons_med)

    draw.text((LCD_W - PILLAR_W - 380, by), "1/60", fill="#FFFFFF", font=f_sans_large)
    draw.text((LCD_W - PILLAR_W - 280, by), "F1.8", fill="#FFFFFF", font=f_sans_large)
    draw.text((LCD_W - PILLAR_W - 160, by), "ISO 800", fill="#FFFFFF", font=f_sans_large)

    return img

def main():
    print("[*] Generating 4 authentic visual parity screens...")
    
    im_lv = render_liveview()
    im_lv.save(legacy_output("cxd90045_liveview_authentic_parity.png"))
    print("[+] Saved cxd90045_liveview_authentic_parity.png")

    im_fn = render_fn_menu(selected_idx=1)
    im_fn.save(legacy_output("cxd90045_fn_menu_authentic_parity.png"))
    print("[+] Saved cxd90045_fn_menu_authentic_parity.png")

    im_menu = render_settings_menu(active_tab=1, active_row=0)
    im_menu.save(legacy_output("cxd90045_menu_authentic_parity.png"))
    print("[+] Saved cxd90045_menu_authentic_parity.png")

    im_pb = render_playback()
    im_pb.save(legacy_output("cxd90045_playback_authentic_parity.png"))
    print("[+] Saved cxd90045_playback_authentic_parity.png")

    print("[***] All 4 screens generated successfully!")

if __name__ == '__main__':
    main()
