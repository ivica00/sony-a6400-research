# E0340 — Fixed-buffer UVC transport on E0150 module; USB mode switch during active UVC caused a camera reboot

Date: 2026-11-11. Physical, user-authorized RAM-only session (no flash/SD/boot
writes). Camera recovered in Mass Storage after the reboot.

## Results

### A. Fixed-buffer sensor feeder attaches to the E0150 module
The E0150 `usbg_video_a6400.ko` (68,540 B, SHA `a5e188076461e254…`) has **no
MOD_QUERY_DMA** ioctl (`IOCTL_UVC_MOD_QUERY_DMA` → `-25/ENOTTY`), so the sensor
feeder was rebuilt to use the module's known buffer window instead:

- `REG_BUF size=1,325,056 phys=0x20000000`; source frame buffer
  `0x20120000` (the same disjoint window the E0150 5m feeder uses);
- `artifacts/analysis/uvc_sensor_fixedbuf_arm` (37,248 B).
- Feeder log: `DMM Rule 5 status=0`, `SET_PATH 720p30 status=0`,
  `IOCTL_UVC_INIT status=0`, `IOCTL_UVC_REG_BUF status=0`,
  `IOCTL_UVC_ENABLE status=0`; 43 test-pattern frames streamed; clean teardown
  (`UNREG`, SET_PATH reset, Rule 0 restore) and Mass Storage returned.
- **`sensor_frames=0`** — the DMM JPEG queue (`QUEUE_SCALAR 0x0167046a`) never
  produced a frame while the camera application stayed in Mass Storage, so the
  feeder kept its built-in test pattern; the Windows UVC frame was again
  `e0150-uvc-frame.jpg` (19,852 B, 1280×720).

### B. Switching to PC Remote during the active UVC overlay rebooted the camera
A 100-second feeder window (`tick < 3000`) was started in MSC; Windows
enumerated `USB Streaming Device` (054C:0322). The user then switched
`USB Connection → PC Remote` while the feeder/UVC overlay was streaming.
Result: the camera **rebooted** (uptime reset to 55 s, `/tmp_bt` cleared, module
gone, back in MSC). `/tmp_bt/feeder.log` was lost with the reboot, so
`sensor_frames` for that window cannot be read.

Interpretation: on this firmware the E0150 module's UVC overlay does not
survive a USB-mode change / liveview re-create; the mode switch while the
overlay is active is unsafe (consistent with the E0210/E0289/E0296 freeze
history). This is not evidence of sensor frames via UVC.

## Boundary

- **`uvc_mode_switch_during_overlay_unsafe`** — do not switch USB modes while a
  synthetic UVC overlay is active; the camera may reboot.
- **`composite_sensor_feed_single_fd_unmodelled`** stands: real sensor frames
  plus PTP must be fed through the composite runner's own fd after
  `IOCTL_UVC_INIT` (MOD_QUERY_DMA → REG_BUF → ENABLE → DMM/JPEG → UPDATE),
  inside one session that already tolerates liveview (e0288 liveview
  consistency), with no mid-session USB mode switch.

## Next

Build the merged runner (single fd, single session) and deploy on a fresh boot;
then verify UVC sensor frame + PTP child simultaneously and test CinemaHUD.

Camera is healthy in MSC; no flash writes were made; emulator suite 1181 OK.
