# E0414 — read-only nflasha device check and boot-area (nflashaB0/B1) dumps

Date: 2026-11-12. **Authorized read-only camera operations only** (standing
authorization, 2026-11-10). No camera write, no dd on the camera, no ioctl, no
mode switch, no SD change, no internal-flash write. `/dev/nflasha2` and
`/dev/nflasha4` were not touched.

## 1. Why

E0413 listed the loader area `/dev/nflashaB0/B1` as "device nodes exist; image
not preserved" and named a read-only boot-area dump as the next physical step.
This record closes that gap and also re-verifies the requested normal-boot
device visibility.

## 2. Inputs and tooling

* Camera in normal Mass Storage mode; USB debugger `A6400_USB_DEBUG_V1`,
  protocol 2, daemon pid 749, transport `usb_extcmd`; camera device
  `VID_054C&PID_0CA8`.
* `tools/camera_debugger.py` `read`/`exec` operations only (`read` is
  camera-side `open(O_RDONLY)` + `pread`). Host cache:
  `artifacts/host-cache/comtypes-gen` (PMCA comtypes generation cannot write into
  site-packages under the workspace sandbox).
* Scripts: `artifacts/analysis/e-nflasha-readonly/{probe,probe2,dump,postcheck}.py`.
* Camera uptime 1,557.57 s → 1,846.30 s over the whole session (monotone, no
  reboot); PID 149 fd 29 → `/dev/nflasha4` unchanged; `/tmp_bt` empty.

## 3. Device exposure and readability

`ls -la /dev/nflasha*` and `cat /proc/partitions` (normal boot):

| device | block | sectors | bytes | in `/proc/partitions` | readable |
| --- | --- | --- | --- | --- | --- |
| `/dev/nflashaB0` | 252:126 | 8,192 | 4,194,304 | yes | **yes** |
| `/dev/nflashaB1` | 252:127 | 8,192 | 4,194,304 | yes | **yes** |
| `/dev/nflasha1` | 252:1 | 16,256 | 8,323,072 | yes | yes |
| `/dev/nflasha3` | 252:3 | 98,304 | 50,331,648 | yes | yes |

`/sys/block/nflashaB0/size` = `/sys/block/nflashaB1/size` = 8,192 sectors, `ro` =
0. A 512-byte read at offset 0 succeeded on all four; the subsequent full dumps
returned full 4,064-byte chunks at every offset. The boot area is **not**
hardware-locked after boot in this state.

## 4. Mount and free space

* `mount | grep mmc` → empty (exit 1); `/proc/mounts` has no `mmc*` entry. The SD
  (`mmca10` 250:10 = 7,782,400 KiB, `mmca10p1` 250:11 = 7,778,304 KiB) is
  exported as USB Mass Storage and is not a camera-side mount.
* `df -h` → `sh: df: not found` (127); `stat`/`which` are also absent, so the
  camera cannot report free space.
* Host binding is libusb-win32 (no drive letter/volume), so SD free space is not
  measurable in this state. Local C: free space was 698.68 GB.
* Therefore the literal `dd if=/dev/nflashaB0 of=<sd_mount>/...` has no
  camera-side target path; bytes were streamed to the host through the debugger
  read operation instead (strictly read-only on the camera).

## 5. Read-only dumps

| device | bytes | SHA-256 | nonzero | chunk | re-read |
| --- | --- | --- | --- | --- | --- |
| `nflashaB0` | 4,194,304 | `3db81064bbb62f2af3937bc68adac7b37482a8f3a582734cb2036fd5a3f4d260` | 72,955 | 4,064 B | 3/3 |
| `nflashaB1` | 4,194,304 | `bb9f8df61474d25e71fa00722318cd387396ca1736605e1248821cc0de3d3af8` | **0** | 4,064 B | 3/3 |
| `nflasha1` | 8,323,072 | `b264e1e61bde1808dbe4b14df834933040af6a48f90e89bb08338ca07515451f` | 6,026,371 | 4,064 B | 3/3 |
| `nflasha3` | 50,331,648 | `cd4178d4518e13c64630d9de62fdbfbc05c0774f1ee8291f9fc56998910719a6` | 16,336,222 | 4,064 B | 3/3 |

Hashes were computed while streaming and independently re-computed on the host
with `Get-FileHash -Algorithm SHA256` (identical). `nflasha1` equals the E0306
dump hash byte-for-byte, so that image is reproducible across sessions.

Bounded shape (not a format decode; content is not published):

* `nflashaB0`: `EXBL` magic at 0 (remaining header zero) and a second `EXBL` record
  at `0xcde0`; 70,256 non-zero non-`0xFF` bytes in the first ~160,492 B
  (ARM Thumb code + 564 printable strings ≥ 8 chars, incl. boot-loader style
  `INS:awake_cmd0`); the rest of the 4 MiB is zero-filled.
* `nflashaB1`: every byte is `0x00` — readable but carries no data; reads are
  full-length and stable, so this is not a read error. Distinguishing "zeroed"
  from an unmapped zero-backing is **not** possible from this observation.
* `nflasha3` is the mounted-rw `/system` vfat (FAT12 boot sector); the dump is a
  byte dump, not an atomic filesystem snapshot.

Cross-reference: the preserved updater `bin/pformat.elf` contains the same `EXBL`
literal and an `awake_*`/`bp_*` config-key namespace (`awake_cmd0`, `awake_start`,
`awake_memaddr`, `awake_entry`, `awake_loadsize`, `bp_entry`, `bp_loadsize`), which
is consistent with a boot-area format programmed by Sony tooling. This is a
format/context match only; **no preserved image is identity-matched** and no
loader behaviour is claimed.

## 6. Verification and boundaries

* Host re-hash matches; re-read equality at three offsets per device; final
  postcheck (`/proc/uptime`, `/dev/nflasha*`, `/proc/partitions`, `mount`,
  `/proc/mounts`, PID 149 fd 29, `/tmp_bt`) is unchanged from the precheck.
* Boundaries: no loader format decode; `/dev/nflashaB1` content is all-zero with
  unknown provenance (zeroed vs zero-backing); `nflasha3` snapshot is not atomic;
  SD filesystem free space is unmeasurable in this binding; `/dev/nflasha2`
  (setting/Backup) and `/dev/nflasha4` (MPR) were intentionally not accessed.

## 7. Artifacts

`artifacts/dumps/a6400-nflasha-readonly/` (README, `manifest.json`, per-device
`.bin`, shape JSON, receipts, dump logs); scripts in
`artifacts/analysis/e-nflasha-readonly/`. `artifacts/` is git-ignored, so the
large images stay local.

## 8. Next

The boot area is now preserved read-only. A future step can statically compare
the `EXBL` header/record format against updater tooling, or cross-match the
`nflashaB0` payload against an update package loader if one is ever preserved.
No write, flash-update or mode-switch work is authorized by this record.
