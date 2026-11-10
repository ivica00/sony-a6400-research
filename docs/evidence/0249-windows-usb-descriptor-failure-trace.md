# E0249 — Windows USB connection trace after P4b: descriptor request failed

Date: 2026-11-09. Host-only monitoring after the P4b session. No camera commands, no driver changes, no USB control transfers beyond Windows' own enumeration.

## Observation

With the host monitor running (`tools/research/monitor_windows_usb.py`, 1 s PnP samples plus SetupAPI tail), the user connected the camera in Mass Storage:

- At **~35.7 s** of monitoring a single new USB device appeared:
  - InstanceId `USB\VID_0000&PID_0002\8&F2CB6FA&0&8`
  - FriendlyName **"Unknown USB Device (Device Descriptor Request Failed)"**
  - Status **Error**, Class **USB**, **Problem 43**
- The device persisted unchanged through the remaining samples; no `VID_054C&PID_0CA8` (MSC) or `054C:0CAA` (PC Remote) device appeared.
- Host Sony query returned 0 devices; the camera debugger could not connect (`Expected one existing MSC/MTP camera; found 0`).
- `setupapi.dev.log` produced no new matching lines during the window (delta empty; the PnP state is the primary observation).

## Interpretation

After the P4b enumeration/teardown attempt, the camera's USB peripheral does not answer the device-descriptor request: Windows sees the port as a failed device with VID 0000/PID 0002 and Code 43, even though the camera menu is functional and the user selected Mass Storage. Unplug/replug and the mode switch do not reset the stuck gadget; a camera restart is required. This is a host-visible consequence of the teardown/return failure, not evidence about the camera application or its storage.

## Limits

No raw USB bus capture (USBPcap not installed); the conclusion rests on Windows PnP state and the absence of a Sony identity. SetupAPI delta was empty, so no driver-binding sequence was recorded. The camera's internal state (module loaded, session retained) cannot be read while the USB peripheral is stuck.

## Recovery

Camera restart, then reconnect in Mass Storage and re-run the read-only check. The P4b record (enumeration succeeded; teardown unconfirmed) is separate; no clean unload is claimed.

**Recovery verified:** after the restart the debugger connected in Mass Storage, uptime was 51.18 s (fresh boot), 42 modules, `usbg_video` absent, `TracerPid: 0`, and `/tmp_bt` contained only baseline files. The stuck gadget was cleared by the restart, not by unplug/replug or the mode switch.
