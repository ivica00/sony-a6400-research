"""Tests for the AnyPS5-style status visualization renderer and treemap engine."""
import unittest
from pathlib import Path

from PIL import Image

from src.a6400.visualization.status_renderer import Category, Panel, StatusRenderer
from src.a6400.visualization.treemap import Rect, compute_tile_grid, squarify_rects
from tools.research.a6400_status_data import get_a6400_project_status_data, get_anyps5_reference_data
from tools.research.generate_status_image import load_custom_json

ROOT = Path(__file__).resolve().parents[1]


class TestStatusRenderer(unittest.TestCase):
    def test_treemap_squarify_bounds(self):
        parent = Rect(0, 0, 400, 300)
        items = [("A", 100.0), ("B", 50.0), ("C", 30.0), ("D", 20.0)]
        laid_out = squarify_rects(items, parent)

        self.assertEqual(len(laid_out), 4)
        for _, box in laid_out:
            # Check within parent bounds
            self.assertGreaterEqual(box.x, parent.x - 0.001)
            self.assertGreaterEqual(box.y, parent.y - 0.001)
            self.assertLessEqual(box.right, parent.right + 0.001)
            self.assertLessEqual(box.bottom, parent.bottom + 0.001)
            self.assertGreater(box.w, 0)
            self.assertGreater(box.h, 0)

        # Total area should approximately equal parent area
        total_child_area = sum(b.w * b.h for _, b in laid_out)
        self.assertAlmostEqual(total_child_area, parent.w * parent.h, places=1)

    def test_compute_tile_grid_counts(self):
        box = Rect(10, 10, 100, 100)
        total = 25
        done = 15
        tiles = compute_tile_grid(box, total, done, top_label_height=15.0)

        self.assertEqual(len(tiles), total)
        done_tiles = [t for t, is_done in tiles if is_done]
        undone_tiles = [t for t, is_done in tiles if not is_done]
        self.assertEqual(len(done_tiles), done)
        self.assertEqual(len(undone_tiles), total - done)

    def test_status_renderer_generates_image(self):
        panels = get_anyps5_reference_data()
        renderer = StatusRenderer(width=600, height=300)
        img = renderer.render(panels, title="Test Status")

        self.assertIsInstance(img, Image.Image)
        self.assertEqual(img.size, (600, 300))
        self.assertEqual(img.mode, "RGB")

    def test_a6400_data_structure(self):
        panels = get_a6400_project_status_data()
        self.assertEqual(len(panels), 2)
        for p in panels:
            self.assertGreater(p.total_count, 0)
            self.assertGreaterEqual(p.total_done, 0)
            self.assertLessEqual(p.total_done, p.total_count)
            self.assertGreater(len(p.categories), 0)


if __name__ == "__main__":
    unittest.main()
