# E0296 — Snapshot2: enumeration stable, reconnect budget short, teardown stuck again

Date: 2026-11-09. Physical snapshot2 run (e0288) + offline tool.

## Result

- Capture: parent 21:58:11.2, **parent+PTP+UVC 21:58:21.6**, children gone 21:59:16.6,
  all gone 21:59:17.4 (Mass Storage). **No liveview-start disappearance** — the e0288
  mitigation kept the composite enumerated through the session again.
- Probe: **connected** at 21:58:10.88, then the WPD COM object shut down at the composite
  re-enumeration; the reconnect attempts ran out within the `--retries 120` budget (~6 s) and
  returned `reconnect_error: No Sony camera found`; `no_frame`.
- Session: **teardown unconfirmed** (`status: started`, no receipt, `DebuggerError -2`).
  **Operator clarification: after entering liveview the camera was not responsive**; the operator
  restarted it (Mass Storage, uptime 34.07 s, 42 modules, no `usbg_video`). The teardown failure
  is therefore the camera-side hang after liveview, not merely a USB stuck state.

## Interpretation

- The e0288 enumeration mitigation is **stable** in this run (device stays enumerated), matching
  E0289.
- The **camera becomes unresponsive after liveview** (operator had to restart it); the WPD COM
  object shutdown and the failed reconnect are consequences of that hang. The e0288 wrappers
  re-arm EP0/pullup inside the app's start path, which is a candidate for the camera-side hang
  (E0289 was clean once, so it is intermittent).
- The **probe reconnect budget** is too short for the re-enumeration window (~8–10 s); use
  `--retries 400` (~20 s).
- The **teardown stuck race is independent and intermittent** (E0289 clean, snapshot2 stuck,
  E0274 correlation); it remains a separate risk.

## Tool added

`tools/research/wpd_state_capture.py`: read-only parallel capture of the raw WPD device list and
the PnP PTP/UVC children (1 s interval), so the child-present window is recorded independently of
the probe. Smoke-tested (empty in Mass Storage). Full suite **669 tests**.

## Next

- **Minimal variant** of the consistency mitigation: drop the overlay on the app's stop (unhook
  + demote) but do **not** re-arm EP0/pullup in the start wrapper — the app's own start should
  handle the UDC. This tests whether the re-arm causes the camera-side hang after liveview.
- Then snapshot3: minimal variant + probe `--retries 400` + parallel `wpd_state_capture` + 0.2 s
  USB capture + LCD observation.
