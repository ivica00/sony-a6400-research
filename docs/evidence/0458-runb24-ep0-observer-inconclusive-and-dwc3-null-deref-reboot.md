# E0458 — Run B24: corrected composite harness, fixed workqueue teardown, Inconclusive OBS timeline, new dwc3 IRQ NULL-deref reboot

Date: 2026-11-13. ONE supervised camera session, authorized explicitly before it
started. Camera: ILCE-6400, kernel `3.0.27_nl-rt106`. No retry was made.

## 1. Purpose

The one deliverable question: does the camera handle the UVC `GET_CUR`
`VIDIOC_QUERYCAP`-probe status stage late (~5 s) or promptly, measured by
comparing the E0446 `[a6400_uvc] OBS ...` lines against the host's ~5.01 s Stop
Endpoint in the Windows USB ETW trace. Run B23 failed because the harness waited
for the wrong PID (`054C:0CAA` instead of the authored `054C:0322`); B23 also
rebooted the camera in `__queue_work` because its observer/restore `work_struct`
was zero-initialised (E0453). This run used the corrected harness and the fixed
module (E0456).

## 2. Preconditions and identity

* Build: `artifacts/native/uvc-transport-e0455-obs-fixed/usbg_video_a6400_shared_candidate.ko`,
  **82,532 B**, SHA-256 `2c6f82e9ce6a1cbffa2b0f608badb3a4172b88ce23ad1a4f212e9fe0496da7fe`
  (E0456: work-struct self-init, schedule guard).
* Transport audit: `offline_module_audit_passed`, mode `transport`, **117 / 8 / 0**
  (`artifacts/analysis/uvc-transport-e0455-obs-fixed-audit/manifest.json`).
* Daemon: `camera-daemon/build/a6400-lived` SHA-256 `990475753ecf20e02a9b5c7b095a74606bf72c710271148d939f7edd910b2f16`.
* Camera was in stock MSC `054C:0CA8`, debugger protocol 2, PID 149 not traced,
  `usbg_video` not loaded. `/tmp_bt` was read-only on this boot, so the standard
  1 MiB tmpfs was mounted first (`mount -t tmpfs -o size=1m,mode=0755 tmpfs /tmp_bt`,
  rc=0) — this is the documented deploy environment, not a firmware change.
* Harness (host-only) `artifacts/analysis/e0457-runb24-ep0-observer/runb24.py`
  with `prep/arm/wait-composite/ffmpeg/wait-restore/collect`; ETW control
  `etw.ps1` (validated start/stop 3 s before the run); ETW providers USBPORT,
  USBHUB3, USBXHCI, UCX.

## 3. Session sequence (times UTC)

| time | event |
|---|---|
| 00:12:52.3 | ETW capture started |
| 00:12:5x | module + daemon deployed to `/tmp_bt`, `insmod`, mknod, daemon armed (`--arm-transport --wait-pcremote --duration 45 --sd-log --sd-mount --dmesg-sd`); daemon pid 1907 |
| ~00:13:0x | operator switched camera to PC Remote (MENU → Setup → USB Connection) |
| — | **authored composite `054C:0322` enumerated with `MI_01` (Camera) + `MI_00` (WPD) — detected by the corrected wait condition** |
| 00:13:40.7 | single ffmpeg DirectShow attempt started (8 s settle after detection) |
| 00:13:41.2 | camera `[a6400_uvc] OBS start dwc=689e5810` (first UVC class request) |
| 00:13:51.3 | ffmpeg attempt failed after 10.599 s ("Could not RenderStream to connect pins", no frame) |
| 00:14:09.9 | camera: `Unable to handle kernel NULL pointer dereference at virtual address 00000000`, task `(null)(irq/229-dwc3)` pid 55 |
| 00:14:23.2 | ETW stopped; 0CA8 already re-enumerated (auto-recovered MSC) |
| 00:14:2x | camera warm-rebooted (new warmboot segment); recovered as stock MSC without operator action |
| 00:14:5x | debugger revived with the documented Senser terminal cycle (read-only evidence recovery); ring/dmesg dumped |

