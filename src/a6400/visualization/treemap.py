"""Treemap and tile-grid layout algorithms."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


@dataclass
class Rect:
    x: float
    y: float
    w: float
    h: float

    @property
    def right(self) -> float:
        return self.x + self.w

    @property
    def bottom(self) -> float:
        return self.y + self.h

    def as_tuple(self) -> tuple[int, int, int, int]:
        return (int(round(self.x)), int(round(self.y)), int(round(self.w)), int(round(self.h)))

    def as_box(self) -> tuple[int, int, int, int]:
        return (int(round(self.x)), int(round(self.y)), int(round(self.right)), int(round(self.bottom)))


def worst_ratio(row: list[float], side_length: float) -> float:
    """Computes the worst aspect ratio in a row of normalized weights."""
    if not row or side_length <= 0:
        return float("inf")
    s = sum(row)
    if s == 0:
        return float("inf")
    s2 = s * s
    side2 = side_length * side_length
    max_val = max(row)
    min_val = min(row)
    if min_val <= 0:
        return float("inf")
    return max((side2 * max_val) / s2, s2 / (side2 * min_val))


def squarify_rects(
    children: list[tuple[Any, float]],
    rect: Rect,
) -> list[tuple[Any, Rect]]:
    """Squarified treemap layout algorithm based on Bruls, Huizing, van Wijk."""
    if not children:
        return []
    if len(children) == 1:
        return [(children[0][0], rect)]

    total_weight = sum(w for _, w in children)
    if total_weight <= 0:
        # Equal distribution if all weights zero
        count = len(children)
        return [(c[0], Rect(rect.x, rect.y + i * (rect.h / count), rect.w, rect.h / count)) for i, c in enumerate(children)]

    area = rect.w * rect.h
    normalized = [(item, (weight / total_weight) * area) for item, weight in children if weight > 0]
    zero_items = [item for item, weight in children if weight <= 0]

    results: list[tuple[Any, Rect]] = []
    
    current_rect = Rect(rect.x, rect.y, rect.w, rect.h)

    def layout_row(row: list[tuple[Any, float]], side: float, is_horizontal: bool) -> tuple[list[tuple[Any, Rect]], Rect]:
        row_area = sum(w for _, w in row)
        if side <= 0 or row_area <= 0:
            return [], current_rect

        other_side = row_area / side
        placed = []
        offset = 0.0

        for item, weight in row:
            item_length = weight / other_side
            if is_horizontal:
                # Splitting along width: other_side is height of the row
                placed.append((item, Rect(current_rect.x + offset, current_rect.y, item_length, other_side)))
            else:
                # Splitting along height: other_side is width of the row
                placed.append((item, Rect(current_rect.x, current_rect.y + offset, other_side, item_length)))
            offset += item_length

        if is_horizontal:
            new_rect = Rect(current_rect.x, current_rect.y + other_side, current_rect.w, max(0.0, current_rect.h - other_side))
        else:
            new_rect = Rect(current_rect.x + other_side, current_rect.y, max(0.0, current_rect.w - other_side), current_rect.h)

        return placed, new_rect

    remaining = list(normalized)
    while remaining:
        is_horizontal = current_rect.w >= current_rect.h
        side = current_rect.w if is_horizontal else current_rect.h
        if side <= 0:
            break

        row: list[tuple[Any, float]] = [remaining[0]]
        remaining = remaining[1:]

        while remaining:
            next_item = remaining[0]
            current_worst = worst_ratio([w for _, w in row], side)
            next_worst = worst_ratio([w for _, w in row + [next_item]], side)

            if next_worst <= current_worst:
                row.append(next_item)
                remaining = remaining[1:]
            else:
                break

        placed, current_rect = layout_row(row, side, is_horizontal)
        results.extend(placed)

    # Any remaining zero-weight items get placed as empty rects
    for item in zero_items:
        results.append((item, Rect(rect.x, rect.y, 0, 0)))

    return results


def compute_tile_grid(
    box: Rect,
    total_count: int,
    done_count: int,
    top_label_height: float = 18.0,
    padding: float = 3.0,
    tile_gap: float = 1.0,
) -> list[tuple[Rect, bool]]:
    """Calculates discrete micro-tile coordinates inside a category bounding box."""
    if total_count <= 0:
        return []

    inner_x = box.x + padding
    inner_y = box.y + top_label_height + padding
    inner_w = max(4.0, box.w - 2 * padding)
    inner_h = max(4.0, box.h - top_label_height - 2 * padding)

    # Estimate ideal tile size (aim for near-square tiles between 4px and 12px)
    area = inner_w * inner_h
    target_side = max(4.0, math.sqrt(area / total_count))

    cols = max(1, int(round(inner_w / (target_side + tile_gap))))
    rows = max(1, math.ceil(total_count / cols))

    # Fine-tune cols/rows to maximize coverage while preserving bounds
    while cols * rows < total_count:
        cols += 1

    tile_w = max(2.0, (inner_w - (cols - 1) * tile_gap) / cols)
    tile_h = max(2.0, (inner_h - (rows - 1) * tile_gap) / rows)

    tiles = []
    idx = 0
    for r in range(rows):
        for c in range(cols):
            if idx >= total_count:
                break
            tx = inner_x + c * (tile_w + tile_gap)
            ty = inner_y + r * (tile_h + tile_gap)
            is_done = idx < done_count
            tiles.append((Rect(tx, ty, tile_w, tile_h), is_done))
            idx += 1

    return tiles

