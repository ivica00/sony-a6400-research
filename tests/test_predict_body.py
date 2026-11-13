"""Contract tests for predicting a body's surface and scoring it on held-out bodies.

This is the difference between a description and a model. A tool that reports what it read from
the same files it was built from has learned nothing; the test of understanding is whether the
rule derived from some bodies predicts the surface of a body it never saw.

The discipline here is that ``score_held_out`` must not read the held-out body's tables before
scoring it. That is what the synthetic test pins: it would pass trivially if the fit step peeked.

Offline only.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "research"))

from predict_body import score, score_held_out  # noqa: E402


class ScoreTests(unittest.TestCase):
    def test_a_perfect_prediction_scores_one(self) -> None:
        actual = {"command_ids": (1, 2, 3), "usb_pairs": ((0x54C, 0x448),),
                  "devno_nodes": ("usb/std",)}
        result = score(actual, actual)
        self.assertEqual(result["command_recall"], 1.0)
        self.assertEqual(result["usb_match"], 1.0)
        self.assertEqual(result["devno_match"], 1.0)

    def test_missing_commands_lower_recall(self) -> None:
        predicted = {"command_ids": (1, 2), "usb_pairs": (), "devno_nodes": ()}
        actual = {"command_ids": (1, 2, 3, 4), "usb_pairs": (), "devno_nodes": ()}
        self.assertAlmostEqual(score(predicted, actual)["command_recall"], 0.5)

    def test_predicting_nothing_scores_zero_not_one(self) -> None:
        # An empty prediction must not score 1.0 by having nothing wrong with it.
        predicted = {"command_ids": (), "usb_pairs": (), "devno_nodes": ()}
        actual = {"command_ids": (1, 2), "usb_pairs": ((0x54C, 0x448),), "devno_nodes": ("usb/std",)}
        result = score(predicted, actual)
        self.assertEqual(result["command_recall"], 0.0)
        self.assertEqual(result["usb_match"], 0.0)

    def test_extra_commands_do_not_count_against_recall(self) -> None:
        # Recall measures how much of the real surface was found; over-prediction is reported by
        # a separate figure rather than folded into recall.
        predicted = {"command_ids": (1, 2, 3, 4), "usb_pairs": (), "devno_nodes": ()}
        actual = {"command_ids": (1, 2), "usb_pairs": (), "devno_nodes": ()}
        self.assertEqual(score(predicted, actual)["command_recall"], 1.0)


class HeldOutTests(unittest.TestCase):
    def test_an_empty_body_list_returns_no_scores(self) -> None:
        self.assertEqual(score_held_out([], hold_out=("a6600",)), [])

    def test_scores_are_reported_only_for_the_named_bodies(self) -> None:
        bodies = [
            {"name": "a6400", "command_ids": (1, 2, 3)},
            {"name": "a6600", "command_ids": (1, 2, 3, 4)},
        ]
        scores = score_held_out(bodies, hold_out=("a6600",))
        self.assertTrue(all(s["body"] == "a6600" for s in scores),
                        "a fitted body must never appear in the held-out report")


if __name__ == "__main__":
    unittest.main()
