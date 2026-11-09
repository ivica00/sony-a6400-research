# E0236 — Physical journal attempt: invalid letter path and self-reboot fault

Date: 2026-11-09. Two bounded physical sessions of the E0235 journal collector. No SD write occurred. The camera self-rebooted twice around PC Remote transitions; physical PC Remote switching is stopped pending isolation.

## Journal write session (17:39:53)

Staged at `artifacts/hardware/uvc-monitor-sd-journal-e0235-write-2` with build SHA-256 `eaca44c7…530e98`, five fresh RAM paths, READY PID 1345. The user switched the camera to ordinary PC Remote; the collector ran its fixed steps and wrote a 15,007-byte receipt.

| Step | Command | Observed | Verdict |
| --- | --- | --- | --- |
| 0 | `IFSYS getdriveinfo A` | `result = 0x00000000`, `filesystemType = 0x0003` | pass |
| 1 | `IFSYS cmp <expected> <expected>` | no open/differ message | pass |
| 2 | `IFSYS cmp A:/a6400_journal_e0235.dat A:/…` | `Can't open file A:/a6400_journal_e0235.dat` | pass (treated as absence) |
| 3 | `IFSYS writeandflash A:/… 64 0xE0235000` | `Fsys_Open err 0x80000041` | **fail** |

The write handler never received a handle, so no file was created and no bytes were written. The collector stopped and wrote `JOURNAL_SESSION_COMPLETE mode=write steps=7 result=0`. Recovery verified TracerPid 0/no `usbg_video`, byte-equal receipt/stdout, helper exit, and removed the five owned RAM files.

### Path finding

The observed `Fsys_Open err 0x80000041` is `Fsys_Open`'s **`CreatePathInfo` failure** fallback (the resolver's empty-letter error is `0x80000031`). Offline execution of the original bodies in E0237 confirms it: `A:/A6400J.DAT` is accepted while `A:/a6400_journal_e0235.dat` is rejected, i.e. the 21-character stem violates the 8.3 name limit. The earlier reading that the PC Remote letter table was empty is **superseded**: the same session's E0233 identity guard found the mount record, and an empty letter would have produced `0x80000031`, not `0x41`. Step 2's `Can't open file` was therefore the same normalizer rejection, not proof of absence. A future attempt must use an 8.3 letter path such as `A:/A6400J.DAT`; the device path `/dev/mmca/A6400J.DAT` also normalizes offline, but `IFSYS cmp` treats a leading `/` as a Linux file, so only the letter form supports the current readback.

Readback is also constrained: `IFSYS cmp` treats a leading `/` as a Linux file, so it cannot compare a device-path PrFile; only `dump` (raw `printf` hex) could read it, and whether that `printf` reaches the monitor output ring is unverified.

## Probe attempts and reboot fault

- First probe: staged 17:47:25 during a boot that started 17:47:13 (12 s uptime; the stage then had no boot gate). The camera appeared as `054C:0CAA` at ≈17:47:29, the RAM files disappeared, and no receipt existed; the session is retained as failed evidence.
- Second probe: staged 17:53:03 after adding a boot-stability gate (uptime 347 s). The camera booted again at **17:53:04** (post-recovery `/proc/uptime` 185.27 s at 17:56:09). The user reports: “when I changed to PC Remote, camera rebooted itself.” Helper PID 826 exited and all five RAM files were cleared by the reboot; no receipt was recoverable.
- Third probe: staged 18:01:44 after adding a 30 s settle sleep and a boot gate (uptime 518 s). The collector performed **no `/dev/mem`, ring or process-memory access** before the switch. The user reports the camera restarted the instant PC Remote was selected in the menu, again destroying the RAM session. This makes the reboot **switch-triggered, not collector-triggered**; the probe was read-only and no SD write was possible.
- Kernel command line contains `exception.reboot=1` and `wdt.timeout=500`; there is no `/proc/last_kmsg`, `/sys/fs/pstore` or `/dev/kmsg` to recover a panic record. `/setting/a6400_usb_debugd.log` holds only cumulative registration/failed-response lines without timestamps or reboot entries. `/log/feeder.log` is the old E0207 UVC feeder record, not related to these sessions.
- The first reboot (17:47:13) occurred before any probe collector was launched; the second and third coincided with the menu switch while the collector was idle or asleep. A camera-side exception during the PC Remote/USB reconfiguration is the working explanation. Because the camera boots normally afterwards and the collector is exonerated, the remaining candidates are the persistent debug-link/USB state, the SD/application database presented at PC Remote entry, or a camera-side fault condition. These have not been separated.

