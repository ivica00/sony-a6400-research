# E0285 — P1: WPD enumeration alone does not trigger liveview

Date: 2026-11-09. Physical bounded test (e0251 session, WPD list-only probe, 0.2 s capture).

## Result

- **WPD list-only probe**: 271 samples, counts 0/1; first device seen at **21:08:56.67**
  (`VID_054C&PID_0CAA`, WPD handle). The probe only listed devices (no open, no PTP).
- **Capture**: parent 21:08:58.7 (brief 0 at 21:08:59.5), **parent+PTP child+UVC child at
  21:09:07.1**, stable until **21:10:02.7** (children gone = teardown), all gone 21:10:06.6.
- **LCD liveview: NE** (operator confirmed).
- Session: `p4_session_completed`, receipt `init/stop_verified/retired/completed` — **clean
  teardown 6/7**; `host_enum_gate` false at the last sample (teardown had removed the children).
- Camera: MSC, healthy (uptime 2217.36 s, 42 modules, no `usbg_video`).

## Interpretation

Host WPD enumeration **does** occur and the composite enumerates correctly (parent + PTP + UVC),
but the camera LCD **does not enter liveview**, and there is **no liveview-start disconnect**.
So enumeration alone is not the liveview trigger. The trigger is more likely the PTP/WPD
**open or handshake** (P2/P3), or a camera-side state.

The earlier F8-5 observation (liveview without a connected probe) remains the anomaly; it may
have involved a different camera UI state or a partial open during enumeration.

## Next

- **P2**: `wpd_presence_probe --open` (open/close the WPD device, no PTP commands) + capture +
  session + LCD observation. If liveview/disconnect appears, the open is the trigger; otherwise
  **P3** (full handshake/GetObject probe).
