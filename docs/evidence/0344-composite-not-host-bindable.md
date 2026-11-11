# E0344 — Composite UVC is not host-bindable: no Windows video device during the session

Date: 2026-11-11. Physical RAM-only diagnostic. Camera left in PC Remote; no
camera writes.

## Test

Feedless composite session (e0288 module + stop-attested runner, `--duration 40`,
`--wait-pcremote`). Host diagnostics ran while the session was active.

## Result

- The host watcher (SetupAPI/libusb enumeration) saw `uvc=1 ptp=1` children from
  13:11:00 to 13:11:28 (USB-level composite presence).
- **Windows PnP had no device matching `VID_054C&PID_0322`** at that time
  (`Get-PnpDevice -PresentOnly | Where InstanceId -like '*054C*PID_0322*'` →
  empty; saved `p9-devices.json` is empty).
- ffmpeg therefore reported
  `Could not find video device with name [USB Streaming Device] among source
  devices of type video` for all four open attempts — **no DirectShow capture
  device existed**.
- Consequence: the composite's UVC interface enumerates on the USB bus but is
  **not bound by Windows' usbvideo/DirectShow stack**. This explains the earlier
  I/O errors even when the inherited-fd feeder was armed: the host could never
  open the interface, independent of feed state. It also explains why the
  E0289 "UVC child present" observations were bus-level only.
- The E0150-module UVC (UVC-only, PID 0322) *is* host-bound (Camera class,
  "USB Streaming Device") and streams the test pattern — so the host stack can
  bind a proper a6400 UVC function; the composite descriptor candidate is the
  gap.
- PTP child: the session's PTP interface likewise did not appear as a WPD/MTP
  device, so the CinemaHUD PTP path could not bind it (the stock `0CAA` WPD path
  is only present in native PC Remote).

## Conclusion / boundary

**`composite_descriptor_not_host_bindable`** — the e0288 shared-enumeration
candidate's UVC (and PTP) interfaces are visible at the USB layer but lack the
descriptor binding Windows needs (UVC VC/VS class layout, IAD, and the PTP/MTP
interface binding). Feeding frames cannot fix this; the descriptor candidate
must be corrected and rebuilt.

## Options

- **A (correct fix):** rebuild the composite descriptor candidate with a proper
  IAD + UVC VC (0x0E)/VS interfaces + PTP (class 6) configuration matching the
  known-good E0134 ZV-E10 173-byte UVC+PTP descriptor (already parsed by
  `usb_host_enum.py`), audit, then test host binding.
- **B (current deliverable):** UVC transport (test pattern, E0150 module) and
  PTP CinemaHUD liveview (E0343) verified separately; composite remains open.
- **C (not recommended):** Windows driver-binding hacks (force usbvideo / remove
  libusb association) — risk to the MSC debugger and camera enumeration.