## 4. Host side: the two 5.01 s EP0 transactions (ETW decode)

ETW: `usb-capture.etl` **235,855,872 B**, SHA-256
`8a5ec1b290be0c07c876cc3eafdbb6513fe12635f07948f21bbebed50728b30c`;
t0 = `2026-11-13T00:12:52.227Z` (tracerpt XML 2,218,396,735 B;
`ctrl-urbs.xml` 2,308 events, `usbhub3.xml` 4,511 events).

Sony control transfers on the `054C:0322` device pointer (UCX `fn=0x1B`):

| +t / UTC | transfer | duration | stop status |
|---|---|---|---|
| +48.979 / 00:13:41.206 | **GET_CUR** `0xA1 0x81 wValue=0x0100 wIndex=2 wLength=0x1A` | **5.005387 s** | `0x0` (stop completed) |
| +53.985 / 00:13:46.212 | **SET_CUR** `0x21 0x01 wValue=0x0100 wIndex=2 wLength=0x1A` | **5.011146 s** | `0xC0010000` (canceled) |
| +58.996 / 00:13:51.223 | GET_CUR (retry) | 0.002314 s | `0xC0000011` (stalled/canceled) |

Total ≈ 10.02 s, matching the single ffmpeg attempt's 10.599 s. This is the same
signature as E0446/B21: the host had to abort/stop the UVC probe control
transfers after ~5 s each. The first GET_CUR's Stop Endpoint completed normally
(`0x0`) after 5.005 s — i.e. the host never completed the status stage promptly.

## 5. Camera side: what the observer produced

SD daemon log (read-only SCSI extraction, `A6400K.LOG` 15,082 B SHA
`cc650f39…`; `A6400RCPT.JSON` 2,390 B SHA `10a70797…`; `A6400LD.LOG` 7,767 B
SHA `38af3b6a…`):

```
[ 1320.259] [a6400_uvc] reference START entry iface=2 count=1
[ 1320.259] [a6400_uvc] reference START returned iface=2 count=1
[ 1336.673699] [a6400_uvc] OBS start dwc=689e5810
```

and **nothing else**: no `OBS <n>` rows, no `OBS done`. Receipt:
`status=clean exit=0 duration_s=45 uptime_ms=79305 get_jpeg_polls=1201
sd_log.mounted=1 verified=1 receipt_written=1 lifecycle.stop_verified=0`.

Crucially, `A6400LD.LOG` shows the teardown **completed**:
`stream_stopped reason=duration_elapsed` → `teardown_begin` → `set_path_stop
status=0` → `dmm_rule_0 status=0` → `uvc_unreg rc=0` → **`uvc_stop verified=1
state=0,0,0,0`** → `ptrace_freeze_for_retire`. In B23 the same point hit the
`__queue_work` BUG_ON and rebooted. **The E0456 workqueue fix worked: the B23
`__queue_work` BUG did not recur.**

Warm klog ring after recovery (`klog-ring.bin` 84,407 B SHA `930446b8…`,
`verified=True`, 3 boot segments, `wrap=0`):

* boot segment 1 (session boot): `... reference START ... OBS start dwc=689e5810`,
  then **no OBS rows**;
* boot segment 2 (current boot): a warm boot created after the session;
* crash in session boot at **`[ 1365.403530] Unable to handle kernel NULL pointer
  dereference at virtual address 00000000`**, `[current task] program:
  (null)(irq/229-dwc3) (pid: 55)`, `current->mm->mmap is NULL`,
  `[Exception Syndrome] vector exception (0x000) at 0x00000000`, then
  `Entering exception monitor` → camera rebooted.

Anchor: `OBS start` printk `1336.673699` ↔ ETW GET_CUR start
`00:13:41.206Z`, so printk ≈ UTC − `1336.674 s` and the NULL-deref crash
`1365.403530` ↔ **`00:14:09.936Z`, 28.73 s after OBS start** — during the
session (the daemon's scheduled teardown was ≈15 s later at camera monotonic
~1380.6 s). The crash is in the **dwc3 IRQ thread**, not the observer's kworker
and not `__queue_work`; it is a new, separate teardown/EP0-adjacent fault that
the workqueue fix did not address.

