# E0339 — Physical UVC/PTP progress: PTP liveview real frames, UVC transport, composite enumeration

Date: 2026-11-11. **Physical** camera work, explicitly authorized by the user
("upgrade PTP/UVC mode; everything in RAM; battery removal is recovery; test on
CinemaHUD"). All camera writes were confined to RAM `/tmp_bt`; no flash, SD,
boot or preload changes. Camera ended in Mass Storage with no loaded module.

## 1. Results

### A. PTP PC Remote liveview — real sensor image (verified)
`ptp_liveview_client --source ptp` over Windows WPD (`VID_054C PID_0CAA`,
ILCE-6400):

- SDIO handshake completed (`SDIOConnect`, `GetSDIOExtDeviceInfo`).
- 20 liveview frames captured, 1024×680, ~52–87 KB each, ~11 FPS.
- Saved frame: `artifacts/analysis/p6-ptp-liveview.jpg` (real scene, not a
  pattern). This is the first recorded real PTP liveview frame in this
  session series.

### B. UVC transport on the current firmware (verified with test pattern)
E0150-style RAM deployment:

- `usbg_video_a6400.ko` (68,540 B, SHA `a5e188076461e254…`) insmod **status 0**,
  `mknod /tmp_bt/video c 248 33`, `uvc_stream_feeder_5m` (2,856 B) launched.
- Windows enumerated `USB Streaming Device` (`VID_054C PID_0322 MI_00`) and
  audio `MI_02`; ffmpeg captured a **1280×720** frame,
  `artifacts/analysis/e0150-uvc-frame.jpg` — the feeder's built-in test pattern
  ("SONY a6400 UVC 720p @ 30 FPS"), i.e. transport works, sensor feed does not.
- Feeder auto-teardown after 5 minutes restored Mass Storage.

### C. Composite UVC+PTP enumeration (verified, briefly)
With the e0288 liveview-consistency module and the stop-attested runner
(`--p4`, 90–120 s), the session completed cleanly:

- `p4_session_completed`, markers init/stop_verified/retired/completed all true,
  `module_list_restored: true`, `usbg_video_after: false`, `reboot: false`.
- During one session the host watcher observed **3 devices: 1 composite parent,
  1 PTP child, 1 UVC child** (`p6-host-watch.jsonl`).
- The PTP/UVC clients were started before the switch and missed the window;
  the UVC client also failed on a missing host dependency (`cv2`).
- The runner completed event 0x13 work earlier; no UVC frames were produced by
  the composite session itself.

### D. Sensor (real JPEG) feeder — built and tested, blocked
- `tools/native_camera/uvc_sensor_feeder_30fps_arm` (34,980 B) drives the DMM
  Rule-5 + SET_PATH 720p30 path and copies real sensor JPEGs from the UIPC DMM
  queue into the UVC DMA slot.
- With the owned-DMA module: DMM Rule 5 **status 0**, SET_PATH 720p30 **status 0**,
  owned DMA 256 KiB obtained; then `IOCTL_UVC_INIT` **−19 (ENODEV)** under the
  e0288 composite module because that module's INIT requires the runner's
  PID-149 freeze/entry-hook publication.
- A freestanding **attach feeder** (skip INIT, retry REG_BUF/ENABLE) was built
  (`artifacts/analysis/uvc_sensor_attach_arm`, 37,376 B) for attaching to an
  active composite session, but its `open("/tmp_bt/video")` returned **−12
  (ENOMEM)**: the module needs a large contiguous DMA allocation per open, and
  the second `open()` (after the runner's) cannot be satisfied on the current
  fragmented memory. No frames were produced.

## 2. Boundaries

- **`composite_sensor_feed_single_fd_unmodelled`** — real sensor frames plus
  PTP in one session require feeding through the **runner's own fd** after its
  `IOCTL_UVC_INIT` (MOD_QUERY_DMA → REG_BUF → ENABLE → DMM/JPEG →
  UPDATE/WAIT) instead of a second `open()`; the runner does not feed yet.
- **`uvc_host_client_cv2_missing`** — the host UVC client path imports `cv2`,
  which is not installed in the project venv; ffmpeg was used instead.
- Composite children are present only while the runner session is active; the
  host monitoring/clients must start **after** the switch (timing-critical).

## 3. Next

1. Build a merged runner: after `IOCTL_UVC_INIT`, use the same fd to query the
   owned DMA metadata, register/enable the buffer, start the DMM/JPEG sensor
   path and submit frames at 30 FPS during the hold phase; stop/retire as today.
2. Deploy RAM-only after a fresh boot (contiguous memory), switch to PC Remote
   when prompted, then verify UVC sensor frame + PTP child simultaneously and
   test CinemaHUD (UVC image + PTP commands).
3. Keep the battery-removal recovery contract: no flash writes; module and all
   helpers remain in RAM only.

Full emulator suite remains green (1181 tests OK); no source changes were made
for this physical round.
