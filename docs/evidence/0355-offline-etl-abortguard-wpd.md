# E0355 — Offline E0354 analysis: ETL limits, teardown abort guard, WPD MI_00 binding tooling

Date: 2026-11-11. **Offline only.** No camera access, no USB mode change, no module load.
Inputs are the E0354 artifacts (`artifacts/analysis/trackB-e0349/attempt-run-b2/`), the
E0352 teardown sources/fixtures, and the host PMCA/WPD code.

## Task 1 — USB ETW dissection (what the retained capture can prove)

`usb-capture.etl` (301,719,552 B) was captured with three providers:
`Microsoft-Windows-USB-USBPORT`, `Microsoft-Windows-USB-USBHUB3`,
`Microsoft-Windows-USB-USBXHCI`.

- **Providers actually present: USBXHCI (~97%) and USBHUB3 (~3%); no USBPORT events**
  (the device is attached to the xHCI controller, so the USB 2.0 URB provider is not in
  the path).
- **USBXHCI event IDs 41–45 are TRB-level**: sample payloads `id41=4|5|0|3200`,
  `id42/43/44=2`, `id45=4|5|0`. They carry slot/endpoint/ring counters only —
  **no `bmRequestType`, `bRequest`, `wValue`, `wIndex`, `wLength` and no USBD_STATUS**.
  Therefore the requested URB-by-URB EP0 timeline (`VS_PROBE_CONTROL` 0x0100,
  `VS_COMMIT_CONTROL` 0x0200, `SET_INTERFACE`, stall/timeout codes) **cannot be
  extracted from this capture**. No stall/short-packet attribution is possible from it.
- **What is recoverable** (details in
  `artifacts/analysis/e0355-offline-run-b-analysis/PART1-ETL.md`):
  - USBHUB3 id=6 at 18:17:53.620 carries the Sony **173-byte configuration descriptor**,
    and it matches the repo-verified composite byte-for-byte: PTP iface0 6/1/1 with
    EP 0x81/0x02/0x83, IAD 8/11/1/2/14/3, VC iface1 0E/1, **VS iface2 0E/2 alt 0 with one
    endpoint, EP 0x84 bulk 512**, MJPEG 1280×720. The host therefore had a correct
    descriptor.
  - **18:18:54.17** ffmpeg started (`ffmpeg.out.log` creation); **18:18:59.44** it failed
    (`Could not RenderStream to connect pins`, 5.3 s) — no USBHUB3 port-state event
    (no reset/removal/descriptor re-read) in the 18:18:20–18:19:40 window. The abort was
    inside usbvideo/DirectShow pin negotiation, not a bus-level fault.
  - The 12 WPD/PTP attempts (18:17:53.6–18:18:49.5) each failed in ~0.4 s
    (`No Sony camera found`).
  - **18:20:05.76** USBHUB3 reports VID 1356 (0x054C) PID 802 (0x0322) attach/enum
    events: the module's teardown reconnect re-enumerated the composite correctly.
  - The capture was stopped at **18:20:10.3**; the later Mass Storage switch and the
    "Device unknown" state are **after the ETL**, so the E0354 unknown-device cause is
    not in this artifact either.
- **Consequence / next capture requirements:** to get the exact EP0 class sequence no
  host USB filter driver is needed — instrument the camera side instead:
  log `bmRequestType/bRequest/wValue/wIndex/wLength` and the reference return code in the
  bridge `CLASS`/`VENDOR` thunk (`uvc_callback_bridge.c`), plus reference START and
  `uvc_ep0_comp`/class-handler returns, to dmesg. The next host capture must stay armed
  through the MSC switch and use a narrower window/provider set. USBPcap or an Android
  raw-usbfs host are the alternatives when host-side URBs are required.

## Task 2 — why the RenderStream attempt regressed the teardown; abort guard added

