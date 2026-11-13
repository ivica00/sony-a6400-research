# E0468 — Run B25: OBS timeline, ETW alignment, verdict **S1**

Date: 2026-11-13. ONE supervised camera session, authorized before it started.
Camera: ILCE-6400, kernel `3.0.27_nl-rt106`. No retry was made and **no reboot
occurred**.

## 1. Purpose and setup

Decide whether the camera handles the UVC `GET_CUR` status stage late (~5 s, S2)
or promptly (S1) by comparing the unbuffered `OBS` rows against the host's
~5.0 s Stop Endpoint in the Windows USB ETW trace.

* Module: `artifacts/native/uvc-transport-e0459-obs-unbuffered/usbg_video_a6400_shared_candidate.ko`,
  **82,804 B**, sha256 `3ddb6bd545cbdb1ac7122eee0a0375a3d2e44b643c9395dd43b0235b80cc352f`
  (E0465 fixes: restore guard + unbuffered observer), audit **117/8/0**.
* Daemon: `camera-daemon/build/a6400-lived` sha256 `99047575…`; camera was in
  stock MSC `054C:0CA8`, debugger protocol 2, PID 149 not traced, module not
  loaded, `/tmp_bt` mounted as the documented 1 MiB tmpfs.
* Harness: `artifacts/analysis/e0466-runb25-ep0-observer/runb25.py` — the
  corrected B24 harness (waits for authoured `054C:0322` with UVC `MI_01` +
  MTP `MI_00`), ETW providers USBPORT/USBHUB3/USBXHCI/UCX.
* ETW: `usb-capture.etl` **347,070,464 B**, sha256
  `edf4925d4457dc0b2e64b4ea95569100972d53d3cfc578ed7fd49e441908811f`;
  `tracerpt` XML 3,292,645,864 B, `ctrl-urbs.xml` 2,768 events,
  `usbhub3.xml` 5,123 events.

## 2. Run sequence and safety

* `/tmp_bt` tmpfs mounted (rc=0); module + daemon pushed; `insmod`; daemon armed
  (pid 2167); ETW started (0 buffers lost); operator switched to PC Remote;
  authored composite `054C:0322` detected.
* Exactly **one** ffmpeg attempt (8 s settle): 10.513 s, failed
  ("Could not RenderStream to connect pins", no frame).
* Daemon session: duration 45 s, receipt `status=clean exit=0 stage=complete
  stop_verified=1 teardown_verified=1 get_jpeg_polls=1348 frames=0
  sd_log verified receipt_written=1 unmount_rc=0 trace_lines=217`.
* Teardown: `[a6400_td] done phases=1ff failed=9 error=0 ep=1 … desc=1
  root=68a84500 retired=1 shadow=0 reconnect=1`; the E0399 legacy deferred
  restore ran and printed **`restore: no legacy Mass Storage table saved;
  shared session owns descriptors, legacy restore skipped`** — the E0465 guard
  fired, no EP0 re-arm over a NULL table, **no reboot**.
* Host saw `054C:0CA8` again (auto-restore) without an operator switch.
* Final camera state verified: MSC `054C:0CA8`, debugger responsive (protocol 2,
  pid 749), `usbg_video` **not** loaded, no daemon process, `/tmp_bt` cleaned
  (daemon receipt/jsonl copied off first, then removed), uptime continuous
  (2624.94 s → 2626.59 s during collect, 2791.87 s at final check; no reboot).
  No flash writes, no `nflasha` changes; only the daemon's own `--sd-log` files
  were written to SD.

## 3. ETW decode (host side)

UVC class requests on the `054C:0322` device (UCX, function 0x1B):

| UTC | transfer | duration | stop status |
|---|---|---|---|
| 08:27:20.975 | **GET_CUR** `A1 81 wValue=0x0100 wIndex=2 wLength=0x1A` | **5.000725 s** | `0x0` |
| 08:27:25.976 | **SET_CUR** `21 01 wValue=0x0100 wIndex=2 wLength=0x1A` | **5.015342 s** | `0xC0010000` (canceled) |
| 08:27:30.992 | GET_CUR retry | 0.0023 s | stalled/canceled |

The single ffmpeg attempt's 10.513 s failure matches the two consecutive ~5 s
EP0 transfers (5.0007 + 5.0153 s).

## 4. Camera OBS timeline (unbuffered, ktime + UTC anchor)

Clock anchor: the module's RR 35 record of the GET_CUR SETUP carries
`ktime_get_ts = 2549.825653`, and the ETL GET_CUR start is
`08:27:20.975942 UTC`; RR 39 (SET_CUR SETUP) is ktime `2554.8258725`
(+5.0002195 s). OBS rows (ktime, ms after GET_CUR SETUP, decoded state, UTC):

