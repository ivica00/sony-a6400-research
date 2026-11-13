# E0486 — Six writable mount points, three frozen flash partitions

Date: 2026-11-13. Offline: the mount layout recorded in the project's own live-capture notes, run
through a parser that is strict about what "writable" means.

This record exists to keep two claims apart. "The camera lets you write here at runtime" and "the
firmware image is modifiable" are different statements, and conflating them turns a routine
observation into a promise that E0489 shows is not supported.

## 0. Short answer

1. **Six mount points are writable at runtime**: `/setting`, `/system`, `/tmp`, `/log`,
   `/android/data`, `/lens`.
2. **Three flash partitions are read-only**: `/` (`nflasha7`), `/usr` (`nflasha15`),
   `/android/system` (`nflasha16`).
3. **A writable mount is not a modified image.** `/tmp` and `/setting` being writable says nothing
   about the image, which is CRC32/MD5 checked per E0489 and which this record does not touch.
4. **The parser refuses to guess.** A mount counts as writable only when its option list says
   `rw`; anything else reads as not writable, because a wrong "this is safe to write" claim is
   worse than a missing one.

## 1. The layout

| device | mount | fstype | writable at runtime |
| --- | --- | --- | --- |
| `/dev/nflasha2` | `/setting` | vfat | yes |
| `/dev/nflasha3` | `/system` | vfat | yes |
| `/dev/nflasha7` | `/` | ext2 | **no** |
| `/dev/nflasha10` | `/tmp` | vfat | yes |
| `/dev/nflasha11` | `/log` | vfat | yes |
| `/dev/nflasha15` | `/usr` | ext2 | **no** |
| `/dev/nflasha16` | `/android/system` | ext2 | **no** |
| `/dev/nflasha17` | `/android/data` | vfat | yes |
| `/dev/nflasha18` | `/lens` | vfat | yes |

```bash
python3 -I tools/research/mod_surface.py mounts.txt
# writable at runtime: /android/data /lens /log /setting /system /tmp
# read-only flash partitions: / /android/system /usr
```

## 2. What each set means for a modification

**Writable at runtime** is where a script can write without touching the image: staging a binary in
`/tmp`, changing a setting in `/setting`, keeping a log. Work that stays inside this set is
reversible by deleting a file, and it is what the community homebrew projects rely on.

**The read-only set is what a firmware modification would have to change**: `/` and `/usr` hold the
system and the application libraries (`libObj.so` lives under `/usr/lib`). Those are on flash, and
changing them is the claim E0489 measured the checks on — not this record.

**A third case the table hides.** `/system` (`nflasha3`) is writable and is *not* the root
filesystem; the similar name is exactly the kind of thing that produces a wrong conclusion. It
holds system data, while `/` holds the root filesystem. The parser reports what the device and
mount say; it does not resolve which one a reader means.

## 3. Alternative explanations

- **"Writable means the change survives a reboot."** Not claimed. `/tmp` (`nflasha10`) is a
  persistent vfat partition in the project's notes, but this record only says the mount is
  writable; persistence is a different property and needs its own measurement.
- **"Read-only at the mount level means unwritable at the device level."** No: a read-only mount is
  a kernel policy on a device that may still accept raw writes. The distinction matters because a
  raw write skips the filesystem and lands in the image-changes category.
- **"The layout is universal across the family."** Untested here. This layout is the a6400's; the
  other twelve bodies have their own partition tables, and one of them may differ.

## 4. Confidence and limitations

- **Verified:** the parser's behaviour on the layout above, and the two sets it produces.
- **Not verified:** that the camera's live `/proc/mounts` still matches this list. The input came
  from the project's preserved notes, not from a fresh capture, and a firmware update could change
  it.
- **Not claimed:** anything about writing to a device node directly, or about persistence across
  reboot, or about the other twelve bodies.

## 5. Dependent implementation

`tools/research/mod_surface.py` and 8 tests in `tests/test_mod_surface.py`. The tests pin the
strictness that makes this record usable: an option list without `rw` is not writable, a
non-`nflasha` read-only mount is not flash, and a writable `nflasha` mount is not in the flash
boundary.

## 6. Next experiment

Take one writable mount and one read-only one and test persistence across a power cycle for the
writable case. That converts "writable" into "survives reboot", which is the property a homebrew
project actually needs, and it needs a camera.
