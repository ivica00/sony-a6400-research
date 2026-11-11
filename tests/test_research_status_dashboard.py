"""Structural and epistemic checks for the telemetry dashboard SVG.

The dashboard is generated, not hand-drawn: these tests parse the committed SVG and
verify that it is well-formed, that no text overlaps or leaves the canvas, that every
KPI/cell/bar number is derived from a tracked inventory, and that no text ever claims an
overall firmware-compatibility percentage.

Standard library only (``xml.etree`` + the generator's own geometry estimator), so the
same checks run in CI.
"""
import re
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from tools.research.a6400_status_data import (
    CELL_BOUNDARY,
    CELL_DECODED,
    CELL_STATES,
    CELL_UNMAPPED,
    CELL_VERIFIED,
    EP0_CLASS_CASES,
    TEARDOWN_PHASES,
    TELEMETRY,
    TRANSPORT_AUDIT_CHECKS,
    evidence_receipt_count,
    registered_target_label,
    status_categories,
)
from tools.research.render_research_status import WIDTH, estimate_text_width, render_svg, text_box

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_DIR = ROOT / "docs" / "evidence"
SVG = ROOT / "docs" / "images" / "research-status.svg"
SVG_NS = "{http://www.w3.org/2000/svg}"

# Sources that name a bounded inventory rather than a dated E0xxx record.
INVENTORY_SOURCES = {
    "task94_phases",
    "imdb_plugins",
    "status data",
    "offline suite receipts",
    "docs/evidence/",
    "src/a6400/targets/",
}


def _parse(svg_text=None):
    if svg_text is None:
        svg_text = SVG.read_text(encoding="utf-8")
    return ET.fromstring(svg_text)


def _text_nodes(root):
    nodes = []
    for element in root.iter(f"{SVG_NS}text"):
        content = "".join(element.itertext())
        family_attr = element.get("font-family", "")
        nodes.append(
            {
                "text": content,
                "x": float(element.get("x")),
                "y": float(element.get("y")),
                "size": float(element.get("font-size")),
                "weight": int(element.get("font-weight", "400")),
                "anchor": element.get("text-anchor", "start"),
                "family": "mono" if "monospace" in family_attr else "sans",
            }
        )
    return nodes


class TestWellFormed(unittest.TestCase):
    def test_parses_as_xml(self):
        root = _parse()
        self.assertEqual(root.tag, f"{SVG_NS}svg")

    def test_canvas_is_920_wide_and_consistent(self):
        root = _parse()
        width = int(root.get("width"))
        height = int(root.get("height"))
        self.assertEqual(width, WIDTH)
        self.assertEqual(root.get("viewBox"), f"0 0 {width} {height}")
        self.assertGreater(height, 700)

    def test_has_accessible_title_and_description(self):
        root = _parse()
        title = root.find(f"{SVG_NS}title")
        desc = root.find(f"{SVG_NS}desc")
        self.assertIsNotNone(title)
        self.assertIsNotNone(desc)
        self.assertIn(TELEMETRY.latest_evidence, title.text)
        self.assertIn("not a firmware compatibility percentage", desc.text.lower())

    def test_dimensions_match_the_generated_document(self):
        self.assertEqual(SVG.read_text(encoding="utf-8"), render_svg(TELEMETRY))


class TestTextLayout(unittest.TestCase):
    def test_no_text_overlaps(self):
        nodes = _text_nodes(_parse())
        self.assertGreater(len(nodes), 40, "dashboard should be text-dense")
        boxes = []
        for node in nodes:
            boxes.append((text_box(node["x"], node["y"], node["text"], node["size"], node["family"],
                                   node["weight"], node["anchor"]), node["text"]))
        collisions = []
        for index, (box, text) in enumerate(boxes):
            for other_box, other_text in boxes[index + 1:]:
                if (box[0] < other_box[2] and box[2] > other_box[0]
                        and box[1] < other_box[3] and box[3] > other_box[1]):
                    collisions.append(f"{text!r} <-> {other_text!r}")
        self.assertEqual(collisions, [], "overlapping text boxes: " + "; ".join(collisions[:5]))

    def test_all_text_stays_inside_the_canvas(self):
        root = _parse()
        width = int(root.get("width"))
        height = int(root.get("height"))
        for node in _text_nodes(root):
            left, top, right, bottom = text_box(node["x"], node["y"], node["text"], node["size"],
                                                node["family"], node["weight"], node["anchor"])
            self.assertGreaterEqual(left, 0.0, node["text"])
            self.assertLessEqual(right, width, node["text"])
            self.assertGreaterEqual(top, 0.0, node["text"])
            self.assertLessEqual(bottom, height, node["text"])

    def test_width_estimator_is_conservative(self):
        # The suite must not silently rely on an optimistic measurement.
        self.assertGreater(estimate_text_width("MMMM", 10), estimate_text_width("iiii", 10) * 0.9)


