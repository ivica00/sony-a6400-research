"""Contract test for the framebuffer question raised by another a6400 project.

That project's README lists "on-screen GUI" as a confirmed dead end, citing "no /dev/fb0", and then
ships a GUI that draws to /dev/fb0. A device-node table answers the question directly: if no
packaged body registers an `fb*` node, a program opening that path cannot succeed by name.

This test asserts what the tables say, so the answer stays checkable rather than becoming a claim
in a comment thread.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "research"))


class FramebufferNodeTests(unittest.TestCase):
    def setUp(self) -> None:
        import os
        raw = os.environ.get("A6400_UNPACKED_ROOT")
        if not raw:
            self.skipTest("A6400_UNPACKED_ROOT not set; no unpacked body available")
        self.root = Path(raw)

    def _nodes(self) -> dict[str, tuple[str, ...]]:
        from predict_body import _devno_nodes

        found: dict[str, tuple[str, ...]] = {}
        for body in sorted(self.root.iterdir()):
            if not body.is_dir():
                continue
            nodes = _devno_nodes(body)
            if nodes:
                found[body.name] = nodes
        return found

    def test_no_packaged_body_registers_a_framebuffer_node(self) -> None:
        nodes = self._nodes()
        if not nodes:
            self.skipTest("no devno.ko parsed under A6400_UNPACKED_ROOT")
        offenders = {body: [n for n in names if n.startswith("fb") or "/fb" in n]
                     for body, names in nodes.items()}
        offenders = {b: n for b, n in offenders.items() if n}
        self.assertEqual(offenders, {},
                         "a packaged devno table registers a framebuffer node")

    def test_the_display_node_is_dmpgles2_on_every_body(self) -> None:
        nodes = self._nodes()
        if not nodes:
            self.skipTest("no devno.ko parsed under A6400_UNPACKED_ROOT")
        for body, names in nodes.items():
            self.assertIn("dmpgles2", names,
                          f"{body} must publish the display node the system actually uses")


if __name__ == "__main__":
    unittest.main()
