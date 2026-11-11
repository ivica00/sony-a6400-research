# E0346 — UVC+PTP composite transport roadmap (long-term track B)

Date: 2026-11-11. Offline planning after E0345 (composite module is
enumeration-only: REG_BUF/ENABLE = -95) and E0344 (no Windows PnP binding for
`054C:0322`).

## Goal

One PC Remote session in which the camera sends a **real UVC video stream**
while **PTP commands stay available**, with CinemaHUD as the host test.

## Verified facts that constrain the plan

- `IOCTL_UVC_INIT` only succeeds in PC Remote mode (E0342).
- The e0288 composite candidate accepts INIT and `MOD_QUERY_DMA` but rejects
  `REG_BUF`/`ENABLE` with -95 (`shared_ioctl` fallback: "enumeration/control
  candidate: no buffer/stream ioctls").
- The shared build sets `-DA6400_UVC_ENUMERATION_ONLY=1`, so the callback bridge
  returns `NOT_HANDLED` for CLASS/VENDOR requests; the reference video callback
  path never runs.
- Windows has never bound the composite children (E0207/E0208: parent only,
  ProblemCode10; E0344: no `054C:0322` PnP device at all), so host binding must
  be fixed before any frame path matters.

## Stages (each built/audited offline, then one bounded physical test)

1. **Host-bindable composite descriptors.** Correct the PTP+UVC configuration
   descriptor construction (`uvc_ptp_descriptors.c` / lease / bundle): PTP
   interface must be class 6/1/1 (PC Remote), UVC VC/VS with IAD, valid
   wTotalLength, and MI_00/MI_01 child binding. Success criterion: Windows PnP
   exposes composite parent + PTP/UVC children with no ProblemCode10, no
   frame claim yet.
2. **Transport enable.** In the shared ioctl, forward REG_BUF (0x4008f000),
   UPDATE (0x4008f003), ENABLE (0xf006) and WAIT (0xf002) to the original
   driver; build without `A6400_UVC_ENUMERATION_ONLY` so the bridge forwards
   CLASS/VENDOR/START to the reference callback. Success criterion: host UVC
   open succeeds and receives frames driven by a simple test-pattern feeder
   over the same fd.
3. **Sensor feed on one fd.** Runner keeps INIT + freezes/hooks, dup2 fd 100,
   forks the inherited-fd sensor feeder (MOD_QUERY_DMA → REG_BUF → ENABLE →
   DMM/JPEG → UPDATE/WAIT). Success criterion: host UVC frame is a real sensor
   frame (`sensor_frames > 0`).
4. **PTP in parallel.** Confirm the PTP child binds (WPD/MTP or a decided host
   binding) and CinemaHUD controls work while UVC streams.
5. **Teardown/recovery hardening** and receipts; then the full CinemaHUD test.

## Current state

Camera healthy in MSC, no module loaded, no flash writes. All logs/helpers in
RAM; the E0345 log is preserved under `/tmp_bt/runner.log`.