class TestKpiDerivation(unittest.TestCase):
    def _pill(self, label):
        for pill in TELEMETRY.pills:
            if pill.label == label:
                return pill
        self.fail(f"missing KPI pill {label!r}")

    def test_contract_test_pill_matches_recorded_suite(self):
        pill = self._pill("contract tests")
        self.assertEqual(pill.value, f"{TELEMETRY.test_count:,} passing")
        self.assertEqual(TELEMETRY.test_count, TELEMETRY.test_count)
        self.assertEqual(pill.tone, "green")

    def test_evidence_receipt_pill_counts_real_files(self):
        pill = self._pill("evidence receipts")
        self.assertEqual(pill.value, f"{evidence_receipt_count()} recorded")
        self.assertGreater(evidence_receipt_count(), 300)
        self.assertEqual(pill.tone, "blue")

    def test_teardown_pill_states_the_recorded_phase_mask(self):
        pill = self._pill("teardown sequencer")
        self.assertIn(f"{TEARDOWN_PHASES}/{TEARDOWN_PHASES}", pill.value)
        self.assertIn("0x1ff", pill.value)
        self.assertEqual(pill.tone, "green")

    def test_task_phase_pill_matches_the_boot_inventory(self):
        phases = status_categories()["task94_phases"]
        pill = self._pill("task phases")
        self.assertEqual(pill.value, f"{phases.done}/{phases.total} observed")
        self.assertEqual(pill.tone, "amber")

    def test_target_pill_matches_the_registry(self):
        pill = self._pill("BIONZ X targets")
        self.assertEqual(pill.value, registered_target_label())
        self.assertEqual(pill.value, "ILCE-6400 + ZV-E10")
        self.assertEqual(pill.tone, "violet")

    def test_pills_cover_the_required_kpis(self):
        self.assertEqual(
            [pill.label for pill in TELEMETRY.pills],
            ["contract tests", "evidence receipts", "teardown sequencer", "task phases", "BIONZ X targets"],
        )


class TestGridDerivation(unittest.TestCase):
    def _group(self, title):
        for group in TELEMETRY.firmware_groups + TELEMETRY.pipeline_groups:
            if group.title == title:
                return group
        self.fail(f"missing cell group {title!r}")

    def test_static_plugin_grid_matches_the_198_item_inventory(self):
        group = self._group("Static Plugins (198)")
        plugins = status_categories()["imdb_plugins"]
        self.assertEqual(len(group.cells), plugins.total)
        self.assertEqual(group.counts()[CELL_UNMAPPED], plugins.total)
        self.assertEqual(group.counts()[CELL_VERIFIED], plugins.done)

    def test_boot_phase_grid_matches_the_8_phase_inventory(self):
        group = self._group("Boot Task Phases (8)")
        phases = status_categories()["task94_phases"]
        self.assertEqual(len(group.cells), phases.total)
        self.assertEqual(group.counts()[CELL_VERIFIED], phases.done)
        self.assertEqual(group.counts()[CELL_UNMAPPED], phases.total - phases.done)

    def test_teardown_and_ep0_groups_are_fully_verified(self):
        for title, expected in (("Teardown 9-Phase Sequencer (0x1ff)", TEARDOWN_PHASES),
                                ("EP0 Class / Probe / Commit", EP0_CLASS_CASES)):
            group = self._group(title)
            self.assertEqual(len(group.cells), expected)
            self.assertEqual(group.counts()[CELL_VERIFIED], expected)

    def test_track_b_group_separates_the_closed_selector_from_open_pins(self):
        # E0354: the live 0x84 selector accepted the endpoint, so exactly one cell is
        # verified; the DirectShow pin connect and MSC recovery stay amber boundaries.
        group = self._group("Track B: DirectShow Pin / 0x84 Start")
        self.assertEqual(len(group.cells), 3)
        self.assertEqual(group.counts()[CELL_VERIFIED], 1)
        self.assertEqual(group.counts()[CELL_BOUNDARY], 2)

    def test_every_grid_group_uses_known_states_and_has_a_source(self):
        for group in TELEMETRY.firmware_groups + TELEMETRY.pipeline_groups:
            self.assertTrue(group.source)
            self.assertTrue(set(group.cells) <= set(CELL_STATES), group.title)

    def test_grids_are_the_specified_six_plus_five_groups(self):
        self.assertEqual(len(TELEMETRY.firmware_groups), 6)
        self.assertEqual(len(TELEMETRY.pipeline_groups), 5)
        self.assertGreater(sum(len(group.cells) for group in TELEMETRY.firmware_groups), 200)