| # | ktime | Δ ms | ep0s | next | st | f0 | f1 | lpos | cnt | UTC |
|---|---|---|---|---|---|---|---|---|---|---|
| 0 | 2549.825978500 | **0.326** | 2 | 1 | 8d | 1 | 11 | 298 | 0 | 08:27:20.976 |
| 1 | 2549.842040500 | **16.388** | **3** | 1 | 9d | 11 | 1 | 2a0 | 0 | 08:27:20.992 |
| 2 | 2554.842050500 | **5016.398** | 2 | 3 | 89 | 1 | 1 | 2b0 | 0 | 08:27:25.992 |
| 3 | 2579.502060000 | 29676.407 | 1 | 1 | 89 | 11 | 1 | 2b4 | 0 | 08:27:50.652 |
| 4 | 2579.602046500 | 29776.394 | 1 | 1 | 89 | 11 | 1 | 2c4 | 0 | 08:27:50.752 |
| 5 | 2579.702053000 | 29876.400 | 1 | 1 | 81 | 11 | 1 | 2c8 | 0 | 08:27:50.852 |
| 6 | 2579.762050000 | 29936.397 | 1 | 1 | 81 | 11 | 1 | 2d0 | 0 | 08:27:50.912 |
| 7 | 2579.802043000 | 29976.390 | 1 | 1 | 80 | 11 | 1 | 2ec | 0 | 08:27:50.952 |

`OBS start`/`OBS work enter` at printk 1270.996673/1270.996875, then
**`OBS done n=8 iterations=1500`** at printk 1300.993041. The same lines were
also captured on the SD `A6400K.LOG` (31,873 B), so the timeline is durable.

## 5. Verdict: **S1**

* **Status armed promptly**: `ep0state 2→3` (NRDY(status) handled, status TRB
  armed) at **+16.388 ms** after the GET_CUR SETUP. S2 (IRQ thread ~5 s late)
  would require this transition at ≈ +5 s; it is **refuted**.
* **No state change for 5.000 s**: between rows 1 and 2 the ep0state stayed 3
  for **5000.010 ms** — the whole host GET_CUR Stop Endpoint interval.
* **Change only at the host abort / next SETUP**: row 2 occurs at
  +5016.398 ms, i.e. **+15.672 ms after the host GET_CUR Stop Endpoint
  completed** (start + 5.000725 s) and +16.177 ms after the SET_CUR SETUP
  arrived (RR 39 at +5000.22 ms). The camera moved only when the host ended the
  transfer and sent the next request.
* Host side: the GET_CUR Stop Endpoint completed with status `0x0` after
  5.0007 s, and the SET_CUR that followed was canceled after 5.0153 s.

Therefore the camera armed the status stage promptly and the host's status OUT
never completed the transfer until the abort/new SETUP. This is the **S1**
outcome defined in E0446 ("status TRB armed promptly but the host's status OUT
never completed it until the abort/new SETUP"). Per E0446, S1 shifts the next
investigation to the **host/bus-level status handshake**, not to camera IRQ
scheduling/priority.

Rows 3-7 are the teardown/reconnect and post-restore MSC re-enumeration
(`ep0s=1`, `st` 89→81→80, `lpos` advancing 2b4→2ec), which is expected and
shows the host re-enumerated while the observer's poll loop was still running.

## 6. Fix confirmation (E0465, live)

* The legacy deferred restore was **skipped** (`-6` guard) and the shared
  teardown kept `desc=1 root=68a84500 reconnect=1`.
* The observer printed `OBS work enter` and every row as it was recorded; the
  full timeline also reached SD. This directly fixes the B24 loss mode.
* The B24 reboot mechanism did **not** occur: no oops in the ring, uptime
  continuous, camera auto-restored to MSC.
* No regression: the daemon teardown completed with `stop_verified=1
  teardown_verified=1` and clean exit 0.

## 7. Artifacts

`artifacts/analysis/e0466-runb25-ep0-observer/`:

* `usb-capture.etl` (347,070,464 B), `usb-capture.xml` (3.29 GB),
  `ctrl-urbs.jsonl`, `usbhub3.jsonl`;
* `runb25-obs-vs-etl.json`, `runb25-obs-vs-etl.txt`, `analyze_b25.py`;
* `preflight/`: `prepare.json`, `arm.json`, `host-enumeration.log`,
  `composite-detected.json`, `ffmpeg.json`+logs, `restore-enumeration.log`,
  `etw.log`, `ring-after-run.bin` (107,267 B), `dmesg-after-run.bin`,
  `tmp_bt-a6400_lived_receipt.json`, `tmp_bt-a6400_lived.jsonl`,
  `collect.json`, `usb-state-after-run.txt`;
* `sdcard/A6400K.LOG` (31,873 B), `A6400LD.LOG` (12,223 B),
  `A6400RCPT.JSON` (2,391 B) + extraction manifest;
* harness: `runb25.py`, `revive_dump.py`, `pull_sdcard_files.py`, `etw.ps1`,
  `extract.py`, `parse.py`.

## 8. Next (no action without authorization)

Host/bus-level status-handshake investigation for the UVC probe `GET_CUR`: use
the ETL's xHCI transfer/event records for the control URB status stage
(why the status OUT is not issued/completed before the Stop Endpoint), plus the
UVC driver's probe sequence. No camera change is indicated by the S1 verdict.