## 6. Verdict

**Inconclusive.** Neither S1 nor S2 is established.

* Host condition for the comparison is proven: GET_CUR issued to the authored
  composite and the Stop Endpoint completed after 5.005 s; SET_CUR took
  5.011 s.
* Camera-side condition is missing: the observer printed `OBS start` (so the
  CLASS callback ran and the fixed work item was scheduled without BUGging), but
  no OBS row was ever recorded, in RAM (ring) or on SD. Because the rows are
  buffered until the end of the 1500-iteration poll loop, and the camera hit a
  NULL-pointer oops 28.73 s after start and then rebooted, the observer
  timeline was lost. From this run alone it is not possible to distinguish
  "work item never executed" from "loop had not finished when the crash/reboot
  hit" — both would leave exactly this evidence.

Consequences: the S1 ("status armed promptly, host never completed it") vs S2
("status stage handled ~5 s late") question remains undecided. The measurement
must be repeated once the observer prints each row **immediately** (plus an
explicit `OBS work enter`) and the dwc3 IRQ NULL dereference is fixed, so a
late camera reboot cannot erase the timeline.

## 7. Safety record (record exactly as required)

* One session only; no retry/iteration.
* **Camera reboot occurred** during/after the session (second warm-boot segment;
  exception monitor dump in the ring). It was recorded, not retried.
* The camera auto-recovered to stock MSC `054C:0CA8` on its own; the operator did
  not need to switch modes; no battery pull was needed.
* No flash writes, no `nflasha` changes; the only camera-side writes were the
  standard RAM deploy (`/tmp_bt` tmpfs mount + module/daemon push), the daemon's
  own `--sd-log/--sd-mount` files (A6400K.LOG / A6400LD.LOG / A6400RCPT.JSON),
  and nothing else.
* Post-run camera state: MSC `054C:0CA8`, `usb_extcmd`/`usbg_*` stock modules
  loaded, `usbg_video` not loaded, no daemon process, `/tmp_bt` empty (owned
  files removed; reboot cleared them), debugger revived and responsive,
  uptime fresh after the reboot.
* `collect` could not run before the reboot left the debug channel down; the
  recovery script performed the same read/dump/verify steps after revival.

## 8. Artifacts

`artifacts/analysis/e0457-runb24-ep0-observer/`:

* `usb-capture.etl` (235,855,872 B), `usb-capture.xml` (2.2 GB),
  `ctrl-urbs.jsonl`, `usbhub3.jsonl`,
  `runb24-etl-analysis.json`, `runb24-etl-timeline.txt`;
* `obs-vs-etl.json`, `runb24-verdict.txt`, `anchor_b24.py`, `analyze_runb24.py`;
* `preflight/`: `prepare.json`, `arm.json`, `host-enumeration.log`,
  `composite-detected.json`, `ffmpeg.json` + logs, `restore-enumeration.log`,
  `restore-detected.json`, `etw.log`, `klog-ring.bin`/`klog-ring.json`,
  `klog-boots.txt`, `dmesg-after-run.bin`, `usb-state-after-run.txt`,
  `service-terminal.txt`, `recovery.json`;
* `sdcard/`: `A6400K.LOG`, `A6400LD.LOG`, `A6400RCPT.JSON` + extraction manifest;
* harness: `runb24.py`, `revive_dump.py`, `pull_sdcard_files.py`, `etw.ps1`,
  `extract.py`, `parse.py`.

## 9. Next steps (need a fresh authorization, no action taken)

1. Observer change: print each recorded row immediately (and an `OBS work enter`
   line), keep a bounded row budget, and shorten the poll so the dump is
   durable; this is a code change and must be built/audited/Unicorn-verified
   like E0456.
2. Fix the `irq/229-dwc3` NULL dereference (vector 0x000, `current->mm == NULL`):
   capture the oops registers/fault address from the full ring dump (already
   preserved in `klog-ring.bin`), map `usbg_video+offset` for the IRQ-thread
   call chain, and gate the reference callback on a valid state before
   forwarding.
3. Then one new supervised session with the same corrected harness.
