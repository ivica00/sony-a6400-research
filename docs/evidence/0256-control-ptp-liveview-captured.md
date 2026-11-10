# E0256 — Control PTP liveview without the module captured a 1024×680 frame; probe polling corrected

Date: 2026-11-09. Physical control in ordinary PC Remote (no module). Read-only PTP.

## Result

- Camera in ordinary PC Remote (`VID_054C&PID_0CAA`, WPD), **no module loaded**.
- Fixed probe (`run_ptp_liveview_probe.py`, settle 1.5 s, 120 GetObject retries): `status=captured`.
- Frame: **1024×680**, **150,292 bytes**, SHA-256 `2afc3e053d50ba050cae74870f5d3f1f4eccafd81bc1034a4eb0c65d6cd61f18`, saved as `artifacts/hardware/f5-control-ptp-2/liveview.jpg`.
- The Sony SDIO commands returned `0x2001`, which E0151 documents as the **expected OK** reply; the handshake was normal.

## Correction of E0255

The earlier "PTP handshake failure" attribution is withdrawn. `0x2001` is the expected Sony SDIO reply. The first probe used only 20 retries (~0.3 s) after the handshake; E0151 polled continuously at 15 ms and treated 8 zero bytes as "not ready yet". The no-frame result in F5b and control-1 was a probe polling bug, not a PTP interface failure.

What remains real: the F5b module session did not return to Mass Storage (stuck `VID_0000/PID_0002`, battery restart). Its only PTP traffic was the handshake plus ~20 failed GetObject polls; no frame was captured. The teardown failure is therefore **not explained by a PTP handshake error**, and whether the brief PTP activity contributed is unresolved.

## Next

Repeat F5b with the fixed probe (settle 1.5 s, 120 retries) so the session includes a captured PTP liveview frame, then measure the teardown. If the teardown fails again, PTP-during-session interaction is implicated; if it is clean, the earlier failure is an unexplained one-off and the teardown path remains proven 3/3 without PTP.
