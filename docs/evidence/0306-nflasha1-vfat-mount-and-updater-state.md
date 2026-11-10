# E0306 — read-only nflasha1 vfat dump, the observed `/mnt` mount/umount contract, and the updater-state read

Date: 2026-11-10. **Authorized read-only camera operations only** (user
authorization continues from E0305). No camera write, no mode switch, no SD
access, no writable internal flash. **No GUI frame.** The VBUS input remains a
labelled experiment; this note adds a media/updater side path.

## 1. Why

E0305 advanced the app past the MPR boundary to
`mount("/dev/nflasha1","/mnt","vfat",…,"posix_attr")`. The retained firmware has
no nflasha1 image (the only same-size image belongs to the ZV-E10 reference and
is not identity-matched), so the truthful next step is another read-only camera
dump plus a bounded read-only mount contract.

## 2. Read-only nflasha1 dump (camera)

Same method as E0305: `tools/camera_debugger.py` read operation only; camera in
normal MSC mode; app PID 149 fd 29 untouched.

* Precheck: `/dev/nflasha1` block **252:1**, sysfs size **16,256 sectors =
  8,323,072 B**, `ro=0`, not mounted. `mount.conf` record:
  `/dev/nflasha1 none vfat 8323072 16384`.
* Script `artifacts/analysis/e0308-nflasha1-dump.py`; output
  `artifacts/hardware/nflasha1-readonly/nflasha1-8323072.bin`
  **8,323,072 B, SHA-256 `b264e1e61bde1808dbe4b14df834933040af6a48f90e89bb08338ca07515451f`**,
  2,048 chunks of 4,064 B, 52.021 s.
* Re-read equality at offsets 0, 16,384 and 8,319,008 matched the saved bytes.
* Camera uptime 27,016.25 s → 27,344.68 s across the whole read; fd 29 unchanged;
  final `ls /tmp_bt | grep mpr|nflasha` empty; no reboot, no mode switch.
* Manifest/receipts: `artifacts/hardware/nflasha1-readonly/` (manifest, dump log,
  precheck, final check).

## 3. Image shape (read-only FAT12)

`src/a6400/execution/guest_vfat.py` parses the dump read-only (FAT12/16/32
supported; no write path, bytes only from the image):

| field | value |
| --- | --- |
| bytes/sector | 512 |
| sectors/cluster | 32 (16 KiB, matches mount.conf) |
| reserved / FATs / FAT size | 1 / 2 / 32 sectors |
| root entries | 512 (fixed root, FAT12) |
| total sectors / clusters | 16,256 / 504 |
| root dir / data start | 33,280 / 49,664 |

Tree (7 files, 1 directory):

| path | size | SHA-256 |
| --- | --- | --- |
| `boot/kemco.txt` | 816 | `abcd32dc…634210` |
| `boot/loadaddr.txt` | 33 | `a55bb7c1…23200d` |
| `boot/initrd.img` | 4,354,048 | `e6315bf0…4f1845` |
| `boot/vmlinux.bin` | 1,697,068 | `7d61feae…79311f` |
| `p1chksum` | 105 | `d619b881…d5748b` |
| `dat2` | 4 (`11 00 03 81`) | `d8f765f2…4ffc64` |
| `dat3` | 4 (`00 00 00 00`) | `df3f6198…b81119` |

This is the boot/updater vfat partition. The model reads it; it is not mounted by
the emulator at boot.

## 4. Observed mount contract

New opt-in `--mount-service observed-nflasha1` (default `stop`):

* the mount syscall (`r7=21`) is served **only** for the exact E0307-observed
  arguments: source `/dev/nflasha1`, target `/mnt`, fstype `vfat`, flags
  `3236757505`, data `posix_attr`; strings are read with a bounded guest
  cstring reader (fstype/data are relative strings, not guest paths). Any other
  mount is an explicit `unsupported_mount_contract`;
* on a match the hash-checked nflasha1 image is materialised under `/mnt` as
  read-only nodes/cache (`GuestFilesystem.mount_vfat`); the mounted target stops
  being an unknown runtime namespace;
