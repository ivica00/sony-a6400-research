"""Verify AGENTS.md stays concise and no historical evidence/hashes were lost."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENTS_MD = ROOT / "AGENTS.md"
ARCHIVE_MD = ROOT / "docs" / "archives" / "agent-notes-2026-11-13-e0210-to-e0476.md"

EVIDENCE_RE = re.compile(r"\bE0\d{3}\b")
SHA256_RE = re.compile(r"\b[0-9a-f]{64}\b")


class TestAgentsMdArchiveIntegrity(unittest.TestCase):
    def test_agents_md_is_concise(self):
        size = AGENTS_MD.stat().st_size
        self.assertLess(size, 12_288, f"AGENTS.md grew too large ({size} bytes); keep historical logs in docs/archives/")

    def test_archive_exists_and_preserves_all_historical_records(self):
        self.assertTrue(ARCHIVE_MD.is_file(), f"missing archive {ARCHIVE_MD}")
        agents_text = AGENTS_MD.read_text(encoding="utf-8")
        archive_text = ARCHIVE_MD.read_text(encoding="utf-8")
        combined = agents_text + "\n" + archive_text

        # Every key milestone E-ID from the pre-reorg AGENTS.md must remain present.
        for eid in (
            "E0210", "E0219", "E0222", "E0226", "E0227", "E0234",
            "E0297", "E0298", "E0300", "E0301", "E0302", "E0304",
            "E0305", "E0306", "E0307", "E0308", "E0309", "E0310",
            "E0311", "E0312", "E0313", "E0314", "E0320", "E0340",
            "E0414", "E0415", "E0416", "E0425", "E0448", "E0454",
            "E0456", "E0458", "E0465", "E0467", "E0468", "E0471",
            "E0476",
        ):
            self.assertIn(eid, combined, f"lost evidence reference {eid}")

        # Critical safety notes must remain in AGENTS.md itself.
        self.assertIn("E0454", agents_text)
        self.assertIn("E0297", agents_text)
        self.assertIn("A:/dev/mmca", agents_text)
        self.assertIn("B:/dev/nflasha23", agents_text)
        self.assertGreater(len(EVIDENCE_RE.findall(archive_text)), 50)
        self.assertGreaterEqual(len(SHA256_RE.findall(combined)), 1)


if __name__ == "__main__":
    unittest.main()
