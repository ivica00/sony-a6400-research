"""Render the AnyPS5-style telemetry dashboard to ``docs/images/research-status.svg``.

The renderer owns geometry only: every number, label and cell state comes from
``tools.research.a6400_status_data.TELEMETRY`` (which derives them from the evidence
directory, the bounded treemap counters, the recorded suite result and the target
registry). It is deterministic and standard-library only, so the same data renders
byte-for-byte identically on Linux, macOS and Windows.

Text placement is validated while the document is built: a label that would leave the
canvas, cross its panel or overlap another label raises ``ValueError`` instead of
producing a broken picture. ``tests/test_research_status_dashboard.py`` re-parses the
generated SVG and applies the same estimator independently.

Usage::

    python -m tools.research.render_research_status --check   # default, exit 1 on drift
    python -m tools.research.render_research_status --stdout  # print, do not write
    python -m tools.research.render_research_status --write   # rewrite the committed SVG
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path
from xml.sax.saxutils import escape

from tools.research.a6400_status_data import (
    CELL_BOUNDARY,
    CELL_DECODED,
    CELL_UNMAPPED,
    CELL_VERIFIED,
    DAILY_TEST_HISTORY,
    TELEMETRY,
    DailyTestPoint,
    TelemetryDashboard,
)

ROOT = Path(__file__).resolve().parents[2]
STATUS_IMAGE_REL = "docs/images/research-status.svg"
GROWTH_IMAGE_REL = "docs/images/test-growth.svg"
DEFAULT_OUTPUT = ROOT / "docs" / "images" / "research-status.svg"
DEFAULT_GROWTH_OUTPUT = ROOT / "docs" / "images" / "test-growth.svg"

WIDTH = 920
MARGIN = 24
GAP = 20
CONTENT_W = WIDTH - 2 * MARGIN
COL_W = (CONTENT_W - GAP) // 2

COLORS = {
    "bg": "#0d1117",
    "panel": "#161b22",
    "panel_elev": "#1c222b",
    "border": "#30363d",
    "track": "#21262d",
    "text": "#f0f6fc",
    "body": "#c9d1d9",
    "muted": "#8b949e",
    "dim": "#9da7b3",
    "green": "#2ea043",
    "green_bright": "#3fb950",
    "cyan": "#39c5cf",
    "blue": "#1f6feb",
    "blue_bright": "#58a6ff",
    "amber": "#d29922",
    "amber_bright": "#f0883e",
    "violet": "#8957e5",
    "violet_bright": "#bc8cff",
    "white": "#ffffff",
}

TONE_COLORS = {
    "green": COLORS["green"],
    "blue": COLORS["blue"],
    "amber": COLORS["amber"],
    "violet": COLORS["violet"],
}

STATE_COLORS = {
    CELL_VERIFIED: COLORS["green"],
    CELL_DECODED: COLORS["blue"],
    CELL_BOUNDARY: COLORS["amber"],
    CELL_UNMAPPED: COLORS["track"],
}

SANS = "Segoe UI, Arial, sans-serif"
MONO = "Consolas, 'Courier New', monospace"

FAMILIES = {"sans": SANS, "mono": MONO}
WIDTH_FACTORS = {"sans": 0.56, "mono": 0.62}

# Cell grid geometry.
CELL_SIZE = 13
CELL_GAP = 3
CELL_PITCH = CELL_SIZE + CELL_GAP
PANEL_PAD = 16
PANEL_HEADER_H = 46
GROUP_HEADER_H = 24

OVERLAP_PAD = 1.0


def estimate_text_width(value: str, size: float, family: str = "sans", weight: int = 400) -> float:
    """Conservative text-width estimate shared by the renderer and its tests."""
    factor = WIDTH_FACTORS[family]
    if weight >= 600:
        factor *= 1.04
    return len(value) * size * factor


def text_box(
    x: float,
    baseline: float,
    value: str,
    size: float,
    family: str = "sans",
    weight: int = 400,
    anchor: str = "start",
):
    """Bounding box for a text baseline, using the renderer's own estimator."""
    width = estimate_text_width(value, size, family, weight)
    if anchor == "end":
        x0 = x - width
    elif anchor == "middle":
        x0 = x - width / 2.0
    else:
        x0 = x
    top = baseline - size * 0.78
    bottom = baseline + size * 0.24
    return (x0, top, x0 + width, bottom)


