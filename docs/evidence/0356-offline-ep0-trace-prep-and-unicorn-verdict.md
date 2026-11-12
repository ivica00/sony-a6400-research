# E0356 — Offline prep for the 5-second EP0 hypothesis: camera-side UVC trace, crash-safe kernel log, Unicorn verdict, UCX capture

Date: 2026-11-11. **Offline only.** No camera access, no module load, no USB mode change.
Prepared for one future bounded run; nothing below is a hardware result.

## Claim

1. **Camera-side instrumentation added** to the UVC bridge so the next session logs the
   exact UVC transaction sequence to dmesg, which is the camera-side substitute for the
   missing host URB/setup trace (E0355):
   - `CLASS`/`VENDOR` **entry**: the full 8-byte `usb_ctrlrequest`
     (`bmRequestType`, `bRequest`, `wValue`, `wIndex`, `wLength`);
   - `CLASS`/`VENDOR` **exit**: the synchronous reference return value
     (`uint` as `%d`);
   - reference **START/STOP** entry (interface, count) and return.
   Module: `artifacts/native/uvc-transport-e0356-instr/…ko`, **77,136 B**,
   SHA-256 `8ea863ac0e4794437f7312f7ecce03b47f5125574b7ee9cab74c6bc4e0fd4a90`,
   transport audit `offline_module_audit_passed` (117 checks / 8 skips / 0 failures);
   the E0352 Unicorn teardown suite was re-run against **this** module: **13/13 passed**
   (including the E0355 CLASS-abort-guard case).
2. **Crash-safe kernel trace to SD** added to the daemon (`--dmesg-sd`, requires
   `--sd-log --sd-mount`): `klogctl(SYSLOG_ACTION_READ_ALL)` (ring read, non-consuming,
   bounded 192 KiB) → lines containing `[a6400_` → append to
   `<mountpoint>/A6400K.LOG` with `O_APPEND|O_SYNC` + `fsync`, de-duplicated by the last
   mirrored line. Flush points: every ~150 stream ticks (~5 s at 30 fps), at each
   `--stats-interval` report, and once **before unmount**. Counters `trace_lines` /
   `trace_errors` are added to `sd_log` in the receipt. Daemon:
   `camera-daemon/build/a6400-lived`, **629,872 B**, SHA-256
   `58ef8e3512a94051b946f9b5864d0498174bfbd53b5bca762188a1dd238afdcb`; host tests
   399/399.
3. **Unicorn verdict on `core_cb_class` EP0 submission** (existing `reference-class`
   harness, 10/10 cases; JSON `artifacts/analysis/unicorn-uvc-e0351/unicorn-uvc-e0351.json`):
   - `SET_CUR` **VS_PROBE_CONTROL** (`bmRequestType 0x21`, `bRequest 0x01`,
     `wValue 0x0100`, `wIndex 0x0002`, `wLength 34`): **result 0**, `stubs=[]`,
     `usb_event_add_queue=[]`, `ep0_reply_hex=null`.
   - `SET_CUR` **VS_COMMIT_CONTROL** (`wValue 0x0200`, len 34): **result 0**, stub
     `osal_record_pro.clone.0`, one `usb_event_add_queue` call with args `0,0,0,7`
     (the user-notify slot 7), `ep0_reply_hex=null`.
   - `GET_CUR` **probe** 34 B: **result 0**; stubs `memcpy 26→temp`, `memcpy 34→0x5e20101c`
     (`this_ex+0x1C`, the EP0 buffer); `ep0_reply_hex` is produced synchronously:
     `0000010115160500…e100e0930400` followed by **8× `A5`** (the 26-byte template copied
     into a 34-byte request).
   - **Conclusion: no worker starvation or deferred queue exists inside
     `core_cb_class`.** It returns synchronously (0) for probe/commit, and the EP0
     data/status submission/completion is delegated to gadgetcore after the callback
     returns. Therefore the 5.3 s usbvideo timeout is **not** caused by an unhooked or
     starved callback; it must be in the gadgetcore EP0 completion/ownership path (or in
     the composite shadow/interface routing that the bridge uses). **No offline "fix" is
     justified by Unicorn alone** — the new bridge trace is what will distinguish:
     which class requests actually arrive (probe/commit/SET_INTERFACE, and with which
     `wIndex`), what `core_cb_class` returns, and whether reference START/STOP run.
     Two concrete follow-up hypotheses remain: (a) the wire VS interface is 2 while the
     reference callback's primary interface is 1 (`uvc_ptp_translate_setup` exists but is
     not used on the bridge CLASS path), and (b) the 26→34-byte probe reply tail.