**Mutations a CLASS/START can leave behind (evidence-based):**
- The reference class handler accepts `SET_CUR` without selector/length checks and
  **queues an asynchronous EP0 request** with `uvc_ep0_comp` (E0351 decision table T4/T5);
  `GET_CUR` replies from a 26-byte template (T6b). The bridge's `in_flight` counter only
  covers the synchronous thunk return, not the queued EP0 completion.
- START installs the endpoint list (`core_cb_start`: ctx+0xB2/B4/B8) and leaves the
  0x84 endpoint enabled; the E0352 sequencer already releases the list, disables/stops
  through unconfigure/pullup/gcw_stop, and unbinds the four EP0 hooks.
- **Gap found:** on a native error after the UDC stop, the sequencer went to
  `demote` and **reconnected** even when an accepted CLASS request could still have a
  completion outstanding. Freeing/unbinding/reconnecting in that state is the suspected
  cause of the E0354 post-RenderStream "unknown device". No `usb_ep_dequeue`/EP0 cancel
  ABI for this reference driver is evidenced in the repository, so an actual dequeue
  could not be implemented honestly.

**Implemented (fail-closed containment, not a fake dequeue):**
- `uvc_callback_bridge.h/.c`: appended `class_requests`, `vendor_requests`,
  `class_last_result` counters (earlier struct offsets unchanged); the CLASS/VENDOR
  thunks increment them and record the reference result.
- `uvc_ptp_soft_disconnect.c`: after the post-UDC `check_error`, if it reports a failure
  **and** `bridge.class_requests > 0`, the sequencer logs
  `[a6400_td] abort guard: … holding before unbind/free/reconnect` and **holds**
  (no unbind, no descriptor free, no reconnect). The verified-stop attestation then
  keeps the module pinned, so `rmmod` remains blocked.
- Rebuilt module: `artifacts/native/uvc-transport-e0355-abortguard/…ko`, **76,036 B**,
  SHA-256 `39977ceff3259a6921971ff55f5659bcd558d5972633956ec62e2be782ee01ba`,
  transport audit `offline_module_audit_passed` (117 checks / 8 skips / 0 failures).
- **Unicorn proof:** the E0352 fixture was extended with case 14
  (`class-request-abort-guard-holds`: `class_requests=1`, post-UDC `check_error=-5`).
  `b4_soft_disconnect_verify.py` now reports **13/13 cases passed**, including the new
  case: events stop after `CHECK_ERROR` with `udc_down=1, reconnect=0, descriptor
  UNTOUCHED, releasable=0`.
- Missing-dequeue boundary remains: **`reference_ep0_request_cancel_unmodelled`** — the
  guard prevents unsafe release, but a real cancel/dequeue needs the reference driver's
  EP0 request ABI (not decoded).

## Task 3 — why WPD did not expose the composite MI_00, and the host-side fix

**Observed (E0354):** PnP showed `USB\VID_054C&PID_0322&MI_00` as **WPD / "MTP USB
Device" with Status OK**, while the PMCA WPD client's `PortableDeviceManager::GetDevices`
filtered by VID 0x054C returned **zero** devices, 12 times.

**Analysis:**
- PMCA filters with `MtpContext.listDevices(0x054C)` over all WPD DeviceIDs and
  `parseDeviceId` is case-insensitive and handles composite IDs
  (`…vid_054c&pid_0322&mi_00#…` → 0x054C/0x0322/MI 0), so the **filter itself is not
  the cause**.
- Therefore, in that state, **PortableDeviceManager did not expose the composite child**
  even though PnP classed it as WPD. Possible causes: WPD service does not enumerate a
  child under a composite parent with this function layout, the MTP function was not in
  a WPD-serviceable state, or enumeration timing/device-change notification. Cannot be
  decided offline without a session-level WPD dump.