class Layout:
    """Accumulates SVG elements and fails closed on any text collision."""

    def __init__(self) -> None:
        self.elements: list[str] = []
        self._text_boxes: list[tuple[float, float, float, float, str]] = []
        self._lowest = 0.0

    # -- primitives ---------------------------------------------------------
    def rect(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        fill: str,
        stroke: str | None = None,
        rx: float = 6,
        stroke_width: float = 1,
        opacity: float | None = None,
    ) -> None:
        attrs = [f'x="{x:g}"', f'y="{y:g}"', f'width="{w:g}"', f'height="{h:g}"', f'rx="{rx:g}"', f'fill="{fill}"']
        if stroke is not None:
            attrs += [f'stroke="{stroke}"', f'stroke-width="{stroke_width:g}"']
        if opacity is not None:
            attrs.append(f'opacity="{opacity:g}"')
        self.elements.append(f"<rect {' '.join(attrs)} />")
        self._lowest = max(self._lowest, y + h)

    def line(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        stroke: str,
        stroke_width: float = 1,
        dasharray: str | None = None,
        opacity: float | None = None,
    ) -> None:
        attrs = [
            f'x1="{x1:g}"',
            f'y1="{y1:g}"',
            f'x2="{x2:g}"',
            f'y2="{y2:g}"',
            f'stroke="{stroke}"',
            f'stroke-width="{stroke_width:g}"',
        ]
        if dasharray is not None:
            attrs.append(f'stroke-dasharray="{dasharray}"')
        if opacity is not None:
            attrs.append(f'opacity="{opacity:g}"')
        self.elements.append(f"<line {' '.join(attrs)} />")
        self._lowest = max(self._lowest, y1, y2)

    def path(
        self,
        d: str,
        fill: str = "none",
        stroke: str | None = None,
        stroke_width: float = 2,
        stroke_linecap: str | None = None,
        stroke_linejoin: str | None = None,
        filter_id: str | None = None,
        opacity: float | None = None,
    ) -> None:
        attrs = [f'd="{d}"', f'fill="{fill}"']
        if stroke is not None:
            attrs += [f'stroke="{stroke}"', f'stroke-width="{stroke_width:g}"']
        if stroke_linecap is not None:
            attrs.append(f'stroke-linecap="{stroke_linecap}"')
        if stroke_linejoin is not None:
            attrs.append(f'stroke-linejoin="{stroke_linejoin}"')
        if filter_id is not None:
            attrs.append(f'filter="url(#{filter_id})"')
        if opacity is not None:
            attrs.append(f'opacity="{opacity:g}"')
        self.elements.append(f"<path {' '.join(attrs)} />")

    def circle(
        self,
        cx: float,
        cy: float,
        r: float,
        fill: str,
        stroke: str | None = None,
        stroke_width: float = 1.5,
        opacity: float | None = None,
    ) -> None:
        attrs = [f'cx="{cx:g}"', f'cy="{cy:g}"', f'r="{r:g}"', f'fill="{fill}"']
        if stroke is not None:
            attrs += [f'stroke="{stroke}"', f'stroke-width="{stroke_width:g}"']
        if opacity is not None:
            attrs.append(f'opacity="{opacity:g}"')
        self.elements.append(f"<circle {' '.join(attrs)} />")
        self._lowest = max(self._lowest, cy + r)

    def text(
        self,
        x: float,
        baseline: float,
        value: str,
        size: float = 10.5,
        weight: int = 400,
        fill: str = COLORS["body"],
        family: str = "sans",
        anchor: str = "start",
        max_x: float | None = None,
    ) -> None:
        left, top, right, bottom = text_box(x, baseline, value, size, family, weight, anchor)
        limit_x = WIDTH - MARGIN if max_x is None else max_x
        if left < MARGIN - 4 or right > limit_x + 0.5:
            raise ValueError(
                f"text overflows its slot: {value!r} at x={x:g} "
                f"(spans {left:.1f}..{right:.1f}, limit {limit_x:.1f})"
            )
        for other_left, other_top, other_right, other_bottom, other_value in self._text_boxes:
            overlaps = (
                left < other_right + OVERLAP_PAD
                and right > other_left - OVERLAP_PAD
                and top < other_bottom + OVERLAP_PAD
                and bottom > other_top - OVERLAP_PAD
            )
            if overlaps:
                raise ValueError(f"text overlap between {value!r} and {other_value!r}")
        self._text_boxes.append((left, top, right, bottom, value))
        self.elements.append(
            f'<text x="{x:g}" y="{baseline:g}" fill="{fill}" font-size="{size:g}" '
            f'font-weight="{weight}" font-family="{FAMILIES[family]}" text-anchor="{anchor}">'
            f"{escape(value)}</text>"
        )
        self._lowest = max(self._lowest, bottom)

    # -- composite rules ----------------------------------------------------
    def panel(self, x: float, y: float, w: float, h: float) -> None:
        self.rect(x, y, w, h, COLORS["panel"], COLORS["border"], rx=8)

    def badge(self, right_x: float, baseline: float, value: str) -> None:
        size = 10.5
        width = estimate_text_width(value, size, "mono") + 18
        self.rect(right_x - width, baseline - 16, width, 22, COLORS["panel"], COLORS["border"], rx=11)
        self.text(right_x - 9, baseline, value, size=size, fill=COLORS["body"], family="mono", anchor="end", max_x=right_x)

    def pill(self, x: float, y: float, label: str, value: str, tone: str) -> float:
        size = 10.5
        label_w = estimate_text_width(label, size) + 18
        value_w = estimate_text_width(value, size, weight=700) + 18
        total = label_w + value_w
        self.rect(x, y, total, 26, COLORS["track"], COLORS["border"], rx=5)
        self.rect(x + label_w, y, value_w, 26, TONE_COLORS[tone], rx=5)
        self.text(x + 9, y + 17, label, size=size, fill=COLORS["body"], max_x=x + label_w - 3)
        self.text(x + label_w + 9, y + 17, value, size=size, weight=700, fill=COLORS["white"], max_x=x + total - 3)
        return total

    def cells(self, x: float, y: float, cells, per_row: int) -> int:
        for index, state in enumerate(cells):
            row, col = divmod(index, per_row)
            cx = x + col * CELL_PITCH
            cy = y + row * CELL_PITCH
            if state == CELL_UNMAPPED:
                self.rect(cx, cy, CELL_SIZE, CELL_SIZE, STATE_COLORS[state], COLORS["border"], rx=2, stroke_width=1)
            else:
                self.rect(cx, cy, CELL_SIZE, CELL_SIZE, STATE_COLORS[state], rx=2)
        rows = (len(cells) + per_row - 1) // per_row
        self._lowest = max(self._lowest, y + rows * CELL_PITCH)
        return rows

    def legend_item(self, x: float, y: float, state: str, label: str) -> float:
        self.rect(x, y - 9, 10, 10, STATE_COLORS[state], COLORS["border"] if state == CELL_UNMAPPED else None, rx=2)
        self.text(x + 16, y, label, size=9.5, fill=COLORS["body"])
        return 16 + estimate_text_width(label, 9.5) + 22


