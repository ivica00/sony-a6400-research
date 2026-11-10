# E0307 — read-only nflasha2 `/setting` namespace, UIPC unregister, and reaching the app's idle/poll state

Date: 2026-11-10. **Authorized read-only camera operations only.** No camera
write, no mode switch, no SD access, no writable internal flash. **No GUI frame.**
The VBUS/event injections remain labelled experiments.

## 1. Read-only nflasha2 dump

Same method as E0305/E0306 (native USB debugger read operation only; camera in
normal MSC mode; app PID 149 fd 29 untouched).

* Precheck: `/dev/nflasha2` block **252:2**, sysfs size **40,960 sectors =
  20,971,520 B**, `ro=0`, mounted at `/setting` (rw) on the camera.
  `mount.conf`: `/dev/nflasha2 /setting vfat 20971520 16384`.
* Script `artifacts/analysis/e0311-nflasha2-dump.py`; output
  `artifacts/hardware/nflasha2-readonly/nflasha2-20971520.bin`
  **20,971,520 B, SHA-256 `4d3269e51af1e48ac8af11775cf59ce111ff2cdd7cd9601911ac4f2f82c7f6fa`**,
  5,161 chunks of 4,064 B, **38.857 s**; re-read chunks at 0 / 32,768 / last
  matched; camera responsive (uptime 27,016 → 28,796 s; final fd 29 check clean;
  no `/tmp_bt` helper files). Manifest/receipts under
  `artifacts/hardware/nflasha2-readonly/`.

## 2. `/setting` image shape

FAT12 (512 B sector, 32 sectors/cluster, 2,560 root-dir start, 1,278 clusters):
62 files, 5 directories, 8,659,836 bytes of file content. Read-only parse only
(`guest_vfat.VfatImage`); notable entries: `.etools`, `.hasp`, `Backup.bin`,
`Backup.bak`, `DmmConfig.bin`, `psd.bin`, `kemco.txt`, `facedmy.bin`,
`facerec0..7.bin`, `mode/`, `gps/`, `appfw_infra/`, `updater/{comp,dat4}`
(`dat4` = 2 B, SHA-256 `fcf0a6c7…c5177f`), plus the **authorized research
payloads placed under `/setting` by earlier physical sessions** (USB debugger
launcher/daemon, input/touch probes, logs). Those payloads stay local; this note
publishes neither their bytes nor any secrets. No settings value is fabricated.

## 3. New emulator contracts

### `/setting` namespace (`--setting-service observed-nflasha2`)

The hash-checked nflasha2 dump is materialised read-only under `/setting`
(`GuestFilesystem.mount_vfat('/setting', image)`; 62 files / 5 directories, bytes
served from the image/cache; no write node). Default `stop` is unchanged. The
existing `observed-e0301` F_OK answers for `/setting` and `/setting/gps` remain.

### Directory open + `getdents64`

`GuestFilesystem` now opens a resolved directory as a read-only descriptor
(`device='directory'`, bounded child list) and serves `getdents64` (syscall 217)
with bounded `linux_dirent64` records (`.`, `..`, then children; no buffer
overrun; EOF semantics; `ENOTDIR` for non-directory fds). Unit-tested with a
constructed FAT12 image. **Note:** in the retained run the app read
`/setting/updater/dat4` directly, and no directory-open/`getdents` event was
recorded for the retried `open("/setting")`; the directory path is therefore
unit-tested but not observed in this run. Do not claim otherwise.

### UIPC unregister (`0x80000009`, opt-in `kernel-e0301`/`kernel-e0303`)

The retained state stopped on `ioctl(fd=3, cmd=0x80000009)`. The argument struct
at the boundary holds `{queue=0x004b024e, handle=0x104a (4170), …}` and handle
4170 is exactly the registered callback with that queue. Contract implemented:
remove only a registered callback whose `queue` and `handle` match; reject
inflight/sync-inflight callbacks and stale/forged identities explicitly
(`uipc_unreg_callback_identity_not_supplied` / `…_inflight`); legacy policy keeps
the boundary. No message/free side effects.

## 4. Bounded runs

All resume with the E0303-G5 policies plus
`--nflasha4-device observed-dump --mount-service observed-nflasha1
--setting-service observed-nflasha2`; `--uipc-pool-options kernel-e0301` matches
the checkpoint.

| run | instructions | result |
| --- | --- | --- |
| `e0312-live-setting.json` | 235,810,681 | `/setting/updater/dat4` opened/read twice (2 B, SHA `fcf0a6c7…`); stops at UIPC unregister call `0x80000009` |
| `e0313-live-setting2.json` | **254,922,253** (timeout 150 s) | both unregisters served (`{queue 0x4b024e, handle 4170}`, `{0x4b0243, 4169}`); infrastructure continues (libInfraIPTC, libInfraCacheMgr, stream2); 67 threads; ends in a `RCV_MSG_TMO` poll loop (ioctl `0x80000007`, tmo 0 → `-1022`) with no contract boundary |
| `e0314-live-usbwake.json` | 268,757,618 (timeout 120 s) | resume from the 254.9M checkpoint with the verified VBUS body and the corrected subtype-2 event record; both inputs accepted/woken but **no USB FSM transition** |

At the timeouts `UsbControl` (1018), `UsbBusPower` (1016) and `BusPower` (1022)
remain `blocked_futex`; `usb_otgcore.config` is `None`; `usb_event` context is
190584; the VBUS consumer is still handle 4106 on queue `0x012002DA`; no
`viewUnified2`/OSD mapping and no frame.

## 5. Boundary and next

The app is now in a bounded **idle/poll state**, not at a device boundary: it
polls a UIPC queue with timeout 0 and waits on the USB/service tier. The next
contracts are the UVC/PTP-relevant ones: UsbControl's runtime receive id and the
inbound SETCONFIG message, the buspwr port-type reply, the `0x008F013A`
relayed-notification consumer, or the actual consumer/timing for the
`RCV_MSG_TMO` poll loop. Do not treat the poll loop as success or drive it with a
fabricated queue message. The physical UVC/PTP lane remains paused.

## 6. Artifacts

* Dump: `artifacts/hardware/nflasha2-readonly/` (image, manifest, receipts),
  analysis scripts `e0311-nflasha2-dump.py`, `e0311-vfat2-tree.py`.
* Code: `src/a6400/execution/guest_vfat.py`, `guest_filesystem.py`
  (directory/getdents, mount/umount), `guest_uipc.py` (unregister); tests
  `tests/test_guest_vfat.py`, `tests/test_uipc_unregister.py`,
  `tests/test_guest_filesystem.py`.
* Runs: `artifacts/analysis/e0312-run-live-setting.py`,
  `e0313-run-live-setting2.py`, `e0314-run-live-usbwake.py`; reports
  `artifacts/execution/e0312-live-setting.json`,
  `e0313-live-setting2.json`, `e0314-live-usbwake.json`; checkpoints
  `boot-e0312-live-setting.ckpt`, `boot-e0313-live-setting2.ckpt`,
  `boot-e0314-live-usbwake.ckpt`.

## 7. Checks

Full suite **873 tests OK** (18.579 s) after the `/setting`, directory,
`getdents64` and UIPC-unregister work. No UVC/PTP function, no GUI frame and no
physical deployment claim.
