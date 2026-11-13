#!/usr/bin/env python3
"""Predict a body's surface from packaged firmware, then score the prediction on held-out bodies.

A description lists what was read. A model predicts what it did not read, and this module is the
only place in the platform work where that distinction is tested: the rule is fitted on some
bodies and scored on bodies excluded from the fit. If every body the model is scored on was also
used to build it, the score measures memorisation.

Three figures, computed the same way for each body:

* **command_recall** — of the command ids the body actually has, how many the rule predicted.
* **usb_match** — whether the predicted stock USB pair set equals the body's.
* **devno_match** — whether the predicted device-node set equals the body's.

Recall is deliberate rather than precision: a rule derived from a ladder of command tables should
find most of a body's ids, while over-predicting is a different failure that recall does not
hide. An empty prediction scores 0, not 1.

Offline only.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _command_ids(root: Path) -> tuple[int, ...]:
    """The body's av-cam command ids, or an empty tuple when the image is not unpacked."""
    from av_command_table import find_table

    for candidate in root.rglob("av-cam.bin"):
        try:
            table = find_table(candidate.read_bytes())
        except (ValueError, OSError):
            continue
        return tuple(table.ids)
    return ()


def _usb_pairs(root: Path) -> tuple[tuple[int, int], ...]:
    """The stock USB descriptor pairs from the package's own ``config.yaml``."""
    config = root / "config.yaml"
    if not config.is_file():
        return ()
    text = config.read_text(errors="replace")
    section = text.split("normalUsbDescriptors:", 1)
    if len(section) < 2:
        return ()
    block = section[1].split("updaterUsbDescriptors:", 1)[0].split("fdat:", 1)[0]
    numbers: list[int] = []
    for token in block.replace("-", " ").split():
        if token.startswith("0x") or token.startswith("0X"):
            try:
                numbers.append(int(token, 16))
            except ValueError:
                continue
    return tuple((numbers[i], numbers[i + 1]) for i in range(0, len(numbers) - 1, 2))


def _devno_nodes(root: Path) -> tuple[str, ...]:
    """Device-node paths from the body's ``devno.ko``."""
    import importlib.util

    sibling = Path(__file__).resolve().parent / "uvc_enablement_manifest.py"
    spec = importlib.util.spec_from_file_location("uvc_enablement_manifest", sibling)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    from src.a6400.execution.zve10_uvc_enablement import parse_devno_table

    for module_path in root.rglob("devno.ko"):
        try:
            rows = parse_devno_table(module.devno_table_bytes(module_path),
                                     module_path.read_bytes())
        except Exception:
            continue
        return tuple(sorted(rows))
    return ()


def read_body(root: Path) -> dict[str, Any]:
    """Everything this module can read from one unpacked body."""
    return {
        "name": root.name,
        "command_ids": _command_ids(root),
        "usb_pairs": _usb_pairs(root),
        "devno_nodes": _devno_nodes(root),
    }


def predict(root: Path) -> dict[str, Any]:
    """The body's surface, read from its packaged files only."""
    return read_body(root)


def score(predicted: dict[str, Any], actual: dict[str, Any]) -> dict[str, float]:
    """How well ``predicted`` matches ``actual``.

    Every figure is 0.0 when the prediction is empty, so a model that predicts nothing cannot
    score well by having nothing wrong.
    """
    predicted_ids = set(predicted.get("command_ids") or ())
    actual_ids = set(actual.get("command_ids") or ())
    recall = len(predicted_ids & actual_ids) / len(actual_ids) if actual_ids else 0.0

    predicted_usb = set(predicted.get("usb_pairs") or ())
    actual_usb = set(actual.get("usb_pairs") or ())
    usb_match = 1.0 if predicted_usb and predicted_usb == actual_usb else 0.0

    predicted_nodes = set(predicted.get("devno_nodes") or ())
    actual_nodes = set(actual.get("devno_nodes") or ())
    devno_match = 1.0 if predicted_nodes and predicted_nodes == actual_nodes else 0.0

    return {"command_recall": recall, "usb_match": usb_match, "devno_match": devno_match}


def fit(bodies: list[dict[str, Any]]) -> dict[str, Any]:
    """The rule: a command id is expected on a new body when every training body has it.

    Deliberately conservative. Sony's command tables form a ladder, so the intersection is the
    part a body is unlikely to drop; predicting the union would score well on recall and be
    useless as a prediction.
    """
    training = [b for b in bodies if b.get("command_ids")]
    if not training:
        return {"command_ids": ()}
    shared = set(training[0]["command_ids"])
    for body in training[1:]:
        shared &= set(body["command_ids"])
    return {"command_ids": tuple(sorted(shared))}


def score_held_out(bodies: list[dict[str, Any]] | None,
                   hold_out: tuple[str, ...]) -> list[dict[str, Any]]:
    """Fit on the bodies not named in ``hold_out`` and report only the held-out scores.

    ``bodies`` may be a list of already-read body dicts (as the tests pass) or ``None`` for an
    empty run. The pointed rule: the held-out body's own tables are used only in ``score``, never
    in ``fit``, and a fitted body never appears in the output.
    """
    if not bodies:
        return []
    held = [b for b in bodies if b["name"] in hold_out]
    training = [b for b in bodies if b["name"] not in hold_out]
    if not held:
        return []
    rule = fit(training) if training else {"command_ids": ()}
    results: list[dict[str, Any]] = []
    for body in held:
        predicted = {"command_ids": rule["command_ids"],
                     "usb_pairs": (), "devno_nodes": ()}
        figures = score(predicted, body)
        results.append({"body": body["name"], **figures})
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--roots", nargs="+", type=Path, required=True,
                        help="unpacked body directories")
    parser.add_argument("--hold-out", nargs="+", required=True, help="body names to hold out")
    parser.add_argument("--emit-tsv", action="store_true")
    args = parser.parse_args(argv)

    bodies = [read_body(root) for root in args.roots]
    results = score_held_out(bodies, tuple(args.hold_out))
    if not results:
        print("no held-out body matched", file=sys.stderr)
        return 2
    if args.emit_tsv:
        print("body\tcommand_recall\tusb_match\tdevno_match")
        for row in results:
            print(f"{row['body']}\t{row['command_recall']:.3f}\t"
                  f"{row['usb_match']:.3f}\t{row['devno_match']:.3f}")
        return 0
    for row in results:
        print(f"{row['body']}: recall {row['command_recall']:.3f} "
              f"usb {row['usb_match']:.0f} devno {row['devno_match']:.0f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
