# E0343 — CinemaHUD PTP liveview demo verified (real image + confirmed PTP control)

Date: 2026-11-11. Physical, user-authorized PC Remote session (no camera writes;
PC Remote mode switch only). Server: local CinemaHUD on `http://127.0.0.1:8080/`.

## Result

- **Camera connected in PC Remote** via Windows WPD (`VID_054C PID_0CAA`,
  `ILCE-6400`); Sony SDIO PTP handshake completed.
- **CinemaHUD server streamed real liveview**: frames 1024×680, ~135–141 KB,
  ~25–30 FPS sustained (server log: 112+ frames, 24.6–25.1 FPS in the sampled
  tail; `/api/status` reported `fps` 27.9–28.9 with `frame_age_ms` 0.195).
- **Status/controls** (`p8-status2.json`):
  - `camera = Sony ILCE-6400`, `controls_available = true`, 4 controls;
  - `shutter = 1/50` (code 53773, writable, full option list),
  - `aperture = f/2.8` (code 20487, writable, option list),
  - `iso = 1000` (code 53790, writable, option list incl. Auto),
  - `ev = +0.0` (code 20496, `writable=false`),
  - `battery` null (PTP property 0x5001 not exposed).
- **PTP command path confirmed**: `POST /api/control` with
  `{"param":"iso","value":1000}` (same value, no visible change) returned
  `{"status":"confirmed","applied":true,...}` and the subsequent `/api/status`
  still reported ISO 1000 — i.e. the camera accepted and confirmed the command
  while liveview streamed.
- **Frame saved**: `artifacts/analysis/p8-cinemahud-frame.jpg` (1024×680 RGB,
  141,385 B) — real scene (power strip, microphone), no test pattern.
- Web UI `/` (CinemaHUD html, AMD FSR shader), MJPEG `/liveview.mjpg`,
  single-frame `/frame.jpg`, JSON `/api/status`, control `/api/control`.

## Notes

- This is the **PTP liveview** path (native PC Remote). It is independent of the
  custom UVC overlay work (E0339/E0340/E0341/E0342); UVC real-sensor + PTP
  simultaneously remains the `composite_sensor_feed_single_fd_unmodelled`
  boundary.
- After the session the camera stays in PC Remote; returning to Mass Storage
  likely needs a battery pull (known host enumeration issue). No flash writes.

## Next

- User decision: continue the composite UVC engineering track, or treat the
  CinemaHUD PTP demo as the current deliverable.
