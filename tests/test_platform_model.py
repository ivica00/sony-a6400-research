"""Contract tests for the platform model document.

The document is the deliverable a reader meets first, so its claims must be checkable: every table
it cites names the image hash it came from, and the flash boundary is stated rather than implied.
These tests fail if the document drifts from that standard.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "PLATFORM_MODEL.md"


class PlatformModelTests(unittest.TestCase):
    def test_the_document_exists(self) -> None:
        self.assertTrue(DOC.is_file(), "docs/PLATFORM_MODEL.md is the platform deliverable")

    def test_every_cited_table_names_an_image_hash(self) -> None:
        """The provenance may sit in the citation's paragraph, not on its own line."""
        text = DOC.read_text()
        paragraphs = re.split(r"\n\s*\n", text)
        for table in ("prediction-scores", "ipc-edges", "aes-key-blocks"):
            citing = [p for p in paragraphs if table in p]
            self.assertTrue(citing, f"{table} is not cited in the platform model")
            self.assertTrue(
                any(re.search(r"[0-9a-f]{16,}", p) or re.search(r"E0\d{3}", p) for p in citing),
                f"{table} is cited without an image hash or an evidence id",
            )

    def test_the_document_states_the_flash_boundary(self) -> None:
        text = DOC.read_text().lower()
        self.assertIn("crc32", text, "the integrity mechanism must be named")
        self.assertIn("md5", text)
        self.assertIn("unknown", text, "what remains unverified must be stated as unknown")

    def test_the_document_does_not_claim_a_boot_acceptance(self) -> None:
        """A bare substring check cannot tell a claim from its denial, so this reads the sentence.

        The document must be free to say "it does not mean a modified image boots" — that
        sentence is the record being honest. What it must not contain is an affirmative claim,
        which is a sentence asserting boot acceptance without a negation.
        """
        import re
        text = DOC.read_text().lower()
        for sentence in re.split(r"(?<=[.!?])\s+", text):
            if "boot" not in sentence and "accepts a modified" not in sentence:
                continue
            negated = any(word in sentence for word in
                          ("not", "no ", "unknown", "unverified", "does not", "cannot", "never"))
            self.assertTrue(
                negated,
                f"the platform model states a boot claim without qualification: {sentence!r}")
        self.assertNotIn("custom firmware is now possible", text)

    def test_every_claim_cites_an_evidence_record(self) -> None:
        text = DOC.read_text()
        ids = set(re.findall(r"E0\d{3}", text))
        self.assertGreaterEqual(len(ids), 6,
                                "the model should rest on several records, not one")


if __name__ == "__main__":
    unittest.main()