def _cells_per_row(panel_w: int) -> int:
    inner = panel_w - 2 * PANEL_PAD
    return max(1, (inner + CELL_GAP) // CELL_PITCH)


def _group_rows(group, per_row: int) -> int:
    return (len(group.cells) + per_row - 1) // per_row


def _groups_height(groups, per_row: int) -> int:
    return sum(GROUP_HEADER_H + _group_rows(group, per_row) * CELL_PITCH + 10 for group in groups)


def _draw_panel_header(layout: Layout, x: float, y: float, title: str, subtitle: str) -> None:
    layout.text(x + PANEL_PAD, y + 22, title, size=12, weight=700, fill=COLORS["text"])
    layout.text(x + PANEL_PAD, y + 38, subtitle, size=8.5, fill=COLORS["muted"])


def _draw_cell_groups(layout: Layout, x: float, y: float, w: float, groups) -> None:
    per_row = _cells_per_row(w)
    inner_x = x + PANEL_PAD
    cursor = y
    for group in groups:
        counts = group.summary()
        counts_w = estimate_text_width(counts, 9, "mono")
        layout.text(
            inner_x,
            cursor + 11,
            group.title,
            size=10,
            weight=600,
            fill=COLORS["text"],
            max_x=x + w - PANEL_PAD - counts_w - 12,
        )
        layout.text(x + w - PANEL_PAD, cursor + 11, counts, size=9, fill=COLORS["muted"], family="mono", anchor="end")
        layout.text(inner_x, cursor + 21, f"source: {group.source}", size=8, fill=COLORS["dim"], max_x=x + w - PANEL_PAD)
        cursor += GROUP_HEADER_H
        layout.cells(inner_x, cursor, group.cells, per_row)
        cursor += _group_rows(group, per_row) * CELL_PITCH + 10


def _draw_contract_bars(layout: Layout, x: float, y: float, w: float, bars) -> None:
    inner_x = x + PANEL_PAD
    track_w = w - 2 * PANEL_PAD
    cursor = y
    for bar in bars:
        layout.text(inner_x, cursor + 10, bar.label, size=10, fill=COLORS["body"])
        layout.text(x + w - PANEL_PAD, cursor + 10, bar.detail, size=9.5, fill=COLORS["muted"], family="mono", anchor="end")
        track_y = cursor + 16
        layout.rect(inner_x, track_y, track_w, 7, COLORS["track"], rx=3.5)
        done_w = track_w * bar.done / bar.total
        if done_w > 0:
            layout.rect(inner_x, track_y, done_w, 7, COLORS["green"], rx=3.5)
        amber_w = track_w * bar.amber / bar.total
        if amber_w > 0:
            layout.rect(inner_x + done_w, track_y, amber_w, 7, COLORS["amber"], rx=3.5)
        cursor += 30


def _draw_boundary_bars(layout: Layout, x: float, y: float, w: float, groups) -> None:
    inner_x = x + PANEL_PAD
    track_w = w - 2 * PANEL_PAD
    largest = max(group.count for group in groups)
    cursor = y
    for group in groups:
        detail = f"{group.count} open"
        detail_w = estimate_text_width(detail, 9.5, "mono")
        layout.text(inner_x, cursor + 10, group.label, size=10, fill=COLORS["body"],
                    max_x=x + w - PANEL_PAD - detail_w - 12)
        layout.text(x + w - PANEL_PAD, cursor + 10, detail, size=9.5, fill=COLORS["amber"], family="mono", anchor="end")
        track_y = cursor + 16
        layout.rect(inner_x, track_y, track_w, 7, COLORS["track"], rx=3.5)
        layout.rect(inner_x, track_y, track_w * group.count / largest, 7, COLORS["amber"], rx=3.5)
        cursor += 30


def _pill_width(pill) -> float:
    return estimate_text_width(pill.label, 10.5) + estimate_text_width(pill.value, 10.5, weight=700) + 36


def _pill_rows(pills) -> list[list]:
    """Greedy wrap, then rebalance so the last row is not a single orphan pill."""
    rows: list[list] = []
    current: list = []
    used = 0.0
    for pill in pills:
        width = _pill_width(pill)
        extra = width + (8.0 if current else 0.0)
        if current and used + extra > CONTENT_W:
            rows.append(current)
            current = [pill]
            used = width
        else:
            current.append(pill)
            used += extra
    if current:
        rows.append(current)
    while len(rows) > 1 and len(rows[-1]) == 1 and len(rows[-2]) > 1:
        moved = rows[-2].pop()
        rows[-1].insert(0, moved)
    return rows


def render_svg(dashboard: TelemetryDashboard = TELEMETRY) -> str:
    """Return the complete dashboard SVG document (no I/O)."""
    layout = Layout()

    # ---------------------------------------------------------------- header
    top = 20
    layout.text(MARGIN, top + 18, dashboard.title, size=21, weight=700, fill=COLORS["text"])
    layout.text(MARGIN, top + 34, dashboard.subtitle, size=9, fill=COLORS["dim"])
    layout.badge(WIDTH - MARGIN, top + 18, f"{dashboard.as_of} | {dashboard.latest_evidence}")

    # ------------------------------------------------------------ KPI pills
    pills_top = top + 48
    pill_bottom = pills_top
    for row_index, row in enumerate(_pill_rows(dashboard.pills)):
        pill_y = pills_top + row_index * (26 + 6)
        pill_x = MARGIN
        for pill in row:
            pill_x += layout.pill(pill_x, pill_y, pill.label, pill.value, pill.tone) + 8
        pill_bottom = pill_y + 26

    # ------------------------------------------------------- middle panels
    middle_top = pill_bottom + 18
    per_row = _cells_per_row(COL_W)
    left_content = _groups_height(dashboard.firmware_groups, per_row)
    right_content = _groups_height(dashboard.pipeline_groups, per_row)
    middle_h = PANEL_HEADER_H + max(left_content, right_content) + 14
    left_x, right_x = MARGIN, MARGIN + COL_W + GAP
    layout.panel(left_x, middle_top, COL_W, middle_h)
    layout.panel(right_x, middle_top, COL_W, middle_h)
    _draw_panel_header(layout, left_x, middle_top, "Firmware & Subsystem Contract Map", "bounded inventory · cell = tracked item")
    _draw_panel_header(layout, right_x, middle_top, "UVC / PTP / Teardown Pipeline Cells", "bounded pipeline inventory")
    _draw_cell_groups(layout, left_x, middle_top + PANEL_HEADER_H, COL_W, dashboard.firmware_groups)
    _draw_cell_groups(layout, right_x, middle_top + PANEL_HEADER_H, COL_W, dashboard.pipeline_groups)
    layout.text(
        right_x + PANEL_PAD,
        middle_top + middle_h - 12,
        dashboard.pipeline_summary,
        size=9,
        fill=COLORS["muted"],
        max_x=right_x + COL_W - PANEL_PAD,
    )

    # ------------------------------------------------------- bottom panels
    bottom_top = middle_top + middle_h + 18
    bars_content = len(dashboard.contract_bars) * 30
    boundary_content = len(dashboard.boundaries) * 30
    bottom_h = PANEL_HEADER_H + max(bars_content, boundary_content) + 20
    layout.panel(left_x, bottom_top, COL_W, bottom_h)
    layout.panel(right_x, bottom_top, COL_W, bottom_h)
    _draw_panel_header(layout, left_x, bottom_top, "Verified Contracts by Subsystem", "bounded ratios · green = verified, amber = active")
    _draw_panel_header(layout, right_x, bottom_top, "Open Boundaries by Area", "tracked gates · sorted by count")
    _draw_contract_bars(layout, left_x, bottom_top + PANEL_HEADER_H, COL_W, dashboard.contract_bars)
    _draw_boundary_bars(layout, right_x, bottom_top + PANEL_HEADER_H, COL_W, dashboard.boundaries)
    total_open = sum(group.count for group in dashboard.boundaries)
    layout.text(
        right_x + PANEL_PAD,
        bottom_top + bottom_h - 12,
        f"{total_open} tracked open boundaries across {len(dashboard.boundaries)} areas",
        size=9,
        fill=COLORS["muted"],
        max_x=right_x + COL_W - PANEL_PAD,
    )

    # ------------------------------------------------------ legend + footer
    legend_top = bottom_top + bottom_h + 24
    legend_x = MARGIN
    for state, label in dashboard.legend:
        legend_x += layout.legend_item(legend_x, legend_top, state, label)
    layout.text(MARGIN, legend_top + 24, dashboard.footnote, size=9.5, fill=COLORS["dim"])

    height = int(round(layout._lowest + 20))

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{height}" '
        f'viewBox="0 0 {WIDTH} {height}" role="img" aria-labelledby="title desc">',
        f'<title id="title">{escape(dashboard.title)} — {dashboard.as_of} | {dashboard.latest_evidence}</title>',
        f'<desc id="desc">{escape(dashboard.description())}</desc>',
        f'<rect width="{WIDTH}" height="{height}" rx="16" fill="{COLORS["bg"]}" />',
        "<g>",
        *layout.elements,
        "</g>",
        "</svg>",
    ]
    return "\n".join(lines) + "\n"


