# E0289 — e0288 mitigation keeps the device enumerated through liveview; clean teardown

Date: 2026-11-09. Physical bounded test with the e0288 liveview-consistency module.

## Result

- Probe: `no_frame` (connected, 120 retries, `closed_utc` written).
- **LCD liveview: DA**.
- Capture timeline:
  - 21:27:34.1 parent,
  - 21:27:45.5 **parent + PTP child + UVC child**,
  - **children stay until 21:28:43.3** (session teardown),
  - 21:28:50.7 all gone (Mass Storage return).
- **No liveview-start disappearance**: unlike P3b, the device did not drop off the bus when
  liveview started; the composite remained enumerated for the whole session.
- Session: **`p4_session_completed`**; receipt `init/stop_verified/retired/completed` all true;
  `p4_after` ok (`module_restored: true`, `usbg_video_after: false`, `reboot: false`);
  `rmmod` and all owned-file removals status 0; module list restored.
- Camera: MSC, healthy (uptime 645.73 s, 42 modules, no `usbg_video`).

## Interpretation

The **liveview-consistency mitigation works for USB enumeration**: the app's liveview-start
gadget re-create no longer removes the device; the composite (PTP + UVC children) survives, and
the teardown completes cleanly with a receipt. This is the first liveview session with a
connected probe and a verified stop/retire/unload.

Remaining gap: the PTP **liveview frame is still absent** (`no_frame`), i.e., the downstream
app/PTP object path (E0266–E0270/E0283) is now the only blocker for PTP liveview frames. The host
monitor reported `uvc_detected_on_host: false` only because the classification properties are
access-denied; the UVC child was present in the capture.

## Next

- Re-test the PTP frame path with the e0288 module (it now keeps the device enumerated):
  probe + GetObject; if `no_frame` persists, investigate the app-side `s_LiveViewStatus`/MTP
  object path (E0266–E0270) with the camera reachable for the whole session.
- Keep the receipt/teardown verification as the safety baseline (clean 6/9).
