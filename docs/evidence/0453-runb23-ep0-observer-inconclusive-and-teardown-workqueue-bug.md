# E0453 — Run B23: supervised PC Remote run of the E0446 EP0 observer — Inconclusive (no GET_CUR reached the observer; camera rebooted in teardown by a module workqueue BUG)

Date: 2026-11-13. Physical Run B23, one camera session. Module
`artifacts/native/uvc-transport-e0446-obs/usbg_video_a6400_shared_candidate.ko`
SHA-256 `7c87ab37f0da038f7ce0f3d112948deacb571584abfa275836b6b070c398002f`
(82,468 B; audit `offline_module_audit_passed`, 117/8/0) verified on the host
before deploy; daemon `camera-daemon/build/a6400-lived` 630,536 B
SHA-256 `990475753ecf20e02a9b5c7b095a74606bf72c710271148d939f7edd910b2f16`.

Artifacts: `artifacts/analysis/e0449-runb23-ep0-obs/` (`run-manifest.json`,
`usb-capture.etl`, decoded buckets, `sdcard/`, `preflight/`, scripts).

## 1. Verdict

**Inconclusive** for S1/S2. The comparison the E0446 note asked for was not
obtained, for three independently verified reasons:

1. **The single ffmpeg UVC capture attempt was never executed.** The host-side
   watcher was written to wait for the *stock* PC-Remote PID `054C:0CAA`; the
   observer module enumerates the authored composite as **`054C:0322`**
   (UVC `MI_01` "ILCE-6400" + MTP `MI_00`). The composite was present for
   45 s, but the trigger never fired, so no `GET_CUR`/`SET_CUR`/`SET_INTERFACE`
   was issued (confirmed from the ETL: **0 UVC class requests to any Sony
   device**).
2. **No `OBS` lines exist** because the observer starts on the first CLASS
   request (`a6400_uvc_obs_start`) and none arrived. `A6400K.LOG` contains the
   module's START/alloc lines but no `CLASS` and no `OBS` line; the warm ring
   confirms this.
3. **The camera rebooted during the daemon teardown**, and the warm kernel ring
   shows the cause: a kernel `BUG` in `__queue_work` raised from
   `schedule_work` from the module's DISCONNECT branch. The same
   `schedule_work`-on-a-static-zeroed-work-struct pattern is used by the E0446
   observer work item itself, so the observer could not have been validated
   even if `GET_CUR` had arrived (§4).

Per the non-negotiable "exactly one session, no retry" rule, no second session
was attempted. No code was changed.

## 2. Safety record and deviations (read first)

* **Camera rebooted** at `2026-11-12T23:51:24Z` (00:51:24 local), confirmed by
  the user (Sony/α start-up screen), by the host (authored composite
  disappeared at +94.139 s and stock MSC `054C:0CA8` re-enumerated at
  +101.942 s) and by the warm klog ring (§4). The reboot was the reset; **no
  battery pull was needed or performed for this run** (the earlier pre-run
  battery pull was user recovery for the dead debug channel, before deploy).
* **Debugger re-injection via Senser service mode** was required before deploy
  (user-directed): after a cold boot the installed daemon answers only after
  the `usbter` ldisc is started (E0412 `service_shell_required`). One service
  session aborted at terminal setup (no camera writes); the second completed
  and the channel answered (`protocol=2`, full op list). No `/setting` or
  `/etc/ld.so.preload` write was made by this run; the post-reboot channel was
  revived by a terminal enable/disable cycle only.
* **ETW** (`logman`) needed a full-access token because the DSH shell ran at
  Low integrity. Capture window `23:49:49.6Z–23:52:30.9Z`, **474,587,136 B**,
  2,308,523 events, **0 lost**.
* Read-only only on the camera: module/daemon in RAM (`/tmp_bt`); SD files were
  pulled with SCSI `READ(10)` through the MSC LUN (no writes, no mount, no
  battery/`nflasha` access). No bulk `/dev/mem`; the warm ring was read with
  the existing bounded `dump-ring` op after the reboot.

## 3. Exact run record (UTC; local = UTC+1)

| t rel. | UTC | local | event |
|---|---|---|---|
| 0.000 | 23:49:49.6 | 00:49:49 | ETW armed; camera in MSC `054C:0CA8`; observer module loaded (`insmod`), daemon armed (pid 2023) waiting for PC Remote |
| +19.880 | 23:50:09.5 | 00:50:09 | `054C:0CA8` removed (operator switches to PC Remote) |
| +44.001 | 23:50:33.6 | 00:50:33 | stock `054C:0CAA` enumerated briefly |
| +48.533 | 23:50:38.1 | 00:50:38 | `0CAA` removed |
| +48.890 | 23:50:38.5 | 00:50:38 | **authored composite `054C:0322`** enumerated (UVC `MI_01` "ILCE-6400" + MTP `MI_00`) |
| — | ~23:50:36 | ~00:50:36 | daemon `pcremote_detected`, 2 s settle, SD mount, freeze/INIT, discovery, stream start (camera log `t=701.331 s` freeze; `t=701.991 s` `set_path_start`) |
| — | 23:50:39–23:51:24 | — | 45 s session; `get_jpeg_polls=1200`, no frames (no host stream request); **no ffmpeg attempt** |
| +94.139 | 23:51:24.1 | 00:51:24 | composite disappears: teardown `stream_stopped duration_elapsed` → `set_path_stop`, `dmm_rule_0`, `uvc_unreg` OK → `uvc_stop` → kernel BUG → reboot |
| +101.942 | 23:51:32.4 | 00:51:32 | camera back as stock MSC `054C:0CA8` |
| +161.3 | 23:52:30.9 | 00:52:30 | ETW stopped |