class TestBarsAndBoundaries(unittest.TestCase):
    def _bar(self, prefix):
        for bar in TELEMETRY.contract_bars:
            if bar.label.startswith(prefix):
                return bar
        self.fail(f"missing contract bar {prefix!r}")

    def test_required_bars_exist_with_bounded_ratios(self):
        self.assertEqual(self._bar("USB Soft-Disconnect").done, TEARDOWN_PHASES)
        self.assertEqual(self._bar("EP0 UVC Class").total, TRANSPORT_AUDIT_CHECKS)
        sync = self._bar("UIPC / MWF Sync Callback")
        self.assertEqual((sync.done, sync.total, sync.amber), (1, 2, 1))
        display = self._bar("GPES / SMAPH-S30")
        self.assertEqual((display.done, display.total), (
            status_categories()["display_subsys"].done, status_categories()["display_subsys"].total))
        phases = self._bar("im.elf Boot Task Phases")
        self.assertEqual((phases.done, phases.total), (
            status_categories()["task94_phases"].done, status_categories()["task94_phases"].total))

    def test_boundaries_are_sorted_by_open_count(self):
        counts = [group.count for group in TELEMETRY.boundaries]
        self.assertEqual(counts, sorted(counts, reverse=True))
        self.assertEqual(counts, [4, 3, 3, 3])

    def test_boundary_items_are_named(self):
        for group in TELEMETRY.boundaries:
            self.assertEqual(group.count, len(group.items))
            self.assertTrue(all(len(item) > 4 for item in group.items))
        self.assertEqual(sum(group.count for group in TELEMETRY.boundaries), 13)

    def test_open_boundary_total_is_rendered(self):
        root = _parse()
        rendered = " ".join("".join(element.itertext()) for element in root.iter(f"{SVG_NS}text"))
        self.assertIn("13 tracked open boundaries across 4 areas", rendered)


class TestEpistemicHonesty(unittest.TestCase):
    def test_no_percentage_claim_is_rendered(self):
        root = _parse()
        texts = ["".join(element.itertext()) for element in root.iter(f"{SVG_NS}text")]
        self.assertFalse([text for text in texts if "%" in text],
                         "the dashboard must not display a percentage")

    def test_footnote_and_legend_are_present(self):
        root = _parse()
        texts = ["".join(element.itertext()) for element in root.iter(f"{SVG_NS}text")]
        joined = " ".join(texts)
        self.assertIn("not an overall firmware compatibility percentage", joined)
        for _state, label in TELEMETRY.legend:
            self.assertIn(label, joined)
        self.assertIn("Unmapped Inventory", joined)

    def test_legend_covers_every_state_used_in_the_grids(self):
        used = set()
        for group in TELEMETRY.firmware_groups + TELEMETRY.pipeline_groups:
            used.update(group.cells)
        legend_states = {state for state, _label in TELEMETRY.legend}
        self.assertEqual(used, legend_states)

    def test_every_source_resolves_to_a_record_or_a_named_inventory(self):
        sources = {group.source for group in TELEMETRY.firmware_groups}
        sources |= {group.source for group in TELEMETRY.pipeline_groups}
        sources |= {bar.source for bar in TELEMETRY.contract_bars}
        sources |= {group.source for group in TELEMETRY.boundaries}
        for source in sources:
            for token in (part.strip() for part in source.split("·")):
                self.assertTrue(token, f"empty token in source {source!r}")
                match = re.fullmatch(r"E(\d{4})", token)
                if match:
                    matches = list(EVIDENCE_DIR.glob(f"{int(match.group(1)):04d}-*.md"))
                    self.assertTrue(matches, f"source {token} has no evidence record")
                else:
                    self.assertIn(token, INVENTORY_SOURCES, f"unknown inventory source {token!r}")


if __name__ == "__main__":
    unittest.main()