def _monotone_cubic_path(points: list[tuple[float, float]]) -> str:
    """Return an SVG smooth monotone cubic Bezier path through ``points``."""
    n = len(points)
    if n == 0:
        return ""
    if n == 1:
        return f"M {points[0][0]:.2f} {points[0][1]:.2f}"
    if n == 2:
        return (
            f"M {points[0][0]:.2f} {points[0][1]:.2f} "
            f"L {points[1][0]:.2f} {points[1][1]:.2f}"
        )

    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    dx = [xs[i + 1] - xs[i] for i in range(n - 1)]
    dy = [ys[i + 1] - ys[i] for i in range(n - 1)]
    slopes = [dy[i] / dx[i] if dx[i] != 0 else 0.0 for i in range(n - 1)]

    tangents = [0.0] * n
    tangents[0] = slopes[0]
    tangents[-1] = slopes[-1]
    for i in range(1, n - 1):
        if slopes[i - 1] * slopes[i] <= 0.0:
            tangents[i] = 0.0
        else:
            w1 = 2.0 * dx[i] + dx[i - 1]
            w2 = dx[i] + 2.0 * dx[i - 1]
            tangents[i] = (w1 + w2) / (w1 / slopes[i - 1] + w2 / slopes[i])

    # Fritsch-Carlson clamping prevents overshoot on plateaus or sharp steps.
    for i in range(n - 1):
        if slopes[i] == 0.0:
            tangents[i] = 0.0
            tangents[i + 1] = 0.0
        else:
            alpha = tangents[i] / slopes[i]
            beta = tangents[i + 1] / slopes[i]
            hypot = (alpha * alpha + beta * beta) ** 0.5
            if hypot > 3.0:
                scale = 3.0 / hypot
                tangents[i] = scale * alpha * slopes[i]
                tangents[i + 1] = scale * beta * slopes[i]

    cmds = [f"M {xs[0]:.2f} {ys[0]:.2f}"]
    for i in range(n - 1):
        seg = dx[i] / 3.0
        c1x = xs[i] + seg
        c1y = ys[i] + tangents[i] * seg
        c2x = xs[i + 1] - seg
        c2y = ys[i + 1] - tangents[i + 1] * seg
        cmds.append(
            f"C {c1x:.2f} {c1y:.2f}, {c2x:.2f} {c2y:.2f}, {xs[i + 1]:.2f} {ys[i + 1]:.2f}"
        )
    return " ".join(cmds)


def _format_short_date(iso_date: str) -> str:
    months = {
        "10": "Oct",
        "11": "Nov",
        "12": "Dec",
        "01": "Jan",
    }
    _year, month, day = iso_date.split("-")
    return f"{months.get(month, month)} {int(day):02d}"


def _delta_bar_fill(delta: int) -> str:
    if delta >= 300:
        return "url(#tg-bar-peak)"
    if delta >= 150:
        return "url(#tg-bar-emerald)"
    if delta >= 40:
        return "url(#tg-bar-amber)"
    return "url(#tg-bar-blue)"


def _cadence_cell_fill(delta: int) -> tuple[str, str | None]:
    if delta == 0:
        return (COLORS["track"], COLORS["border"])
    if delta < 40:
        return (COLORS["blue_bright"], None)
    if delta < 150:
        return (COLORS["amber_bright"], None)
    if delta < 300:
        return (COLORS["green_bright"], None)
    return (COLORS["violet_bright"], None)