## Host-side WPD timing

Windows `Microsoft-Windows-WPD-MTPClassDriver/Operational` events for this window:

| Host time | Event | Meaning |
| --- | --- | --- |
| 17:40:31 | 1000/1001/1003 | PC Remote device arrived for the write-2 session |
| 17:42:18 | 1002 | device removed after return to MSC |
| 17:47:35 | 1000/1001/1003 | PC Remote device arrived **after** the 17:47:13 boot |
| 17:51:08 | 1002 | removed |
| 17:53:32 | 1000/1001/1003 | arrived **after** the 17:53:04 boot |
| 17:55:32 | 1002 | removed |
| 18:02:25 | 1000/1001/1003 | arrived after the ≈18:01:45 entry; camera still in PC Remote |

The **first** PC Remote entry at 17:40:31 succeeded and the write-2 session ran normally (no boot before 17:42). Every later entry arrives only after a boot, i.e. the camera restarted during entries at ≈17:47, ≈17:53 and ≈18:01. Because the fault persists across those reboots, a persistent camera-side state (SD/application database, `/setting`, or the USB/debug-link configuration) is more likely than transient RAM or the sleeping collector.

## Post-isolation observation (18:09)

The unplugged PC Remote switch itself was stable, but while the user was scrolling through the camera menu with **USB unplugged and PC Remote not selected**, the camera restarted at ≈18:09:01 and then entered PC Remote by itself. The fourth probe (staged 18:06:57) was killed and its RAM files cleared. Post-recovery `/proc/uptime` was 88.75 s at 18:10:30, matching that boot. This removes the USB link as a necessary condition and makes a persistent camera-side state (SD/application database or `/setting`) the leading candidate; no crash log is available and the debug-daemon log only gained registration lines. Camera recovery now takes precedence over further project tests.

## Idle/probe contrast and fifth reboot

- Idle session: staged 18:15:27 with build `0a11b40e`, collector opened its log/expected files and slept 90 s with **no `/dev/mem` or ring access**. The user switched to PC Remote and back; the camera did not restart (boot remained 18:09:01), the receipt `IDLE_SESSION_COMPLETE result=1` was recovered, and the five owned RAM files were cleaned.
- Probe-5: same binary and same sleep-before-access design (30 s settle), staged 18:19:39. The user switched to PC Remote and the camera rebooted at ≈18:19:56 **inside the settle sleep and before any command was published** (post-recovery uptime 73.32 s at 18:21:09, boot 18:19:56). No receipt survived.
- The idle and probe-5 runs are therefore the same process/file footprint during the switch; only the intermittent outcome differs. The reboot is **not deterministically caused by a specific collector mode or monitor command**. The staged collector plus PC Remote entry remains associated with the failures, but a camera-side intermittent fault cannot be excluded.

## State and stop condition

Final state after the user returned the camera: MSC `054C:0CA8` Status OK, `/proc/uptime` 188.60 s at 18:05:08 (boot at 18:01:59, matching the fourth restart), TracerPid 0, `/proc/modules` 42 entries without `usbg_video`, `/tmp_bt` free of `mon_sd_*`. No UVC activation, module, hook, mount or raw storage write occurred. The authorized SD journal remains **unwritten**; no `writeandflash` open ever succeeded, so no target file was created by this project.

All physical project tests are stopped until the camera is recovered. The unplugged PC Remote switch was stable, but the later menu scroll rebooted without USB and auto-entered PC Remote, so the fault is persistent camera-side state rather than the host link or the collector. Recommended user recovery order: (1) power off, remove the SD card, power on and scroll the menu for a few minutes — if it stays stable, the card/application database is implicated; (2) back up photos before any repair; (3) with the card reinserted use Sony's non-destructive “Repair Img. DB” or test a different card; (4) if it still reboots without the SD, consider “Reset Settings” (images are preserved) or Sony service. Do not format the card, enter service mode, update firmware or retry PC Remote. The journal, device-path probe and restart proof remain unwritten/unattempted.
