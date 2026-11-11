# E0342 — INIT mode dependence, feed-runner fallback, and host-side limits

Date: 2026-11-11. Offline/physical RAM-only diagnostics. Camera healthy in MSC;
no flash writes.

## Findings

1. **`IOCTL_UVC_INIT` requires PC Remote mode.** Running the feed runner in
   **Mass Storage** (`--wait-pcremote` omitted) reaches the entry-hook publish
   (175 threads frozen/resumed, hook at 0x602b8844) but
   `IOCTL_UVC_INIT` returns **-1/EINVAL (errno 22)**. The runner then stops,
   retires the hook and completes cleanly; camera remains MSC. So INIT is
   valid only while the camera application is in PC Remote mode — the composite
   path cannot be exercised from MSC.
2. **Feed runner + inherited-fd feeder built**: runner duplicates its fd to 100,
   forks/execs `uvc_sensor_inherit` (no second open); feeder now falls back to
   the E0150 fixed buffer (`REG_BUF 0x20000000/1325056`, source 0x20120000) when
   `MOD_QUERY_DMA` fails.
3. **Host-side limits confirmed**: `cv2` and `libmtp` are absent from the venv
   (pyusb is present). The PTP client discovers WPD by vendor only; during the
   composite session no WPD/MTP device existed, so PTP commands could not be
   driven over the composite PTP child. Direct libusb PTP would require a
   WinUSB/libusb driver bound to the composite PTP interface (not present).
4. After the PC Remote session Windows lost the Sony device entirely (known);
   battery removal is the recovery path. This makes on-camera logs
   (`/tmp_bt/runner.log`, feeder output) unreadable after each attempt.

## Consequence

Further composite iterations are **blind** (logs lost) unless we either
(a) deliver host-visible behavior only and infer feeder progress from UVC
frames/open errors, or (b) find a persistent log channel. Current most valuable
practical path: CinemaHUD over **PTP liveview** (real 1024×680 frames verified,
PTP commands work) while UVC stays an engineering track.

## Next options

- A: CinemaHUD PTP liveview demo now (real image + PTP controls; one mode switch
  → expected battery pull afterwards).
- B: one more composite session with host-only diagnostics (UVC open
  pre/post-feeder with delayed feed, PnP problem codes), then battery.
- C: ZV-E10 native UVC overlay path (highest risk, requires replacing
  libInfraUsbCmn/devno semantics; overlay plan remains blocked).