def render_test_growth_svg(
    history: tuple[DailyTestPoint, ...] = DAILY_TEST_HISTORY,
) -> str:
    """Render the modern daily test growth & velocity chart to SVG (no I/O)."""
    if not history:
        raise ValueError("history must not be empty")

    layout = Layout()
    first = history[0]
    latest = history[-1]
    total_days = len(history)
    active_days = sum(1 for item in history if item.delta > 0)
    peak_day = max(history, key=lambda item: item.delta)
    net_gain = latest.total - first.total
    last_7 = history[-7:]
    seven_day_gain = sum(item.delta for item in last_7)
    seven_day_avg = seven_day_gain / len(last_7)

    # ---------------------------------------------------------------- header
    top = 20
    layout.text(
        MARGIN,
        top + 18,
        "Automated Test Suite Growth & Daily Velocity",
        size=19,
        weight=700,
        fill=COLORS["text"],
    )
    layout.text(
        MARGIN,
        top + 34,
        (
            f"Daily cumulative offline checks & net additions · {first.date} to {latest.date} "
            f"({total_days} days · deterministic suite)"
        ),
        size=8.8,
        fill=COLORS["dim"],
    )

    badge_val = f"{latest.date} | {latest.total:,} PASSING"
    badge_w = estimate_text_width(badge_val, 10, "mono", 700) + 34
    badge_x = WIDTH - MARGIN - badge_w
    layout.rect(badge_x, top + 2, badge_w, 24, COLORS["panel_elev"], COLORS["border"], rx=12)
    layout.circle(badge_x + 13, top + 14, 6.5, COLORS["green_bright"], opacity=0.20)
    layout.circle(badge_x + 13, top + 14, 3.5, COLORS["green_bright"])
    layout.text(
        WIDTH - MARGIN - 11,
        top + 17.5,
        badge_val,
        size=10,
        weight=700,
        fill=COLORS["text"],
        family="mono",
        anchor="end",
        max_x=WIDTH - MARGIN,
    )

    # ------------------------------------------------------- KPI metric cards
    cards_y = top + 50
    card_h = 68
    card_w = 164
    card_gap = 13
    kpis = (
        ("CURRENT SUITE", f"{latest.total:,}", f"+{latest.delta} today · {latest.evidence_id}", COLORS["green_bright"]),
        ("NET EXPANSION", f"+{net_gain:,}", f"{first.total} -> {latest.total:,} ({total_days}d)", COLORS["cyan"]),
        ("PEAK DAY SURGE", f"+{peak_day.delta}", f"{peak_day.date} · {peak_day.evidence_id}", COLORS["violet_bright"]),
        ("7-DAY VELOCITY", f"+{seven_day_gain:,}", f"avg +{seven_day_avg:.1f}/d · Nov 08-14", COLORS["amber_bright"]),
        ("ACTIVE CADENCE", f"{active_days} / {total_days}d", f"{latest.evidence_id} evidence track", COLORS["blue_bright"]),
    )
    for idx, (label, metric, sub, accent) in enumerate(kpis):
        cx = MARGIN + idx * (card_w + card_gap)
        layout.rect(cx, cards_y, card_w, card_h, "url(#tg-card-bg)", COLORS["border"], rx=8)
        layout.rect(cx + 1, cards_y + 1, card_w - 2, 3, accent, rx=1.5)
        layout.text(
            cx + 12,
            cards_y + 20,
            label,
            size=8.2,
            weight=700,
            fill=COLORS["muted"],
            max_x=cx + card_w - 8,
        )
        layout.text(
            cx + 12,
            cards_y + 43,
            metric,
            size=17,
            weight=700,
            fill=COLORS["text"],
            family="mono",
            max_x=cx + card_w - 8,
        )
        layout.text(
            cx + 12,
            cards_y + 59,
            sub,
            size=8.2,
            fill=accent,
            max_x=cx + card_w - 8,
        )

    # ---------------------------------------------------- dual-layer combo plot
    chart_panel_y = cards_y + card_h + 16
    chart_panel_h = 376
    layout.panel(MARGIN, chart_panel_y, CONTENT_W, chart_panel_h)
    layout.text(
        MARGIN + PANEL_PAD,
        chart_panel_y + 22,
        "Cumulative Test Trajectory & Daily Additions",
        size=12,
        weight=700,
        fill=COLORS["text"],
    )
    layout.text(
        MARGIN + PANEL_PAD,
        chart_panel_y + 38,
        "Smooth monotone curve (left axis) · daily net delta bars (lower band) · 3 project phases",
        size=8.5,
        fill=COLORS["muted"],
    )

    # Inline legend on top-right of panel header
    legend_x = 550
    legend_y = chart_panel_y + 22
    layout.line(legend_x, legend_y - 3, legend_x + 15, legend_y - 3, COLORS["green_bright"], stroke_width=2.5)
    layout.circle(legend_x + 7.5, legend_y - 3, 2.6, COLORS["green_bright"])
    layout.text(legend_x + 20, legend_y, "Cumulative", size=8.2, fill=COLORS["body"])

    bar_leg_x = legend_x + 78
    for swatch_c, swatch_lbl in (
        (COLORS["blue_bright"], "+1..39"),
        (COLORS["amber_bright"], "+40..149"),
        (COLORS["green_bright"], "+150..299"),
        (COLORS["violet_bright"], "+300+"),
    ):
        layout.rect(bar_leg_x, legend_y - 7.5, 8, 8, swatch_c, rx=2)
        layout.text(bar_leg_x + 12, legend_y, swatch_lbl, size=8.0, fill=COLORS["muted"], family="mono")
        bar_leg_x += 12 + estimate_text_width(swatch_lbl, 8.0, "mono") + 10

    plot_x = 70
    plot_right = 876
    plot_w = plot_right - plot_x
    plot_y = chart_panel_y + 52
    y_top = plot_y + 24
    y_bot = plot_y + 264
    chart_h = y_bot - y_top
    y_max = 2000.0
    step_x = plot_w / total_days

    # Micro-grid & frame inside plot
    layout.rect(plot_x, plot_y, plot_w, y_bot - plot_y, "url(#tg-grid)", COLORS["border"], rx=6)

    # Three phase bands across the 28-day timeline
    phases = (
        (0, 18, "PHASE I · CORE LOADER, FS & GLES", COLORS["blue"]),
        (18, 24, "PHASE II · DEBUGGER & UVC", COLORS["cyan"]),
        (24, 28, "PHASE III · KERNEL BOOT", COLORS["violet"]),
    )
    for start_idx, end_idx, label, tint in phases:
        bx0 = plot_x + start_idx * step_x
        bw = (end_idx - start_idx) * step_x
        layout.rect(bx0, plot_y, bw, y_bot - plot_y, tint, rx=0, opacity=0.045)
        layout.rect(bx0, plot_y, bw, 22, tint, rx=0, opacity=0.08)
        if start_idx > 0:
            layout.line(bx0, plot_y, bx0, y_bot, COLORS["border"], stroke_width=1, dasharray="3 3")
        layout.text(
            bx0 + bw / 2.0,
            plot_y + 14,
            label,
            size=7.6,
            weight=700,
            fill=COLORS["dim"],
            anchor="middle",
            max_x=bx0 + bw - 2,
        )

    # Horizontal gridlines & left Y-axis ticks
    for tick in (0, 400, 800, 1200, 1600, 2000):
        ty = y_bot - (tick / y_max) * chart_h
        layout.line(
            plot_x,
            ty,
            plot_right,
            ty,
            COLORS["border"],
            stroke_width=1 if tick == 0 else 0.75,
            dasharray=None if tick == 0 else "2 4",
            opacity=0.85 if tick == 0 else 0.55,
        )
        layout.text(
            plot_x - 8,
            ty + 3,
            f"{tick:,}",
            size=8.5,
            fill=COLORS["muted"],
            family="mono",
            anchor="end",
            max_x=plot_x - 4,
        )

    # Compute node & bar geometry
    max_delta = max(item.delta for item in history)
    max_bar_h = 86.0
    bar_w = 16.0
    coords: list[tuple[float, float]] = []
    for idx, item in enumerate(history):
        cx = plot_x + (idx + 0.5) * step_x
        cy = y_bot - (item.total / y_max) * chart_h
        coords.append((cx, cy))

    # Draw daily addition bars in the lower band
    for idx, item in enumerate(history):
        cx = coords[idx][0]
        if item.delta <= 0:
            layout.rect(cx - bar_w / 2.0, y_bot - 2, bar_w, 2, COLORS["border"], rx=1, opacity=0.7)
            continue
        bh = max(4.0, (item.delta / max_delta) * max_bar_h)
        by = y_bot - bh
        layout.rect(cx - bar_w / 2.0, by, bar_w, bh, _delta_bar_fill(item.delta), rx=3, opacity=0.82)
        # Annotate prominent surge bars where there is ample clearance below the curve
        if item.delta >= 100 and by - 14 > coords[idx][1] + 12:
            layout.text(
                cx,
                by - 5,
                f"+{item.delta}",
                size=7.6,
                weight=700,
                fill=COLORS["amber_bright"] if item.delta < 300 else COLORS["violet_bright"],
                family="mono",
                anchor="middle",
                max_x=plot_right,
            )

    # Cumulative area fill + smooth glowing curve
    curve_d = _monotone_cubic_path(coords)
    area_d = f"{curve_d} L {coords[-1][0]:.2f} {y_bot:.2f} L {coords[0][0]:.2f} {y_bot:.2f} Z"
    layout.path(area_d, fill="url(#tg-area-grad)")
    layout.path(
        curve_d,
        stroke="url(#tg-line-grad)",
        stroke_width=3.0,
        stroke_linecap="round",
        stroke_linejoin="round",
        filter_id="tg-glow",
    )

    # Data nodes along the cumulative trajectory
    milestone_indices = {0, 6, 15, 20, 22, 24, 25, 26, 27}
    for idx, (cx, cy) in enumerate(coords):
        item = history[idx]
        if idx == len(coords) - 1:
            layout.circle(cx, cy, 9.0, COLORS["green_bright"], opacity=0.22)
            layout.circle(cx, cy, 4.8, COLORS["green_bright"], stroke=COLORS["bg"], stroke_width=2.0)
        elif idx in milestone_indices:
            ring_color = COLORS["violet_bright"] if item.delta >= 300 else COLORS["green_bright"]
            layout.circle(cx, cy, 3.8, ring_color, stroke=COLORS["bg"], stroke_width=1.5)
        elif item.delta > 0:
            layout.circle(cx, cy, 2.3, COLORS["cyan"], stroke=COLORS["bg"], stroke_width=1.0)
        else:
            layout.circle(cx, cy, 1.8, COLORS["muted"], opacity=0.7)

    # Milestone callout annotations (staggered with zero overlap)
    callouts = (
        (0, "204", 0, -25, "middle"),
        (6, "446", 0, -12, "middle"),
        (15, "498", 0, -12, "middle"),
        (20, "599", 0, -12, "middle"),
        (22, "778", 0, -12, "middle"),
        (24, "1,312", -18, 2, "end"),
        (25, "1,510", -18, 2, "end"),
        (26, "1,727", -18, 5, "end"),
    )
    for idx, label, dx, dy, anchor in callouts:
        nx, ny = coords[idx]
        if dx < 0:
            layout.line(nx - 5, ny, nx + dx + 3, ny + dy - 2, COLORS["muted"], stroke_width=0.9, opacity=0.7)
        layout.text(
            nx + dx,
            ny + dy,
            label,
            size=8.4,
            weight=700,
            fill=COLORS["text"],
            family="mono",
            anchor=anchor,
            max_x=plot_right,
        )

    # Highlighted terminal pill for 1,895
    end_x, end_y = coords[-1]
    pill_w = 48
    pill_x = end_x - pill_w - 14
    pill_y = end_y - 13
    layout.rect(pill_x, pill_y, pill_w, 18, COLORS["green"], COLORS["green_bright"], rx=5)
    layout.text(
        pill_x + pill_w / 2.0,
        pill_y + 12.2,
        f"{latest.total:,}",
        size=8.8,
        weight=700,
        fill=COLORS["white"],
        family="mono",
        anchor="middle",
        max_x=pill_x + pill_w,
    )

    # X-axis day-of-month ticks & month brackets
    oct_nov_split = plot_x + 14 * step_x
    layout.line(oct_nov_split, y_bot, oct_nov_split, y_bot + 26, COLORS["border"], stroke_width=1)
    for idx, item in enumerate(history):
        cx = coords[idx][0]
        day_num = item.date.split("-")[2]
        layout.line(cx, y_bot, cx, y_bot + 4, COLORS["border"], stroke_width=1)
        layout.text(
            cx,
            y_bot + 15,
            day_num,
            size=7.8,
            weight=600 if item.delta > 0 else 400,
            fill=COLORS["body"] if item.delta > 0 else COLORS["muted"],
            family="mono",
            anchor="middle",
            max_x=plot_right + 10,
        )

    layout.text(
        plot_x + 7 * step_x,
        y_bot + 30,
        "OCTOBER 2026",
        size=8.0,
        weight=700,
        fill=COLORS["muted"],
        anchor="middle",
    )
    layout.text(
        plot_x + 21 * step_x,
        y_bot + 30,
        "NOVEMBER 2026",
        size=8.0,
        weight=700,
        fill=COLORS["muted"],
        anchor="middle",
    )

    # ------------------------------------------------- 28-day chronological ledger
    ledger_panel_y = chart_panel_y + chart_panel_h + 16
    ledger_panel_h = 256
    layout.panel(MARGIN, ledger_panel_y, CONTENT_W, ledger_panel_h)
    layout.text(
        MARGIN + PANEL_PAD,
        ledger_panel_y + 22,
        "Complete 28-Day Chronological Ledger",
        size=12,
        weight=700,
        fill=COLORS["text"],
    )
    layout.text(
        MARGIN + PANEL_PAD,
        ledger_panel_y + 38,
        "Every day since project start (2026-10-18) · cumulative total, daily net delta (+), and anchor evidence",
        size=8.5,
        fill=COLORS["muted"],
    )

    # Cadence intensity legend on top-right of ledger panel
    cadence_items = (
        (COLORS["track"], COLORS["border"], "+0"),
        (COLORS["blue_bright"], None, "+1..39"),
        (COLORS["amber_bright"], None, "+40..149"),
        (COLORS["green_bright"], None, "+150..299"),
        (COLORS["violet_bright"], None, "+300+"),
    )
    cad_x = 588
    cad_y = ledger_panel_y + 21
    for fill_c, stroke_c, lbl in cadence_items:
        layout.rect(cad_x, cad_y - 8, 9, 9, fill_c, stroke_c, rx=2)
        layout.text(cad_x + 13, cad_y, lbl, size=8.0, fill=COLORS["muted"], family="mono")
        cad_x += 13 + estimate_text_width(lbl, 8.0, "mono") + 10

    # 28-cell daily cadence strip
    strip_x = MARGIN + PANEL_PAD
    strip_y = ledger_panel_y + 49
    cell_w = 26
    cell_gap = 4
    for idx, item in enumerate(history):
        fill_c, stroke_c = _cadence_cell_fill(item.delta)
        layout.rect(strip_x + idx * (cell_w + cell_gap), strip_y, cell_w, 12, fill_c, stroke_c, rx=3)

    # 4-column x 7-row daily table
    grid_x = MARGIN + PANEL_PAD
    grid_y = strip_y + 22
    col_w = 201
    col_gap = 12
    row_h = 20
    for col in range(4):
        cx = grid_x + col * (col_w + col_gap)
        layout.rect(cx, grid_y, col_w, 18, COLORS["track"], rx=4)
        layout.text(cx + 8, grid_y + 12, "DATE", size=7.4, weight=700, fill=COLORS["muted"], family="mono", max_x=cx + 55)
        layout.text(cx + 92, grid_y + 12, "TOTAL", size=7.4, weight=700, fill=COLORS["muted"], family="mono", anchor="end", max_x=cx + 96)
        layout.text(cx + 144, grid_y + 12, "+DAY", size=7.4, weight=700, fill=COLORS["muted"], family="mono", anchor="end", max_x=cx + 148)
        layout.text(cx + 193, grid_y + 12, "REF", size=7.4, weight=700, fill=COLORS["muted"], family="mono", anchor="end", max_x=cx + col_w)

        for row in range(7):
            item_idx = col * 7 + row
            if item_idx >= total_days:
                continue
            item = history[item_idx]
            ry = grid_y + 20 + row * row_h
            if row % 2 == 1:
                layout.rect(cx, ry, col_w, row_h - 1, COLORS["panel_elev"], rx=3, opacity=0.7)
            if item.delta >= 300:
                delta_color = COLORS["violet_bright"]
            elif item.delta >= 150:
                delta_color = COLORS["green_bright"]
            elif item.delta >= 40:
                delta_color = COLORS["amber_bright"]
            elif item.delta > 0:
                delta_color = COLORS["blue_bright"]
            else:
                delta_color = COLORS["muted"]

            layout.text(
                cx + 8,
                ry + 13,
                _format_short_date(item.date),
                size=8.2,
                fill=COLORS["body"],
                family="mono",
                max_x=cx + 58,
            )
            layout.text(
                cx + 92,
                ry + 13,
                f"{item.total:,}",
                size=8.2,
                weight=600,
                fill=COLORS["text"],
                family="mono",
                anchor="end",
                max_x=cx + 96,
            )
            layout.text(
                cx + 144,
                ry + 13,
                f"+{item.delta}",
                size=8.2,
                weight=600 if item.delta > 0 else 400,
                fill=delta_color,
                family="mono",
                anchor="end",
                max_x=cx + 148,
            )
            layout.text(
                cx + 193,
                ry + 13,
                item.evidence_id,
                size=8.0,
                fill=COLORS["muted"],
                family="mono",
                anchor="end",
                max_x=cx + col_w,
            )

    # --------------------------------------------------------------- footer
    footer_y = ledger_panel_y + ledger_panel_h + 20
    layout.text(
        MARGIN,
        footer_y,
        "Source: tools/research/a6400_status_data.py (DAILY_TEST_HISTORY) · Git history & docs/evidence/E0001-E0510",
        size=8.6,
        fill=COLORS["dim"],
    )
    layout.text(
        WIDTH - MARGIN,
        footer_y,
        f"Deterministic stdlib SVG · {latest.total:,} total tests",
        size=8.6,
        fill=COLORS["dim"],
        anchor="end",
    )

    height = int(round(layout._lowest + 20))
    title_text = f"Automated Test Suite Growth — {first.date} to {latest.date} ({latest.total:,} passing)"
    desc_text = (
        f"Daily cumulative test suite growth across {total_days} days from {first.total} tests "
        f"on {first.date} to {latest.total:,} tests on {latest.date}. Bounded offline and hardware checks, "
        "not a firmware compatibility percentage."
    )
    defs = "\n".join([
        "<defs>",
        '  <linearGradient id="tg-area-grad" x1="0" y1="0" x2="0" y2="1">',
        '    <stop offset="0%" stop-color="#2ea043" stop-opacity="0.42" />',
        '    <stop offset="55%" stop-color="#1f6feb" stop-opacity="0.16" />',
        '    <stop offset="100%" stop-color="#0d1117" stop-opacity="0.02" />',
        "  </linearGradient>",
        '  <linearGradient id="tg-line-grad" x1="0" y1="0" x2="1" y2="0">',
        '    <stop offset="0%" stop-color="#58a6ff" />',
        '    <stop offset="45%" stop-color="#39c5cf" />',
        '    <stop offset="80%" stop-color="#3fb950" />',
        '    <stop offset="100%" stop-color="#bc8cff" />',
        "  </linearGradient>",
        '  <linearGradient id="tg-bar-blue" x1="0" y1="0" x2="0" y2="1">',
        '    <stop offset="0%" stop-color="#58a6ff" />',
        '    <stop offset="100%" stop-color="#1f6feb" stop-opacity="0.45" />',
        "  </linearGradient>",
        '  <linearGradient id="tg-bar-amber" x1="0" y1="0" x2="0" y2="1">',
        '    <stop offset="0%" stop-color="#f0883e" />',
        '    <stop offset="100%" stop-color="#d29922" stop-opacity="0.45" />',
        "  </linearGradient>",
        '  <linearGradient id="tg-bar-emerald" x1="0" y1="0" x2="0" y2="1">',
        '    <stop offset="0%" stop-color="#56d364" />',
        '    <stop offset="100%" stop-color="#2ea043" stop-opacity="0.45" />',
        "  </linearGradient>",
        '  <linearGradient id="tg-bar-peak" x1="0" y1="0" x2="0" y2="1">',
        '    <stop offset="0%" stop-color="#bc8cff" />',
        '    <stop offset="100%" stop-color="#8957e5" stop-opacity="0.50" />',
        "  </linearGradient>",
        '  <linearGradient id="tg-card-bg" x1="0" y1="0" x2="0" y2="1">',
        '    <stop offset="0%" stop-color="#1c232d" />',
        '    <stop offset="100%" stop-color="#141921" />',
        "  </linearGradient>",
        '  <pattern id="tg-grid" width="24" height="24" patternUnits="userSpaceOnUse">',
        '    <path d="M 24 0 L 0 0 0 24" fill="none" stroke="#21262d" stroke-width="0.6" opacity="0.55" />',
        "  </pattern>",
        '  <filter id="tg-glow" x="-12%" y="-12%" width="124%" height="124%">',
        '    <feGaussianBlur stdDeviation="2.4" result="blur" />',
        "    <feMerge>",
        '      <feMergeNode in="blur" />',
        '      <feMergeNode in="SourceGraphic" />',
        "    </feMerge>",
        "  </filter>",
        '  <radialGradient id="tg-ambient-green" cx="50%" cy="50%" r="50%">',
        '    <stop offset="0%" stop-color="#2ea043" stop-opacity="0.16" />',
        '    <stop offset="100%" stop-color="#2ea043" stop-opacity="0" />',
        "  </radialGradient>",
        '  <radialGradient id="tg-ambient-blue" cx="50%" cy="50%" r="50%">',
        '    <stop offset="0%" stop-color="#1f6feb" stop-opacity="0.15" />',
        '    <stop offset="100%" stop-color="#1f6feb" stop-opacity="0" />',
        "  </radialGradient>",
        '  <clipPath id="tg-canvas-clip">',
        f'    <rect width="{WIDTH}" height="{height}" rx="16" />',
        "  </clipPath>",
        "</defs>",
    ])

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{height}" '
        f'viewBox="0 0 {WIDTH} {height}" role="img" aria-labelledby="title desc">',
        f'<title id="title">{escape(title_text)}</title>',
        f'<desc id="desc">{escape(desc_text)}</desc>',
        defs,
        f'<rect width="{WIDTH}" height="{height}" rx="16" fill="{COLORS["bg"]}" />',
        '<g clip-path="url(#tg-canvas-clip)">',
        '  <ellipse cx="740" cy="110" rx="240" ry="120" fill="url(#tg-ambient-green)" />',
        '  <ellipse cx="220" cy="370" rx="260" ry="150" fill="url(#tg-ambient-blue)" />',
        "</g>",
        "<g>",
        *layout.elements,
        "</g>",
        "</svg>",
    ]
    return "\n".join(lines) + "\n"


