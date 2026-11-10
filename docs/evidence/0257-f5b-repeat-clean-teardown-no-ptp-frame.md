# E0257 — F5b repeat: clean teardown with the PTP probe; no liveview frame inside the composite session

Date: 2026-11-09. Physical session with the unchanged e0251 candidate/runner and the fixed PTP probe (settle 1.5 s, 120 GetObject retries).

## Result

- Probe: connected to `vid_054c&pid_0caa`, SDIO handshake `0x2001` (expected OK), **120 GetObject polls, no frame** (`no_frame`, 1.5 s settle + ~1.8 s polling).
- Session: **`p4_session_completed`** — receipt `stop_verified` + `retired` + `complete result=0`; `rmmod` succeeded; module list restored; camera returned to Mass Storage; **no reboot** (uptime 288.05 s → 457.88 s, monotonic); 42 modules; `usbg_video` absent; `TracerPid: 0`.

## Comparison

| Session | PTP probe | Teardown |
| --- | --- | --- |
| F5b-1 (E0255) | 20 retries, no frame | **failed** (no MSC, `VID_0000`, battery restart) |
| F5b-2 (this) | fixed, 120 retries, no frame | **clean** (receipt + MSC, no reboot) |
| Control (E0256, no module) | fixed, 120 retries | **frame captured** (1024×680) |

The earlier F5b teardown failure did **not** reproduce with the same module and a probe that performed the same handshake plus more failed GetObject polls. The teardown path is now 4/4 clean (three sessions without PTP, one with PTP traffic). The stuck-gadget event remains an unexplained one-off at this point, not a deterministic PTP-in-session effect.

What is reproducible: **the camera delivers no PTP liveview frame inside the composite session**, while the same probe captures 1024×680 in ordinary PC Remote without the module.

## Hypotheses (not yet isolated)

1. **WPD node selection**: during the composite session the host exposed multiple Sony WPD/PnP entries; the client opens `devices[0]`. The no-module control had a single device. The probe may be opening the wrong composite node.
2. **Video suppression**: the enumeration-only candidate suppresses video START; Sony's PTP liveview may be gated on the video function being started.
3. **Descriptor/session difference**: the candidate's PTP interface or device/configuration context may differ from the original PC Remote mode.

## Limits

Two sessions with PTP; no frame; the receipt is present only for this clean run. No sensor frame or UVC streaming was demonstrated inside the composite session. The PTP handshake itself is normal (`0x2001` expected).

## Next

Offline/descriptor diagnosis before another session: compare the original PC Remote PTP interface/device context with the candidate descriptor tree, and enumerate the composite WPD nodes so the probe can select the correct one. Only then design a bounded in-session PTP test.
