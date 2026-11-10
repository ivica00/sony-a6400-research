# E0255 — F5b: PTP liveview handshake returned 0x2001 and the session teardown ended in a stuck USB gadget

Date: 2026-11-09. Physical session with the unchanged e0251/runner plus the read-only WPD/PTP liveview probe. Recovery required a camera restart (battery removal).

## What happened

- Session staged as in F5a: e0251 (SHA `383ea3b8…`), runner `a7c1b4ea…`, 60 s hold, MSC wait 120 s.
- PTP probe (`run_ptp_liveview_probe.py`) waited for the WPD device, connected at 19:32:08 (`vid_054c&pid_0caa`), and executed the Sony SDIO handshake:
  - `SDIOConnect(1,0,0)` → **rc=0x2001**
  - `SDIOConnect(2,0,0)` → **rc=0x2001**
  - `GetSDIOExtDeviceInfo(0xC8)` → **rc=0x2001**, len=136
  - `SDIOConnect(3,0,0)` → **rc=0x2001**
  - `GetObject(0xFFFFC002)` returned no JPEG → status `no_frame`.
- The session did not return to Mass Storage. The session tool's reconnect attempts failed; its final cleanup recorded `DebuggerError('Camera error -2')` and the manifest remained `started` with no receipt (no `p4_receipt`/`p4_after`).
- Windows then reported the camera as unrecognized (`USB\VID_0000&PID_0002`, descriptor request failed — the E0249 state). Replug and the mode switch did not clear it.

## Recovery

Battery removal/restart. Post-restart read-only check: Mass Storage, uptime **38.67 s** (fresh boot), 42 modules, `usbg_video` absent, `TracerPid: 0`. The camera is healthy.

## Interpretation

F5a showed 3/3 clean teardowns **without** PTP. F5b added a PTP handshake that failed with GeneralError `0x2001` and ended in the same stuck-gadget state as P4b. The leading hypothesis is that the failed PTP transaction left the PTP interface in a state the module's unconfigure-first teardown could not drain, so the gadget never returned to Mass Storage. The exact cause — module descriptor/session interaction vs WPD/Sony-client behavior in this composite configuration — is not isolated.

## Correction (E0256 control)

A no-module control with the same probe also received `0x2001` for every SDIO command and no frame. E0151 documents `0x2001` as the **expected OK reply** for the Sony SDIO handshake, so the handshake did not fail; what failed is only the first `GetObject` poll. The probe used 20 retries (~0.3 s) after the handshake, while E0151 polled continuously at 15 ms and treated 8 zero bytes as "not ready yet". The probe's polling window was too short for a first frame. The F5b teardown failure (no MSC, stuck gadget) remains a real, unconfirmed event, but the earlier "PTP handshake 0x2001" attribution is withdrawn: the handshake was normal.

## Limits

No runner receipt (lost), no final session status; the STOP/retire path is unverified for this attempt. One attempt only; the fixed probe's first-frame wait must be re-tested before drawing conclusions about the module/PTP interaction.

## Next

Control test: the same PTP probe in **ordinary PC Remote without the module** (E0151 baseline). If it captures a 1024×680 frame, the probe/client is fine and the failure is specific to the composite module/PTP interaction; if it fails identically, investigate the WPD/Sony client path before any further module session.
