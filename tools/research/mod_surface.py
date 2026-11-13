#!/usr/bin/env python3
"""Separate what the camera lets you write at runtime from what the flash image allows.

Two claims are routinely confused: "this is modifiable" and "the firmware is modifiable". The
first is a mounted filesystem the running system writes; the second is the encrypted,
checksum-verified image this project measured in E0489. Keeping them apart is the difference
between an honest capability statement and a promise the evidence does not support.

The parser is strict on purpose: a mount counts as writable only when its option list says
``rw``. An option list that says neither reads as *not writable* rather than defaulting to yes,
because a wrong "writable" claim is a claim about safety.

Offline only: the input is ``/proc/mounts`` text from a preserved read-only capture or a fixture.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any


def parse_mounts(text: str) -> list[dict[str, Any]]:
    """``/proc/mounts`` lines as dicts, ignoring anything that is not six fields."""
    mounts: list[dict[str, Any]] = []
    for line in text.splitlines():
        fields = line.split()
        if len(fields) < 4:
            continue
        device, mount, fstype = fields[0], fields[1], fields[2]
        options = fields[3].split(",")
        mounts.append({
            "device": device,
            "mount": mount,
            "fstype": fstype,
            "readonly": "ro" in options,
            "writable": "rw" in options,
        })
    return mounts


def writable_surface(mounts: list[dict[str, Any]]) -> list[str]:
    """Mount points the running system can write, sorted."""
    return sorted({m["mount"] for m in mounts if m.get("writable") and not m["readonly"]})


def flash_boundary(mounts: list[dict[str, Any]]) -> list[str]:
    """Mount points on flash partitions that are read-only, i.e. where the image is frozen."""
    return sorted({m["mount"] for m in mounts
                   if m["device"].startswith("/dev/nflasha") and m["readonly"]})


def summarise(text: str) -> dict[str, Any]:
    """The two sets plus a plain statement of what each one means."""
    mounts = parse_mounts(text)
    writable = writable_surface(mounts)
    frozen = flash_boundary(mounts)
    return {
        "writable": writable,
        "flash_boundary": frozen,
        "statement": (
            f"{len(writable)} mount point(s) are writable at runtime; {len(frozen)} flash "
            "partition(s) are read-only. A writable mount is not a modified firmware image: the "
            "image itself is checksum-verified (E0489)."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("mounts", type=Path, nargs="?",
                        help="file containing /proc/mounts text; omit to read stdin")
    args = parser.parse_args(argv)

    text = args.mounts.read_text() if args.mounts else sys.stdin.read()
    result = summarise(text)
    print("writable at runtime:")
    for mount in result["writable"]:
        print(f"  {mount}")
    print("read-only flash partitions:")
    for mount in result["flash_boundary"]:
        print(f"  {mount}")
    print(result["statement"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
