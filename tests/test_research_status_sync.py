"""Keep README.md and docs/images/research-status.svg synchronized.

The narrative status card is generated from ``tools.research.a6400_status_data.STATUS_SNAPSHOT``.
These checks fail when the committed SVG is hand-edited, when README.md cites a different
latest evidence ID or test count, or when a new evidence record appears without the
documentation being refreshed. Offline and standard-library only.
"""
import re
import unittest
from pathlib import Path

from tools.research.a6400_status_data import STATUS_SNAPSHOT, TELEMETRY
from tools.research.render_research_status import (
    first_difference,
    readme_image_url,
    readme_image_url_in,
    render_svg,
    svg_cache_buster,
    sync_readme_cache_buster,
)

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
STATUS_SVG = ROOT / "docs" / "images" / "research-status.svg"
EVIDENCE_DIR = ROOT / "docs" / "evidence"

EVIDENCE_ID_RE = re.compile(r"\bE(\d{4})\b")
TEST_COUNT_RE = re.compile(r"([\d][\d,]*)\s+tests?\b")
EVIDENCE_FILE_RE = re.compile(r"^(\d{4})-[a-z0-9-]+\.md$")


def _normalized_text(path):
    return path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")


def _evidence_ids(text):
    return sorted({int(match) for match in EVIDENCE_ID_RE.findall(text)})


def _test_counts(text):
    return sorted({int(match.replace(",", "")) for match in TEST_COUNT_RE.findall(text)})


class TestResearchStatusSync(unittest.TestCase):
    def test_readme_cites_the_snapshot_latest_evidence(self):
        ids = _evidence_ids(_normalized_text(README))
        self.assertTrue(ids, "README.md cites no evidence record")
        self.assertEqual(
            f"E{ids[-1]:04d}",
            STATUS_SNAPSHOT.latest.evidence_id,
            "README.md's newest evidence ID differs from STATUS_SNAPSHOT.latest; "
            "update tools/research/a6400_status_data.py or the README together",
        )

    def test_readme_test_count_matches_snapshot(self):
        counts = _test_counts(_normalized_text(README))
        self.assertTrue(counts, "README.md states no recorded test count")
        self.assertEqual(
            counts,
            [STATUS_SNAPSHOT.suite.test_count],
            "README.md test counts disagree with STATUS_SNAPSHOT.suite.test_count",
        )

    def test_svg_identifies_the_snapshot_latest_evidence(self):
        svg = _normalized_text(STATUS_SVG)
        title = re.search(r'<title id="title">([^<]*)</title>', svg)
        self.assertIsNotNone(title, "status card has no <title id=\"title\">")
        self.assertIn(STATUS_SNAPSHOT.latest.evidence_id, title.group(1))
        self.assertIn(STATUS_SNAPSHOT.as_of, svg)
        self.assertEqual(
            sorted({int(match) for match in EVIDENCE_ID_RE.findall(svg)})[-1],
            int(STATUS_SNAPSHOT.latest.evidence_id[1:]),
            "the status card mentions an evidence record newer than the snapshot",
        )

    def test_svg_test_count_matches_snapshot(self):
        counts = _test_counts(_normalized_text(STATUS_SVG))
        self.assertTrue(counts, "the status card states no recorded test count")
        self.assertEqual(counts, [STATUS_SNAPSHOT.suite.test_count])

    def test_svg_is_the_generated_output(self):
        committed = _normalized_text(STATUS_SVG)
        expected = render_svg(TELEMETRY)
        if committed != expected:
            self.fail(
                "docs/images/research-status.svg was not generated from STATUS_SNAPSHOT: "
                + first_difference(expected, committed)
                + "\nrun: python -m tools.research.render_research_status --write"
            )

    def test_generator_is_deterministic(self):
        first = render_svg(TELEMETRY)
        self.assertEqual(first, render_svg(TELEMETRY))
        self.assertNotIn("\r", first)
        self.assertTrue(first.startswith("<svg "))
        self.assertTrue(first.endswith("\n"))
        self.assertIn('<title id="title">', first)
        self.assertIn('<desc id="desc">', first)
        self.assertEqual(first, _normalized_text(STATUS_SVG))

    def test_latest_evidence_record_exists_and_matches(self):
        record = ROOT / STATUS_SNAPSHOT.latest.path
        self.assertTrue(record.is_file(), f"missing evidence record: {STATUS_SNAPSHOT.latest.path}")
        text = _normalized_text(record)
        first_line = text.splitlines()[0]
        self.assertTrue(
            first_line.startswith(f"# {STATUS_SNAPSHOT.latest.evidence_id} "),
            f"evidence record heading is {first_line!r}",
        )
        self.assertIn(STATUS_SNAPSHOT.latest.date, text)
        self.assertEqual(STATUS_SNAPSHOT.latest.date, STATUS_SNAPSHOT.as_of)
        self.assertEqual(STATUS_SNAPSHOT.suite.recorded_at, STATUS_SNAPSHOT.as_of)

    def test_no_unrecorded_newer_evidence(self):
        ids = []
        for path in EVIDENCE_DIR.iterdir():
            match = EVIDENCE_FILE_RE.match(path.name)
            if match:
                ids.append(int(match.group(1)))
        self.assertTrue(ids, "no evidence records found")
        self.assertEqual(
            f"E{max(ids):04d}",
            STATUS_SNAPSHOT.latest.evidence_id,
            "a newer evidence record exists than the documentation snapshot; refresh "
            "STATUS_SNAPSHOT, README.md and the status card together",
        )

    def test_snapshot_cards_are_backed_by_records(self):
        latest = int(STATUS_SNAPSHOT.latest.evidence_id[1:])
        for card in STATUS_SNAPSHOT.cards:
            record = ROOT / card.path
            self.assertTrue(record.is_file(), f"missing card evidence record: {card.path}")
            self.assertLessEqual(int(card.evidence_id[1:]), latest)
            self.assertIn(card.evidence_id, _normalized_text(record).splitlines()[0])
            self.assertEqual(f"E{int(card.evidence_id[1:]):04d}", card.evidence_id)
            self.assertRegex(card.date, r"^\d{4}-\d{2}-\d{2}$")
            self.assertTrue(card.tier, "every card must state its evidence tier")
            self.assertTrue(card.demonstrated and card.boundary)

    def test_readme_image_url_pins_the_svg_cache_buster(self):
        readme = _normalized_text(README)
        embedded = readme_image_url_in(readme)
        committed = _normalized_text(STATUS_SVG)
        self.assertEqual(embedded, readme_image_url(committed))
        self.assertEqual(embedded, readme_image_url(render_svg(TELEMETRY)))
        self.assertRegex(embedded, r"^docs/images/research-status\.svg\?v=[0-9a-f]{12}$")
        self.assertIn(f"?v={svg_cache_buster(committed)}", readme)

    def test_cache_buster_sync_is_idempotent(self):
        old_url, new_url = sync_readme_cache_buster(render_svg(TELEMETRY), write=False)
        self.assertEqual(old_url, new_url, "README cache buster is stale; run --write")

    def test_readme_evidence_links_resolve(self):
        readme = _normalized_text(README)
        links = re.findall(r"\]\((docs/evidence/[0-9]{4}-[a-z0-9-]+\.md)\)", readme)
        self.assertTrue(links, "README.md links no evidence record")
        for link in links:
            self.assertTrue((ROOT / link).is_file(), f"README.md links a missing record: {link}")


if __name__ == "__main__":
    unittest.main()
