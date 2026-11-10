# E0248 — P4b: simultaneous PTP+UVC enumeration succeeded; USB return stuck, recovered by restart

Date: 2026-11-09. Physical session with e0212 and the rebuilt stop-attested runner. No streaming, no sensor frames, no SD write.

## Preflight and staging

- Module `e0212` SHA-256 `1bcb464842e8d478a8735be46161689f6d3e8c280c6b048bd94a2687f9e33b23` (72,512 B), audit passed, upload read-back verified.
- Runner rebuilt SHA-256 `a7c1b4ea397797044877976120b626a82f38cf7d0f6307f615c1b13d2c4af47e` (16,048 B), upload read-back verified.
- P4 preflight `ok=True`; `insmod`, `mknod` and runner launch returned 0; runner confirmed ready before the switch.
- Parameters: duration 60 s, MSC wait 120 s, strict policy (`p4_policy`).

## Host enumeration

- At ~50.7 s the parent `USB\VID_054C&PID_0CAA\CF93603BE631` appeared (`WPD`, ILCE-6400).
- At ~54.5 s **both children were present and Status OK**:
  - `USB\VID_054C&PID_0CAA&MI_00\...` — WPD / **MTP USB Device**
  - `USB\VID_054C&PID_0CAA&MI_01\...` — Camera / **ILCE-6400**
  - Parent: **USB Composite Device** (`usbccgp`-class)
- The tool's `children_ready_simultaneously` flag stayed false because `Get-PnpDeviceProperty` returned **Access denied** for `Service`, `ProblemCode`, etc.; the raw device presence and Status OK are the observed facts. No driver installation was performed.
- At ~118 s both children disappeared from the host.

## Teardown

- The camera did not return to Mass Storage within 120 s: report status `teardown_unconfirmed`.
- The policy **did not attempt `rmmod`**; the module was preserved. The runner receipt could not be collected.
- A host connection trace (E0249) then showed only `USB\VID_0000&PID_0002` — "Unknown USB Device (Device Descriptor Request Failed)", Problem 43 — with no Sony identity, even after the user selected Mass Storage.

## Recovery

- The user restarted the camera. Post-restart read-only verification: debugger connected in Mass Storage, uptime **51.18 s** (reboot), **42 modules**, `usbg_video` **absent**, `TracerPid: 0`, `/tmp_bt` contains only baseline files (the P4b module/runner/receipt files were RAM and are gone).

## Interpretation

With the guarded e0212 candidate and the stop-attested runner, Windows enumerated **PTP and UVC children simultaneously** — the enumeration objective of P4 was met. The teardown/return objective was **not** met: the gadget did not come back to MSC and ended in a descriptor-request-failed state. Because the receipt was lost with the restart, the failed runner phase (STOP, status, retire, or the USB gadget reset) is unknown. This is the same failure class as E0210, now observed with the newer runner and strict policy.

## Limits

No runner receipt (RAM lost), no raw USB bus capture, and the PnP classifier could not read ownership properties. The restart restored Mass Storage but is not proof of a reversible teardown. No UVC streaming, sensor frame, PTP transaction or SD write occurred.

## Next

Teardown diagnosis: a receipt/stage beacon that survives the USB failure (e.g., a RAM marker readable after a manual mode return, or a pre-STOP beacon), and a reviewed gadget-reset/return path. Do not repeat physical activation until that plan exists.