def _normalize(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


# --- README cache buster -----------------------------------------------------
#
# GitHub serves repository images from its /raw/ CDN with a five-minute max-age and
# the README image URL stays identical across commits, so a refreshed dashboard can
# keep showing a stale copy. The README link therefore carries a content-hash query
# (``?v=<sha256 prefix>``) that this generator rewrites; every dashboard change gets a
# new URL and both browsers and the CDN must fetch the new file. tests/
# test_research_status_sync.py fails when the two disagree.
README_PATH = ROOT / "README.md"


def _image_link_re(image_path: str) -> re.Pattern[str]:
    return re.compile(
        rf"(!\[[^\]]*\]\()({re.escape(image_path)})(\?v=[0-9a-f]+)?(\))"
    )


def svg_cache_buster(svg_text: str) -> str:
    """Deterministic content hash prefix for a rendered dashboard."""
    payload = _normalize(svg_text).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:12]


def readme_image_url(svg_text: str, image_path: str = STATUS_IMAGE_REL) -> str:
    """The README image URL, including the current content hash."""
    return f"{image_path}?v={svg_cache_buster(svg_text)}"


def _single_image_match(readme_text: str, image_path: str = STATUS_IMAGE_REL):
    matches = list(_image_link_re(image_path).finditer(_normalize(readme_text)))
    if len(matches) != 1:
        raise ValueError(
            f"README.md must embed {image_path} exactly once, "
            f"found {len(matches)} occurrence(s)"
        )
    return matches[0]


