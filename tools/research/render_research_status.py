"""Render ``docs/images/research-status.svg`` from ``STATUS_SNAPSHOT``.

Deterministic and standard-library only: the same snapshot renders byte-for-byte
the same SVG on Linux, macOS and Windows. It never invents a percentage, a test
count or an evidence ID -- every dynamic string comes from
``tools/research/a6400_status_data.py`` and ``tests/test_research_status_sync.py``
fails when the committed SVG, README.md and that snapshot disagree.

Usage::

    python -m tools.research.render_research_status --check   # default, exit 1 on drift
    python -m tools.research.render_research_status --stdout  # print, do not write
    python -m tools.research.render_research_status --write   # rewrite the committed SVG
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from xml.sax.saxutils import escape

from tools.research.a6400_status_data import STATUS_SNAPSHOT, StatusSnapshot

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "docs" / "images" / "research-status.svg"

WIDTH = 1000
HEIGHT = 810
CARD_X = 28
CARD_WIDTH = 944
CARD_HEIGHT = 152
CARD_TOPS = (103, 267, 431, 595)
WRAP_COLUMNS = 100
MAX_LINES = 2


def _wrap(text: str, *, columns: int = WRAP_COLUMNS, max_lines: int = MAX_LINES) -> list[str]:
    """Greedy word wrap with a hard limit that fails closed instead of truncating."""
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = word if not current else f"{current} {word}"
        if len(candidate) <= columns:
            current = candidate
            continue
        lines.append(current)
        current = word
    if current:
        lines.append(current)
    if len(lines) > max_lines:
        raise ValueError(
            f"status text needs {len(lines)} lines (limit {max_lines}); shorten the "
            f"snapshot text instead of truncating it: {text!r}"
        )
    return lines


def _text(x: int, y: int, fill: str, size: int, weight: int, value: str) -> str:
    return (
        f'<text x="{x}" y="{y}" fill="{fill}" font-size="{size}" font-weight="{weight}">'
        f"{escape(value)}</text>"
    )


def render_svg(snapshot: StatusSnapshot = STATUS_SNAPSHOT) -> str:
    """Return the complete SVG document for ``snapshot`` (no I/O)."""
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" '
        f'viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-labelledby="title desc">',
        f'<title id="title">{escape(snapshot.title)}</title>',
        f'<desc id="desc">{escape(snapshot.description)}</desc>',
        f'<rect width="{WIDTH}" height="{HEIGHT}" rx="16" fill="#0d1117" />',
        '<g font-family="Segoe UI,Arial,sans-serif">',
        _text(28, 42, "#f0f6fc", 26, 700, "Research status"),
        _text(740, 40, "#c9d1d9", 17, 400, f"{snapshot.as_of} | {snapshot.latest.evidence_id}"),
        _text(28, 78, "#36c88a", 18, 400, snapshot.headline),
    ]
    for card, top in zip(snapshot.cards, CARD_TOPS):
        lines.append(
            f'<rect x="{CARD_X}" y="{top}" width="{CARD_WIDTH}" height="{CARD_HEIGHT}" '
            'rx="8" fill="#161b22" />'
        )
        lines.append(_text(44, top + 22, "#9da7b3", 12, 400, card.tier))
        lines.append(_text(44, top + 48, "#f0f6fc", 19, 700, card.title))
        for slot, line in enumerate(_wrap(card.demonstrated)):
            lines.append(_text(44, top + 72 + slot * 20, "#c9d1d9", 14, 400, line))
        for slot, line in enumerate(_wrap(card.boundary)):
            lines.append(_text(44, top + 116 + slot * 20, "#f0bd55", 14, 400, line))
    lines.append(_text(28, 786, "#9da7b3", 15, 400, snapshot.footer))
    lines.append("</g>")
    lines.append("</svg>")
    return "\n".join(lines) + "\n"


def _normalize(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


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
        print(f"wrote {args.output.relative_to(ROOT).as_posix()}")
        return 0

    if not args.output.is_file():
        print(f"missing status card: {args.output}", file=sys.stderr)
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
    print(
        f"{args.output.relative_to(ROOT).as_posix()} is current "
        f"({STATUS_SNAPSHOT.latest.evidence_id}, {STATUS_SNAPSHOT.suite.test_count} tests)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
