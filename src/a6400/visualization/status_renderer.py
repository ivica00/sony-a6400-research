"""Dark-mode status visualization renderer matching AnyPS5 design."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from PIL import Image, ImageDraw, ImageFont

from src.a6400.visualization.treemap import Rect, compute_tile_grid, squarify_rects

# Colors matching the GitHub Dark / AnyPS5 palette
COLOR_BG = (11, 14, 20)           # Deep charcoal background #0b0e14
COLOR_PANEL_BG = (13, 17, 23)     # Container dark background #0d1117
COLOR_BOX_BORDER = (48, 54, 61)    # Box outline #30363d
COLOR_TEXT_WHITE = (240, 246, 252) # Crisp white text #f0f6fc
COLOR_TEXT_MUTED = (139, 148, 158) # Muted text #8b949e
COLOR_BADGE_LABEL_BG = (33, 38, 45)# Badge left bg #21262d
COLOR_BADGE_LABEL_TXT = (201, 209, 217) # Badge label text #c9d1d9
COLOR_GREEN = (46, 160, 67)        # Tile/Badge green #2ea043
COLOR_GREY_TILE = (48, 54, 61)     # Unfinished tile slate grey #30363d
COLOR_AMBER_TILE = (210, 153, 34)  # Optional partial tile amber #d29922


@dataclass
class Category:
    name: str
    done: int
    total: int
    weight: float = field(default=0.0)

    def __post_init__(self) -> None:
        if self.weight <= 0.0:
            self.weight = float(max(1, self.total))


@dataclass
class Panel:
    title: str
    badge_label: str
    categories: list[Category]

    @property
    def total_done(self) -> int:
        return sum(c.done for c in self.categories)

    @property
    def total_count(self) -> int:
        return sum(c.total for c in self.categories)

    @property
    def percentage(self) -> float:
        return (self.total_done / self.total_count * 100.0) if self.total_count > 0 else 0.0


class StatusRenderer:
    def __init__(self, width: int = 1040, height: int = 480):
        self.width = width
        self.height = height
        self._init_fonts()

    def _init_fonts(self) -> None:
        from PIL import ImageFont

        font_paths = [
            ("segoeuib.ttf", "segoeui.ttf"),
            ("arialbd.ttf", "arial.ttf"),
        ]
        system_font_dir = os.environ.get("WINDIR", "C:\\Windows") + "\\Fonts"

        self.font_title = None
        self.font_section = None
        self.font_badge = None
        self.font_label = None
        self.font_small = None

        for bold_name, regular_name in font_paths:
            b_path = os.path.join(system_font_dir, bold_name)
            r_path = os.path.join(system_font_dir, regular_name)
            if os.path.exists(b_path) and os.path.exists(r_path):
                try:
                    self.font_title = ImageFont.truetype(b_path, 28)
                    self.font_section = ImageFont.truetype(b_path, 14)
                    self.font_badge = ImageFont.truetype(b_path, 12)
                    self.font_label = ImageFont.truetype(r_path, 11)
                    self.font_small = ImageFont.truetype(r_path, 9)
                    break
                except Exception:
                    continue

        if not self.font_title:
            default_font = ImageFont.load_default()
            self.font_title = default_font
            self.font_section = default_font
            self.font_badge = default_font
            self.font_label = default_font
            self.font_small = default_font

    def _draw_pill_badge(
        self,
        draw: ImageDraw.ImageDraw,
        x: int,
        y: int,
        label: str,
        percentage_str: str,
    ) -> int:
        """Draws a split pill badge: [ label | percentage ] and returns its width."""
        pad_x = 8
        h = 22
        r = 4

        # Measure text
        bbox_l = draw.textbbox((0, 0), label, font=self.font_badge)
        w_l = bbox_l[2] - bbox_l[0] + pad_x * 2

        bbox_r = draw.textbbox((0, 0), percentage_str, font=self.font_badge)
        w_r = bbox_r[2] - bbox_r[0] + pad_x * 2

        total_w = w_l + w_r

        # Draw left capsule
        draw.rounded_rectangle((x, y, x + w_l, y + h), radius=r, corners=(True, False, False, True), fill=COLOR_BADGE_LABEL_BG)
        # Draw right capsule
        draw.rounded_rectangle((x + w_l, y, x + total_w, y + h), radius=r, corners=(False, True, True, False), fill=COLOR_GREEN)

        # Draw texts
        ty = y + 2
        draw.text((x + pad_x, ty), label, fill=COLOR_BADGE_LABEL_TXT, font=self.font_badge)
        draw.text((x + w_l + pad_x, ty), percentage_str, fill=COLOR_TEXT_WHITE, font=self.font_badge)

        return total_w

    def render(self, panels: list[Panel], title: str = "Status") -> Image.Image:
        """Renders the complete AnyPS5-style status dashboard image."""
        from PIL import Image, ImageDraw

        img = Image.new("RGB", (self.width, self.height), color=COLOR_BG)
        draw = ImageDraw.Draw(img)

        # 1. Main Header Title
        margin_x = 24
        top_y = 18
        draw.text((margin_x, top_y), title, fill=COLOR_TEXT_WHITE, font=self.font_title)

        # 2. Pill Badges row
        badge_y = top_y + 44
        badge_x = margin_x
        for panel in panels:
            pct_text = f"{panel.percentage:.2f}%" if panel.percentage < 99.999 else "100.0%"
            badge_width = self._draw_pill_badge(draw, badge_x, badge_y, panel.badge_label, pct_text)
            badge_x += badge_width + 8

        # Horizontal subtle divider line
        divider_y = badge_y + 34
        draw.line((margin_x, divider_y, self.width - margin_x, divider_y), fill=(30, 36, 44), width=1)

        # 3. Panels Layout (Dual column or N columns)
        content_top = divider_y + 14
        content_bottom = self.height - 20
        content_h = content_bottom - content_top
        column_gap = 24
        num_panels = max(1, len(panels))
        available_w = self.width - 2 * margin_x - (num_panels - 1) * column_gap
        column_w = available_w / num_panels

        header_h = 24
        grid_area_h = content_h - header_h

        for idx, panel in enumerate(panels):
            panel_x = margin_x + idx * (column_w + column_gap)
            panel_y = content_top

            # Section Title: e.g. "System libraries*: 90.32% (3480/3853)"
            pct_str = f"{panel.percentage:.2f}%" if panel.percentage < 99.999 else "100.0%"
            section_title = f"{panel.title}: {pct_str} ({panel.total_done}/{panel.total_count})"
            draw.text((panel_x, panel_y), section_title, fill=COLOR_TEXT_WHITE, font=self.font_section)

            # Squarified Treemap for Categories
            tree_rect = Rect(panel_x, panel_y + header_h, column_w, grid_area_h)
            cat_weights = [(cat, cat.weight) for cat in panel.categories]
            laid_out = squarify_rects(cat_weights, tree_rect)

            for cat, box in laid_out:
                if box.w < 2 or box.h < 2:
                    continue

                # Category box boundary
                bx0, by0, bx1, by1 = box.as_box()
                draw.rectangle((bx0, by0, bx1, by1), outline=COLOR_BOX_BORDER, width=1)

                # Category label at top left
                label_h = 16.0
                if box.w >= 20 and box.h >= 20:
                    fnt = self.font_label if box.w >= 36 else self.font_small
                    text = cat.name
                    draw.text((bx0 + 3, by0 + 1), text, fill=COLOR_TEXT_WHITE, font=fnt)
                else:
                    label_h = 2.0

                # Micro tiles with visible 1px borders
                tiles = compute_tile_grid(box, cat.total, cat.done, top_label_height=label_h, padding=2.0, tile_gap=1.0)
                for tile_rect, is_done in tiles:
                    tx0 = int(round(tile_rect.x))
                    ty0 = int(round(tile_rect.y))
                    tx1 = int(round(tile_rect.x + tile_rect.w))
                    ty1 = int(round(tile_rect.y + tile_rect.h))
                    if tx1 <= tx0 or ty1 <= ty0:
                        continue
                    fill_color = COLOR_GREEN if is_done else COLOR_GREY_TILE
                    # Draw filled rectangle with outline to guarantee discrete block appearance
                    draw.rectangle((tx0, ty0, tx1 - 1, ty1 - 1), fill=fill_color, outline=COLOR_BG)

        return img