def readme_image_url_in(readme_text: str, image_path: str = STATUS_IMAGE_REL) -> str:
    """The image URL the README currently embeds (raises if missing/ambiguous)."""
    match = _single_image_match(readme_text, image_path)
    return match.group(2) + (match.group(3) or "")


def sync_readme_cache_buster(
    svg_text: str,
    readme_path: Path = README_PATH,
    *,
    write: bool = True,
    image_path: str = STATUS_IMAGE_REL,
) -> tuple[str, str]:
    """Rewrite the README image URL to the current hash; return ``(old, new)`` URLs."""
    raw = readme_path.read_bytes()
    newline = "\r\n" if b"\r\n" in raw else "\n"
    text = _normalize(raw.decode("utf-8"))
    match = _single_image_match(text, image_path)
    old_url = match.group(2) + (match.group(3) or "")
    new_url = readme_image_url(svg_text, image_path)
    if write and old_url != new_url:
        updated = _image_link_re(image_path).sub(
            lambda found: f"{found.group(1)}{new_url}{found.group(4)}", text, count=1
        )
        readme_path.write_text(updated, encoding="utf-8", newline=newline)
    return old_url, new_url


def first_difference(expected: str, actual: str) -> str:
    """Human-readable first differing line for the drift report."""
    expected_lines = _normalize(expected).splitlines()
    actual_lines = _normalize(actual).splitlines()
    for index in range(max(len(expected_lines), len(actual_lines))):
        expected_line = expected_lines[index] if index < len(expected_lines) else "<missing>"
        actual_line = actual_lines[index] if index < len(actual_lines) else "<missing>"
        if expected_line != actual_line:
            return f"line {index + 1} differs:\n  committed: {actual_line}\n  expected:  {expected_line}"
    return "no difference"


