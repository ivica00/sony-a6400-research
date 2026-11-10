# E0286 — P2: WPD open/close alone does not trigger liveview

Date: 2026-11-09. Physical bounded test (e0251 session, WPD open-only probe, 0.2 s capture).

## Result

- **Open-only probe**: 263 samples, `max_count=1`, `opened+closed` first at **21:12:32.48**
  (elapsed 36.6 s); the WPD device was opened and closed repeatedly, **no PTP commands**.
- **Capture**: parent 21:12:34.9; **parent+PTP child+UVC child 21:12:42.5**; stable until
  **21:13:39.0** (teardown); all gone 21:13:42.9.
- **LCD liveview: NE** (operator).
- Session: `p4_session_completed`, receipt `init/stop_verified/retired/completed` — **clean
  teardown 7/8**; `host_enum_gate` false at the last sample (teardown removed the children).
- Camera: MSC, healthy (uptime 2427.83 s, 42 modules, no `usbg_video`).

## Interpretation

WPD open/close (even repeated) does not start the camera liveview and does not disconnect the
composite. Together with P1 (list-only), the remaining trigger candidate is the **PTP/SDIO
handshake** (or the GetObject traffic) that the earlier probe performed when the LCD liveview
appeared (F7/F5b-2). The F8-5 anomaly (liveview without a successful connection) is still
unexplained, but P1/P2 rule out enumeration/open as the trigger.

## Next

- **P3**: full probe (handshake + GetObject) + 0.2 s capture + session + LCD observation. That
  reproduces the liveview start and shows the exact disconnect timing for the mitigation.
