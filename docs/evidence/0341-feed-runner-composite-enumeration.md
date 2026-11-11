# E0341 — Feed runner + inherited-fd feeder: composite children enumerate, but UVC host open fails and Windows loses MSC afterwards

Date: 2026-11-11. Physical, user-authorized RAM-only session (battery removal is
the recovery path; the user confirmed the known post-PC-Remote MSC enumeration
issue). No flash/SD/boot writes.

## Implementation

- New `tools/native_camera/uvc_ptp_feed_runner.c` (built as
  `artifacts/analysis/uvc_ptp_feed_runner.elf`, 16,248 B): the session runner
  gains `--feed <path>`. After a successful `IOCTL_UVC_INIT` it duplicates its
  device fd to **fd 100**, `fork()`s, and `exec()`s the feeder with that
  inherited fd — so the module is opened **once**; no second open and no USB
  mode switch inside the session.
- New `artifacts/analysis/uvc_sensor_inherit_arm` (37,220 B): the sensor feeder
  variant uses `uvc_fd = 100` instead of opening `/tmp_bt/video`, skips
  `IOCTL_UVC_INIT` (the runner already did it), then runs the DMM/JPEG path and
  `REG_BUF`/`ENABLE`/`UPDATE` on the inherited fd.
- Deployed RAM-only: e0288 module (73,072 B, sha `7a3e2f59…`), runner, feeder in
  `/tmp_bt`; runner started with `--wait-pcremote --duration 150 --feed`.

## Result

- Runner opened the device and reached `STEP 0: Waiting for camera to enter PC
  Remote mode`; after the switch the runner proceeded (host observed the
  composite).
- **Composite enumeration succeeded**: the host watcher saw
  `uvc_children=1 ptp_children=1` continuously from 12:55:08 to 12:56:36
  (parent `VID_054C PID_0322` composite). This is the first run where the
  composite UVC+PTP children appear while the inherited-fd feed path is armed.
- **No UVC frames**: every ffmpeg open of `USB Streaming Device` returned I/O
  error while the child was present (`uvc_ready=False`). The feeder/runner logs
  could not be read because the camera disappeared from Windows after the
  session (see below), so the feeder's `MOD_QUERY_DMA`/`REG_BUF`/`ENABLE`
  results are unverified for this run.
- **PTP client could not connect**: it searches for a WPD parent with
  `0CAA`; the composite parent is `0322`, so the WPD/PTP client path does not
  find it even though a PTP child exists. PTP commands over this composite need
  a different host binding than the stock `0CAA` WPD lookup.
- After the session, Windows enumerated **no Sony device at all** (not even
  Mass Storage) — the known post-PC-Remote MSC loss; battery removal is the
  recovery path (per user).

## Boundaries

- **`composite_host_uvc_open_io_error`** — UVC child enumerates but the host
  cannot open the streaming interface; likely the feeder never reached
  `ENABLE`/`UPDATE` (unverified) or the UVC interface needs the feeder's
  alt-setting/stream start.
- **`composite_ptp_host_binding_0322_unresolved`** — the PTP client must bind
  the composite parent (32 2/PTP child), not the `0CAA` WPD parent.
- Known operational: Windows may not re-enumerate MSC after PC Remote; battery
  pull required.

## Next

1. Recover camera (battery), keep MSC.
2. Re-run the feed runner with a **shorter duration** and capture the runner +
   feeder logs **after the session returns to MSC** (before any battery pull);
   verify whether the inherited-fd feeder reached `REG_BUF`/`ENABLE` and
   `sensor_frames > 0`, or add a fixed-buffer fallback if `MOD_QUERY_DMA`
   returns ENOTTY on e0288.
3. Bind the PTP host client to the composite parent/PID 0322 path (or the PTP
   child) and re-test commands while UVC runs.