4. **Host capture updated** (`tools/research/renderstream_capture.ps1`):
   `Microsoft-Windows-USB-UCX` added to both provider lists (present on this host:
   GUID `36DA592D-E43A-4E28-AF6F-4BC57C5A11E8`), and a new
   `-PostCaptureWaitSec` parameter keeps the ETW session armed **after** the caller
   command (for the MSC switch / unknown-device transition) before stop. Dry-run
   verified (ETW selected, UCX listed, no capture started).

## Why this addresses the 5-second hypothesis

The hypothesis was: an accepted UVC CLASS request leaves an asynchronous EP0
data/status phase pending forever, timing out usbvideo (~5,000 ms), blocking WPD on the
shared EP0, and leaving an outstanding EP0 request at teardown. The Unicorn evidence
rules out the "callback never submits/never returns" variant: `core_cb_class` returns 0
synchronously for probe/commit and only prepares the GET_CUR reply buffer. What remains
is the gadgetcore-side completion, which can only be observed on hardware. The new
bridge log records exactly the requests/returns and the START/STOP pair; combined with
`--dmesg-sd` (`A6400K.LOG` + `A6400RCPT.JSON` on the card) it survives a hang/power
cycle; combined with `-PostCaptureWaitSec` and the UCX provider it gives the host EP0
status from both sides.

## Verification

| Item | Value |
| --- | --- |
| Instrumented module | 77,136 B, `8ea863ac…`, audit `offline_module_audit_passed` (117/8/0) |
| Unicorn teardown suite (E0352 harness, 13 cases incl. CLASS abort guard) | 13/13 passed on the instrumented module |
| Unicorn `core_cb_class` results | 10/10 passed; probe/commit/GET_CUR records as above |
| Daemon | 629,872 B, `58ef8e35…`; host tests 399/399 |
| Capture script | UCX + `PostCaptureWaitSec`; dry-run exit 0; UCX GUID recorded |
| Suite | see final run log (1312 tests at E0355; no new Python tests here) |

## Single future bounded run (only after explicit go-ahead; not executed)

1. Fresh boot (< ~120 s) → push/verify module `8ea863ac…` + daemon `58ef8e35…`, `insmod`,
   `mknod`, daemon `--arm-transport --wait-pcremote --timeout 900 --duration ~150
   --stats-interval 5 --sd-log --sd-mount --dmesg-sd`.
2. Start ETW with UCX + `-PostCaptureWaitSec 90`; operator switches to PC Remote; wait for
   composite; host PTP attempt (WPD diagnostics if still empty); one ffmpeg RenderStream
   attempt; then switch to MSC while ETW is still armed; stop ETW after the switch.
3. Read `A6400K.LOG` / `A6400RCPT.JSON` from the card (survives a power cycle), dmesg
   `[a6400_uvc]`/`[a6400_sel]`/`[a6400_td]`, and the UCX ETL for the EP0 status.
4. Decide from the trace: if probe/commit class requests arrive with results 0 and no
   corresponding EP0 status completes, the gadgetcore EP0 ownership/routing is the fix
   target (then translate wire interface 2→reference 1 on the CLASS path and/or correct
   the probe reply length, validated offline first). If class requests never arrive,
   the host/pin path (usbvideo) is the target.

## Safety statement

Offline only: no camera, no module load, no USB mode change, no flash/SD write. The new
SD kernel-trace path is gated by the existing `--sd-log --sd-mount` window
(PC Remote-confirmed, `/dev/mmca1` only, never internal flash).
