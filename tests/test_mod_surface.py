"""Contract tests for separating the runtime-writable surface from the flash boundary.

Two claims get confused in practice: "this is modifiable" and "this is flash-modifiable". The
first is a mounted filesystem the camera writes at runtime; the second is the encrypted,
checksum-verified image. This module keeps them apart, and the parser is strict on purpose: a
mount is written only when its option list says ``rw``, so an unexpected option set reads as
unknown rather than writable.

Offline only: the input is ``/proc/mounts`` text from a preserved read-only capture or a fixture.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "research"))

from mod_surface import flash_boundary, parse_mounts, writable_surface  # noqa: E402

SAMPLE = (
    "/dev/nflasha7 / ext2 ro,relatime 0 0\n"
    "/dev/nflasha10 /tmp vfat rw,relatime 0 0\n"
    "/dev/nflasha15 /usr ext2 ro,relatime 0 0\n"
    "/dev/root /var/tmp tmpfs rw,nosuid 0 0\n"
)


class ParseTests(unittest.TestCase):
    def test_readonly_is_read_from_the_option_list(self) -> None:
        mounts = parse_mounts(SAMPLE)
        self.assertEqual([m["readonly"] for m in mounts], [True, False, True, False])

    def test_fields_are_read_correctly(self) -> None:
        mount = parse_mounts(SAMPLE)[1]
        self.assertEqual(mount["device"], "/dev/nflasha10")
        self.assertEqual(mount["mount"], "/tmp")
        self.assertEqual(mount["fstype"], "vfat")

    def test_a_line_with_too_few_fields_is_ignored_rather_than_guessed(self) -> None:
        self.assertEqual(parse_mounts("garbage\n"), [])

    def test_an_option_list_without_ro_or_rw_reads_as_not_writable(self) -> None:
        # Anything that does not say "rw" is not claimed writable.
        mounts = parse_mounts("/dev/x /y ext2 0 0\n")
        self.assertEqual(writable_surface(mounts), [])


class SurfaceTests(unittest.TestCase):
    def test_writable_surface_excludes_read_only_mounts(self) -> None:
        self.assertEqual(writable_surface(parse_mounts(SAMPLE)), ["/tmp", "/var/tmp"])

    def test_flash_boundary_lists_read_only_nflasha_mounts(self) -> None:
        self.assertEqual(flash_boundary(parse_mounts(SAMPLE)), ["/", "/usr"])

    def test_a_writable_nflasha_mount_is_not_in_the_flash_boundary(self) -> None:
        mounts = parse_mounts("/dev/nflasha10 /tmp vfat rw 0 0\n")
        self.assertEqual(flash_boundary(mounts), [])

    def test_a_non_nflasha_read_only_mount_is_not_flash(self) -> None:
        mounts = parse_mounts("/dev/sr0 /media iso9660 ro 0 0\n")
        self.assertEqual(flash_boundary(mounts), [])


if __name__ == "__main__":
    unittest.main()