Camera-side daemon timeline (`A6400LD.LOG`, monotonic ms): `sd_log_mounted`;
freeze `t=701331` (180 tids, 1176 ms); hook publish; `uvc_init`/`reg_buf`/
`enable` OK; `dmm_rule_5`, `set_path_start` OK; `stream_begin`; stats every
5 s to `polls=1200`; `stream_stopped reason=duration_elapsed`;
`teardown_begin`; `set_path_stop status=0` `t=747037`; `dmm_rule_0 status=0`;
`uvc_unreg rc=0`; **`destructive_step uvc_stop` `t=747059` with no completion**.

Receipt (`A6400RCPT.JSON`, 2,390 B): `status=clean`, `exit_code=0`,
`duration_s=45`, `init_attempted=1`, `session_active=1`,
`get_jpeg_polls=1200`, `sd_log.mounted=1 verified=1 sentinel_ok=1
receipt_written=1`, but `stop_verified=0`, `stop_attempts=0`,
`teardown_verified=0`, `sd_log.unmount_rc=1` — the stop sequence was cut by the
reboot after it had already written the receipt.

## 4. Reboot root cause (warm klog ring, boot 0 of 2)

`dump-ring` returned a valid 131,072-byte ring with two boots (54,533 data
bytes, CRC32 `0x50dbbb59`, boot 0 = session boot 48,884 B; boot 1 = post-reboot
boot that kept the previous buffer, `klog: keep logging buffer ... nbit: 0`).
The tail of boot 0 is the Sony exception monitor:

```
[Exception Syndrome]
Illeagle Instruction at 0x60111104
[current task]
program: /tmp_bt/a6400-lived(a6400-lived) (pid: 2023, cpu:0, tid: -1, stackpage: 0x698d2060)
[call stack]
    function entry : 0x601110e0 [ factor : 0x60111104 ] --  @ NULL : 0x60111104
 <- function entry : 0x6014a060 [ caller : 0x6014a3c8 ]
 <- function entry : 0x6014a38c [ caller : 0x6014a4a8 ]
 <- function entry : 0x6014a474 [ caller : 0x6014a4d4 ]
 <- function entry : 0x6014a4b8 [ caller : 0x5f5863f4 ]
Entering exception monitor.
```

Resolved against the live kallsyms (`artifacts/analysis/e0401-kallsyms-now.txt`)
and the module load base `usbg_video @ 0x5f581000`:

| address | symbol |
|---|---|
| `0x601110e0` (+0x24 = `0x60111104`, illegal instruction) | `__bug` |
| `0x6014a060` | `__queue_work` |
| `0x6014a38c` | `queue_work_on` |
| `0x6014a474` | `queue_work` |
| `0x6014a4b8` | `schedule_work` |
| `0x5f5863f4` | `usbg_video + 0x53f4` |

`usbg_video + 0x53f4` lies inside the module function `invoke` (build symbol
`st_value=0x4ad8`, size 2,448, offset `+0x91c`). The only `schedule_work` call
in `invoke` is the DISCONNECT branch that schedules the deferred descriptor
restore (`a6400_uvc_restore_work`/E0399 pattern). The work struct is a static,
zero-initialised array (no `INIT_WORK`, i.e. `work->entry` is not a valid list
head), so the queue operation trips the kernel's workqueue `BUG_ON`; `__bug`
executes an illegal instruction and the Sony exception monitor reboots the
camera. This is consistent with the E0399/B22 "deferred restore" reboot
confound and explains it.

**Consequence for the observer:** `a6400_uvc_obs_start` uses the identical
pattern — `static uvc_u32 g_obs_work[8]` zeroed, function pointer written at
+12, then `schedule_work()` without `INIT_WORK`. The E0446 Unicorn check
(`e0446-observer-unicorn.py`) modelled the work call but not this kernel list
invariant, so its PASS did not cover it. The observer would therefore have
raised the same BUG when its work item was queued.

Boundary: this does not prove whether `uvc_stop` itself, the disconnect
callback order, or the long-pending PTP transfer (below) is the precise
trigger; it does prove the module's workqueue usage is unsafe as built.

## 5. ETL decode (Windows USB ETW)

`tracerpt -of XML` produced 4,468,880,838 B; extraction
(`extract.py`/`parse.py`/`analyze.py` from `e0399-b21-etl`) kept
`ctrl-urbs` 3,748 events, `usbhub3` 5,268, `usbxhci-mgmt` 321. Sony identity
events (USBHUB3) and control transfers:

* `054C:0CA8` (MSC) present at capture start, removed at +19.880 s.
* `054C:0CAA` (stock PC-Remote PTP) +44.001 s, removed +48.533 s.
* **`054C:0322` (authored composite) enumerated +48.890 s**, removed at
  +94.139 s — exactly the daemon teardown.
* `054C:0CA8` re-appears +101.942 s (reboot completed).
* Sony control transfers: GET_DESCRIPTORs for both enumerations
  (`0x0100`/`0x0300`/`0x0200`/`0x0302`, ~3 µs each) and one PTP class transfer
  on the composite MTP interface: `bmRequestType 0xA1 bRequest 0x67 wLength 0x24`,
  duration **14.590 s**, overlapping the teardown (submitted +79.098 s,
  completed +93.688 s).
* **UVC class requests to Sony devices: 0.** No `GET_CUR`, no `SET_CUR`
  PROBE/COMMIT, no `SET_INTERFACE` — the observer data path was never entered.
  (The thousands of `URB_FUNCTION_CLASS_INTERFACE` events in the bus trace
  belong to other devices — e.g. `1C75:AF80` — and were excluded by the
  per-device join on Sony `idVendor`.)

Therefore there is no camera-side EP0 status timeline to compare against the
host's 5.01 s Stop Endpoint; S1 and S2 are both unsupported.

## 6. What was verified vs not

Verified:
* Module SHA-256 and audit before deploy; module loaded (`usbg_video` in
  `/proc/modules`), daemon armed and detected PC Remote, SD log mounted and
  receipt written, UVC reference START fired in the camera log.
* Host enumeration of the authored composite and its exact disappearance at
  teardown; the warm-ring BUG chain and its symbol resolution; camera reboot
  and self-recovery to MSC.
* Camera responsive after the run; debugger channel restored read-only
  (`dmesg`, `dump-ring`, `usb-state`).

Not verified / not claimed:
* S1 vs S2 (no OBS data).
* Whether the observer work item executes at all on hardware (its
  `schedule_work` usage is unsafe — see §4).
* The precise reboot trigger ordering between `uvc_stop`, the disconnect
  callback and the 14.59 s pending PTP transfer.

## 7. Next (offline first; no camera run authorised by this note)

1. Fix the module workqueue usage: initialise both work items with
   `INIT_WORK` (or explicitly set `entry.next/entry.prev` to the list head
   before the first schedule) for the deferred restore and the observer; do not
   schedule an already-queued work item. Re-run the Unicorn observer harness
   with an explicit list-head invariant check.
2. Fix the host-side trigger for the authored composite: wait for the UVC/MTP
   child devices of `054C:0322` (not stock `0CAA`), and run the single ffmpeg
   attempt once the composite is enumerated.
3. Only then repeat one supervised session to obtain `OBS` timestamps and
   compare them with the ETL Stop Endpoint timing (E0446 goal).

## 8. Artifact index (all under `artifacts/analysis/e0449-runb23-ep0-obs/`)

| artifact | bytes | SHA-256 (short) |
|---|---|---|
| `usb-capture.etl` | 474,587,136 | `22616923cf099f41…` |
| `usb-capture-summary.txt` | 26,006 | `c897493834666937…` |
| `usb-capture.xml` (tracerpt) | 4,468,880,838 | `0b72d0bed332c9b3…` |
| `ctrl-urbs.jsonl` / `.xml` | 3,967,262 / 10,457,010 | `bbf9befd436d7cb1…` / `0878f4fa916eda99…` |
| `usbhub3.jsonl` / `.xml` | 1,904,504 / 6,934,831 | `a6000b0843a94119…` / `e41b193464d81bca…` |
| `runb23-etl-analysis.json` / `runb23-etl-timeline.txt` | 29,891 / 3,770 | `e15e0ce2d51fd12a…` / `23e91bf420b74904…` |
| `sdcard/A6400K.LOG` | 8,104 | `d14e13e556db79ef…` |
| `sdcard/A6400RCPT.JSON` | 2,390 | `52c7d32013c39f4a…` |
| `sdcard/A6400LD.LOG` | 3,807 | `5ceaf801a460d776…` |
| `preflight/klog-ring.bin` / `.json` | 54,545 / 1,434 | `ec08dd8eb3a94236…` / `bb5b4981aab8f88d…` |
| `preflight/klog-boot0-session.txt` (session boot, exception monitor) | 48,884 | `5cb2e9c78cdda247…` |
| `preflight/dmesg-after-reboot.txt` | 6,024 | `3c3fc231858146b3…` |
| `run-manifest.json` | — | full hashes |

Scripts kept in the same directory: `run_camera_prepare.py`, `arm_daemon.py`,
`analyze_run.py`, `extract.py`, `parse.py`, `analyze.py`,
`pull_card_probe.py`, `pull_sdcard_files.py`, `recover_ring.py`,
`resolve_module_symbol.py`, `service_inject_debugger.py`,
`etw_capture_elevated.ps1`. Pre-existing scripts were copied from
`artifacts/analysis/e0399-b21-etl/` with the input path changed only.