- **Camera-side alternative:** a local OSAL/UIPC command that wakes the
  `0x0167046a` JPEG producer directly is **not evidenced**. E0260/E0273 show the app
  receives `GetObject 0xFFFFC002` and builds an 8-byte OSAL message internally; the local
  queue id/message format and a receiver for an out-of-process sender are unmapped
  (`libinfraremote_liveview_local_trigger_unmodelled`). P1 (E0349) showed frames appear
  when a host PTP consumer is active; Run A (E0353) had 1,800 empty `GET_JPEG` polls with
  no consumer. So a host PTP consumer (or the UVC open path) is required at present.

**Implemented host-side tooling (read-only):**
- `tools/research/wpd_device_dump.py`: enumerates every WPD DeviceID via PMCA, parses
  VID/PID/MI, optionally opens/closes each device; exits 2 when COM/WPD is unavailable.
  Samples: `USB\VID_054C&PID_0CAA…` → (0x054C,0x0CAA,None);
  `\\?\usb#vid_054c&pid_0322&mi_00#…` → (0x054C,0x0322,MI 0).
- `tools/research/ptp_liveview_client.py`: new `--wpd-device-id` filter (select composite
  MI_00 by DeviceID substring) and, on empty enumeration, prints the full WPD device list
  before failing with an explicit composite-MI_00 diagnosis.
- Offline verification: `--help` shows the new option; a run with no WPD device prints
  `WPD manager lists 0 device(s)` and the explicit message (exit 1/2 paths are distinct).

## Verification / artifacts

| Item | Value |
| --- | --- |
| ETL dissection | `artifacts/analysis/e0355-offline-run-b-analysis/PART1-ETL.md` |
| Extracted Sony config descriptor | `artifacts/analysis/trackB-e0349/attempt-run-b2/sony-config-descriptor-bytes.txt` |
| ETL | `…/usb-capture.etl`, 301,719,552 B (XML derived copy removed) |
| Abort-guard module | 76,036 B, `39977cef…`, audit `offline_module_audit_passed` (117/8/0) |
| Unicorn teardown proof | `artifacts/analysis/unicorn-teardown-e0352/b4-soft-disconnect-unicorn.json`, 13/13 passed |
| WPD tool | `tools/research/wpd_device_dump.py` (0 devices in MSC as expected; parser samples above) |
| PTP opener | `tools/research/ptp_liveview_client.py --wpd-device-id`, diagnostic dump on failure |
| Suite | `Ran 1312 tests … OK` (before the final doc sync; see the final run log) |

## Confidence and limitations

- High: no EP0 setup/URB data in this ETL; exact ffmpeg timing; host descriptor correct;
  no hub-level reset during RenderStream; teardown reconnect at 18:20:05; abort guard
  holds in Unicorn and the module still passes the transport audit.
- Medium: that a queued EP0 completion is the E0354 unknown-device cause — the guard is a
  containment, not a proof; the unknown-device interval itself was outside the capture.
- Not solved: actual EP0 request cancellation (no ABI evidence); WPD composite-child
  enumeration cause; camera-side local liveview trigger.
- No camera was touched for this record.

## Next experiments (no live run proposed until the camera-side class logging exists)

1. Instrument `uvc_callback_bridge.c` CLASS/VENDOR and reference START/class returns
   (`bmRequestType/bRequest/wValue/wIndex/wLength`, result, EP0 completion entry/exit) to
   dmesg; rebuild/audit (same builder path). This substitutes for the missing USBPcap data
   and makes the next bounded run diagnostic.
2. On the next run, keep ETW armed through the Mass Storage switch (and only for the
   ±30 s window) to capture the unknown-device transition; dump WPD IDs in-session with
   `wpd_device_dump.py --open-ids`.
3. If EP0 request cancellation is needed after the class trace: decode the reference
   driver's EP0 request/`uvc_ep0_comp` cancel path from `usbg_video.ko` (E0319 object
   context) and model it in the sequencer + Unicorn before another run.
4. Keep Track A (Android pipelined PTP + `0x9207` controls + SGSR shader) as the shipping
   path; Track B remains gated on the EP0 instrumentation above.