def _check_svg_and_readme(output_path: Path, rendered: str, image_rel: str) -> bool:
    if not output_path.is_file():
        print(f"missing SVG asset: {output_path}", file=sys.stderr)
        return False
    committed = output_path.read_text(encoding="utf-8")
    if _normalize(committed) != rendered:
        print(
            f"{output_path.relative_to(ROOT).as_posix()} is out of date: "
            f"{first_difference(rendered, committed)}",
            file=sys.stderr,
        )
        print("run: python -m tools.research.render_research_status --write", file=sys.stderr)
        return False
    readme_url = readme_image_url_in(README_PATH.read_text(encoding="utf-8"), image_rel)
    expected_url = readme_image_url(rendered, image_rel)
    if readme_url != expected_url:
        print(
            f"README.md image cache buster is stale: {readme_url} (expected {expected_url})",
            file=sys.stderr,
        )
        print("run: python -m tools.research.render_research_status --write", file=sys.stderr)
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="verify the committed SVG is current (default)")
    mode.add_argument("--write", action="store_true", help="rewrite the committed SVG")
    mode.add_argument("--stdout", action="store_true", help="print the SVG to stdout")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="target SVG path")
    parser.add_argument(
        "--growth-output",
        type=Path,
        default=DEFAULT_GROWTH_OUTPUT,
        help="target test-growth SVG path",
    )
    args = parser.parse_args(argv)

    rendered = render_svg()
    rendered_growth = render_test_growth_svg()

    if args.stdout:
        sys.stdout.write(rendered)
        return 0

    if args.write:
        for out_path, svg_body, image_rel in (
            (args.output, rendered, STATUS_IMAGE_REL),
            (args.growth_output, rendered_growth, GROWTH_IMAGE_REL),
        ):
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(svg_body, encoding="utf-8", newline="\n")
            old_url, new_url = sync_readme_cache_buster(svg_body, image_path=image_rel)
            print(f"wrote {out_path.relative_to(ROOT).as_posix()}")
            if old_url != new_url:
                print(f"pinned README image cache buster: {old_url} -> {new_url}")
        return 0

    if not _check_svg_and_readme(args.output, rendered, STATUS_IMAGE_REL):
        return 1
    if not _check_svg_and_readme(args.growth_output, rendered_growth, GROWTH_IMAGE_REL):
        return 1
    print(
        f"{args.output.relative_to(ROOT).as_posix()} and {args.growth_output.relative_to(ROOT).as_posix()} "
        f"are current ({TELEMETRY.latest_evidence}, {TELEMETRY.test_count} tests, "
        f"{TELEMETRY.receipt_count} receipts, v={svg_cache_buster(rendered)})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
