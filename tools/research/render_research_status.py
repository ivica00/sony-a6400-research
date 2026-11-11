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
    TELEMETRY,
    TelemetryDashboard,
)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "docs" / "images" / "research-status.svg"

WIDTH = 920
MARGIN = 24
GAP = 20
CONTENT_W = WIDTH - 2 * MARGIN
COL_W = (CONTENT_W - GAP) // 2

COLORS = {
    "bg": "#0d1117",
    "panel": "#161b22",
    "border": "#30363d",
    "track": "#21262d",
    "text": "#f0f6fc",
    "body": "#c9d1d9",
    "muted": "#8b949e",
    "dim": "#9da7b3",
    "green": "#2ea043",
    "blue": "#1f6feb",
    "amber": "#d29922",
    "violet": "#8957e5",
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
    ) -> None:
        attrs = [f'x="{x:g}"', f'y="{y:g}"', f'width="{w:g}"', f'height="{h:g}"', f'rx="{rx:g}"', f'fill="{fill}"']
        if stroke is not None:
            attrs += [f'stroke="{stroke}"', f'stroke-width="{stroke_width:g}"']
        self.elements.append(f"<rect {' '.join(attrs)} />")
        self._lowest = max(self._lowest, y + h)

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
IMAGE_LINK_RE = re.compile(
    r"(!\[[^\]]*\]\()(docs/images/research-status\.svg)(\?v=[0-9a-f]+)?(\))"
)


def svg_cache_buster(svg_text: str) -> str:
    """Deterministic content hash prefix for a rendered dashboard."""
    payload = _normalize(svg_text).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:12]


def readme_image_url(svg_text: str) -> str:
    """The README image URL, including the current content hash."""
    return f"docs/images/research-status.svg?v={svg_cache_buster(svg_text)}"


def _single_image_match(readme_text: str):
    matches = list(IMAGE_LINK_RE.finditer(_normalize(readme_text)))
    if len(matches) != 1:
        raise ValueError(
            "README.md must embed docs/images/research-status.svg exactly once, "
            f"found {len(matches)} occurrence(s)"
        )
    return matches[0]


def readme_image_url_in(readme_text: str) -> str:
    """The image URL the README currently embeds (raises if missing/ambiguous)."""
    match = _single_image_match(readme_text)
    return match.group(2) + (match.group(3) or "")


def sync_readme_cache_buster(
    svg_text: str, readme_path: Path = README_PATH, *, write: bool = True
) -> tuple[str, str]:
    """Rewrite the README image URL to the current hash; return ``(old, new)`` URLs."""
    raw = readme_path.read_bytes()
    newline = "\r\n" if b"\r\n" in raw else "\n"
    text = _normalize(raw.decode("utf-8"))
    match = _single_image_match(text)
    old_url = match.group(2) + (match.group(3) or "")
    new_url = readme_image_url(svg_text)
    if write and old_url != new_url:
        updated = IMAGE_LINK_RE.sub(
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="verify the committed SVG is current (default)")
    mode.add_argument("--write", action="store_true", help="rewrite the committed SVG")
    mode.add_argument("--stdout", action="store_true", help="print the SVG to stdout")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="target SVG path")
    args = parser.parse_args(argv)

    rendered = render_svg()

    if args.stdout:
        sys.stdout.write(rendered)
        return 0

    if args.write:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8", newline="\n")
        old_url, new_url = sync_readme_cache_buster(rendered)
        print(f"wrote {args.output.relative_to(ROOT).as_posix()}")
        if old_url != new_url:
            print(f"pinned README image cache buster: {old_url} -> {new_url}")
        return 0

    if not args.output.is_file():
        print(f"missing status dashboard: {args.output}", file=sys.stderr)
        return 1
    committed = args.output.read_text(encoding="utf-8")
    if _normalize(committed) != rendered:
        print(
            f"{args.output.relative_to(ROOT).as_posix()} is out of date: "
            f"{first_difference(rendered, committed)}",
            file=sys.stderr,
        )
        print("run: python -m tools.research.render_research_status --write", file=sys.stderr)
        return 1
    readme_url = readme_image_url_in(README_PATH.read_text(encoding="utf-8"))
    expected_url = readme_image_url(rendered)
    if readme_url != expected_url:
        print(
            f"README.md image cache buster is stale: {readme_url} (expected {expected_url})",
            file=sys.stderr,
        )
        print("run: python -m tools.research.render_research_status --write", file=sys.stderr)
        return 1
    print(
        f"{args.output.relative_to(ROOT).as_posix()} is current "
        f"({TELEMETRY.latest_evidence}, {TELEMETRY.test_count} tests, "
        f"{TELEMETRY.receipt_count} receipts, v={svg_cache_buster(rendered)})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