* `umount2` (`r7=52`) is served only for target `/mnt`, flags 0; it restores the
  original `/mnt` manifest node and removes the materialised nodes/cache;
* the image identity is verified from the manifest before execution; the default
  and earlier policies are unchanged; no write/mmap/device operation is served.

## 5. Bounded run

Resume `boot-e0307-live-dump2.ckpt` (235,778,358, mount boundary) with
`--nflasha4-device observed-dump --mount-service observed-nflasha1` and the
same E0303-G5 policies; no new injection.

| run | instruction | result |
| --- | --- | --- |
| `e0309-live-mount.json` | 235,778,360 | first attempt: fstype/data decoded as null (paths are relative) → `mount_arguments_not_observed`; fixed by using the cstring reader |
| `e0310-live-mount2.json` | **235,790,039** | mount served; `/mnt/dat2` and `/mnt/dat3` opened/read (4 B each); `umount2("/mnt",0)` served; then stops at `open("/setting")` |

The app's actual sequence after mount:

```
mount("/dev/nflasha1", "/mnt", "vfat", 0xC0ED0001, "posix_attr") -> 0
open("/mnt/dat2", O_RDONLY)  -> fd 32, size 4, sha256 d8f765f2…4ffc64
read(fd, 4)                  -> 4 bytes (11 00 03 81)
close(fd)
open("/mnt/dat3", O_RDONLY)  -> fd 32, size 4, sha256 df3f6198…b81119
read(fd, 4)                  -> 4 bytes (00 00 00 00)
close(fd)
umount2("/mnt", 0)           -> 0
open("/setting", O_RDONLY)   -> boundary runtime_namespace_not_supplied
```

So the app reads the updater state words (`dat2`/`dat3`) and immediately
unmounts; the vfat path is a bounded boot/update state check, not media
streaming.

**Still no USB FSM transition**: at 235,790,039 / 61 threads,
`UsbControl` (1018), `UsbBusPower` (1016) and `BusPower` (1022) remain
`blocked_futex`; `usb_otgcore.config` is `None`; `viewUnified2` is not loaded;
OSD A/B are unmapped; no GUI frame.

## 6. Boundary and next

The next side path is **`open("/setting")`**: `/setting` is the camera's
nflasha2 vfat partition (mount.conf: `/dev/nflasha2 /setting vfat 20971520
16384`), currently an unknown runtime root. Continuing truthfully needs
(a) a read-only nflasha2 dump, (b) materialisation of `/setting` as a read-only
namespace (not a new mount), and (c) directory-open/`getdents` semantics if the
app enumerates it. Only the existing `observed-e0301` F_OK access answers are in
place today; no directory fd, `getdents` or file bytes are supplied.

Other open lanes are unchanged: the UVC/PTP-relevant USB receive id/SETCONFIG,
the `0x008F013A` relayed-notification consumer, the buspwr port-type reply, the
otgcore PTP/UVC templates, and the unresolved fresh-path tzset CPU defect. The
physical UVC/PTP lane remains paused.

## 7. Artifacts

* Dump/analysis: `artifacts/hardware/nflasha1-readonly/` (image, manifest,
  receipts), `artifacts/analysis/e0308-nflasha1-dump.py`,
  `e0308-vfat-tree.py`, `e0308-vfat-files.py`, `tree.json`.
* Reader/policy: `src/a6400/execution/guest_vfat.py`,
  `tests/test_guest_vfat.py`; `GuestFilesystem.mount_vfat/umount_vfat` and the
  mount/umount handlers in `interpreter_probe.py`; session/CLI
  `--mount-service`.
* Runs: `artifacts/analysis/e0309-run-live-mount.py`,
  `e0310-run-live-mount2.py`; reports `artifacts/execution/e0309-live-mount.json`,
  `e0310-live-mount2.json`; checkpoints `boot-e0309-live-mount.ckpt`,
  `boot-e0310-live-mount2.ckpt`.

## 8. Checks

Full suite **867 tests OK** (18.203 s) after the vfat reader/mount contract and
tests were added. This note establishes no UVC/PTP function and no GUI frame.
