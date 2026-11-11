# E0345 — Composite module is enumeration-only: REG_BUF/ENABLE(-95), no video transport

Date: 2026-11-11. Physical RAM-only session with preserved logs (MSC returned
without a battery pull this time). No camera writes.

## Decisive log (preserved on camera)

`/tmp_bt/runner.log` from the inherited-fd feed session:

```
SESSION_RUNNER start ... wait_pcremote=1 ...
STEP 0: Detected PC Remote mode ... at 29 seconds
STEP 1: FREEZE threads=181 ... Entry hook published ...
STEP 2: IOCTL_UVC_INIT returned ret=0 errno=22 (Invalid argument)
STEP 2: sensor feed launched pid=1516 fd=100 path=/tmp_bt/uvc_sensor_inherit
STEP 2: Composite session ACTIVE! Holding for 45 seconds...
USB_STATE sec=0 flags=00000006 config=0 mode=0 speed=1
=== A6400 COHERENT SENSOR UVC FEEDER (30 FPS) ===
[feeder] DMM Rule 5 status=0
[feeder] SET_PATH 720p30 status=0
[feeder] using inherited UVC fd=100
[feeder] Owned DMA: phys=0x00740000 total=262144 slot=131072 max_payload=131060
[feeder] IOCTL_UVC_INIT status=0
USB_STATE sec=1 flags=00000006 config=1 mode=0 speed=1
STEP 3: Composite session stopped; IDLE/unpinned/no hooks/no error verified.
STEP 4: Entry hook retired, 0xe1a0c00d restored...
SESSION_RUNNER complete result=0
[feeder] REG_BUF status=-95
[feeder] IOCTL_UVC_ENABLE status=-95
[feeder] Streaming loop completed: total_frames=0 sensor_frames=0
=== A6400 FEEDER SESSION CLEANLY TERMINATED ===
```

## Interpretation

- The e0288 composite module accepts `IOCTL_UVC_INIT` (session active,
  config=1) and even `MOD_QUERY_DMA` (owned DMA 0x00740000, 256 KiB), but
  **`IOCTL_UVC_REG_BUF` and `IOCTL_UVC_ENABLE` return -95 (EOPNOTSUPP)**.
- Therefore the module is **enumeration-only** for the composite candidate: it
  has no external-buffer/UVC transport path. `UPDATE` cannot follow; the feeder
  correctly reports `total_frames=0 sensor_frames=0` and terminates cleanly.
- Combined with E0344 (no Windows PnP binding for `054C:0322`), video over this
  composite module is not achievable with the current build: it neither binds
  on the host nor accepts frames.
- The earlier 5m test-pattern UVC works only with the **UVC-only E0150 module**
  (which has REG_BUF/ENABLE/UPDATE but no PTP function).

## Consequence / boundary

**`composite_module_enumeration_only`** — real UVC video plus PTP in one session
requires either:

1. implementing the composite module's UVC transport (Update/WAIT/release +
   host-bindable UVC/PTP descriptors — kernel-module work), or
2. the ZV-E10 native UVC stack overlay (E0321/E0322, still blocked/risky), or
3. accepting the verified split deliverable: PTP CinemaHUD liveview (E0343) and
   UVC test-pattern transport (E0339/E0340) as separate modes.

Camera is healthy in MSC; module unloaded; no flash writes. Operational note:
this time MSC returned without a battery pull, so logs were preserved.
