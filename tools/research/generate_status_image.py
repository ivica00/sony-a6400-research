"""Generates an AnyPS5-style project status visualization image."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.a6400.visualization.status_renderer import Category, Panel, StatusRenderer
from tools.research.a6400_status_data import get_a6400_project_status_data, get_anyps5_reference_data

ROOT = Path(__file__).resolve().parents[2]


def load_custom_json(path: Path) -> tuple[str, list[Panel]]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    title = data.get("title", "Status")
    panels = []
    for p_data in data.get("panels", []):
        cats = [
            Category(
                name=c["name"],
                done=int(c["done"]),
                total=int(c["total"]),
                weight=float(c.get("weight", c["total"])),
            )
            for c in p_data.get("categories", [])
        ]
        panels.append(
            Panel(
                title=p_data.get("title", "Panel"),
                badge_label=p_data.get("badge_label", "status"),
                categories=cats,
            )
        )
    return title, panels


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate AnyPS5-style project status visualization image.")
    parser.add_argument(
        "--mode",
        choices=["a6400", "demo", "json"],
        default="a6400",
        help="Data mode: 'a6400' (live project metrics), 'demo' (AnyPS5 reference layout), or 'json' (custom JSON file).",
    )
    parser.add_argument("--data", type=Path, default=None, help="Path to custom JSON file when --mode json is specified.")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/reports/status_a6400.png", help="Target PNG file path.")
    parser.add_argument("--width", type=int, default=1040, help="Image canvas width in pixels.")
    parser.add_argument("--height", type=int, default=480, help="Image canvas height in pixels.")
    parser.add_argument("--title", type=str, default=None, help="Override status title text.")

    args = parser.parse_args()

    if args.mode == "demo":
        title = args.title or "Status"
        panels = get_anyps5_reference_data()
    elif args.mode == "json":
        if not args.data or not args.data.exists():
            print(f"Error: --data JSON file must exist when using --mode json: {args.data}", file=sys.stderr)
            return 1
        title, panels = load_custom_json(args.data)
        if args.title:
            title = args.title
    else:
        title = args.title or "Sony a6400 Firmware Execution Status"
        panels = get_a6400_project_status_data()

    renderer = StatusRenderer(width=args.width, height=args.height)
    img = renderer.render(panels, title=title)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    img.save(args.output, format="PNG")
    print(f"Successfully generated status image: {args.output} ({args.width}x{args.height})")
    
    # Keep generated copies inside the documented picture directories.
    docs_status = ROOT / "docs" / "images" / "status_a6400.png"
    docs_status.parent.mkdir(parents=True, exist_ok=True)
    img.save(docs_status, format="PNG")
    print(f"Copied status image to docs/images: {docs_status}")

    alt_out = args.output.parent / "status.png"
    if alt_out != args.output:
        img.save(alt_out, format="PNG")
        docs_alt = ROOT / "docs" / "images" / "status.png"
        if docs_alt != docs_status:
            img.save(docs_alt, format="PNG")
    
    for panel in panels:
        print(f"  [{panel.badge_label}] {panel.title}: {panel.percentage:.2f}% ({panel.total_done}/{panel.total_count})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
