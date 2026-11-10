# E0287 — P3b: handshake → liveview → the whole device disappears (Windows "device unknown")

Date: 2026-11-09. Physical bounded test (probe retry after an ENOMEM abort), battery recovery.

## First P3 attempt

- Session failed before the test: runner `FAIL open device ... Cannot allocate memory (errno=12)`.
- Receipt contained only the FAIL line; module was loaded with refcount 0. Recovery: `rmmod usbg_video`,
  removal of the owned /tmp_bt files; camera verified 42 modules, no `usbg_video`.

## P3b retry (after recovery)

- Probe: `no_frame`; connected (`device_count=1`), 120 GetObject retries, **`closed_utc` written**
  (the new close/finally path worked).
- **LCD liveview: DA** (operator).
- Capture timeline:
  - 21:16:54.4 parent appears,
  - 21:16:55.2 parent briefly 0,
  - 21:17:02.9 **parent + PTP child + UVC child**,
  - **21:17:19.1 parents 0, children 0 — the whole device disappears and never returns**.
- Session: **teardown unconfirmed** — `status: started`, no `p4_receipt`, `cleanup_error:
  DebuggerError('Camera error -2: ')`, `host_enum_gate` false.
- Windows reported "device unknown"; Mass Storage did not return. **Battery restart** recovered.
- After restart: MSC healthy (uptime 69.53 s, 42 modules, no `usbg_video`, `TracerPid: 0`).

## Interpretation

The trigger chain is now clear:

```
WPD open + PTP handshake (probe) → camera starts liveview (LCD DA)
  → app gadget re-create / UDC restart → USB device disappears entirely
  → Windows "device unknown", no PTP child, no MSC; teardown unconfirmed
```

P1/P2 showed enumeration and open/close alone do not trigger this; the **handshake/liveview
start** does. The failure is not just the PTP/UVC child functions: the whole device drops off the
bus and does not re-enumerate, so the mitigation must keep/restore the UDC enumeration through
the app's liveview-start re-create (E0282 option A: unhook/consistent config around the re-create;
option B: re-apply the descriptor/function set and re-arm the UDC after `usb_gcw_start`).

## Next

- Implement the mitigation in the shim: hook `usb_gcw_stop`/`usb_gcw_start` (or the app create
  path) and, after the app's re-create, re-apply the module descriptors/function set and re-arm
  EP0/pullup; fall back to a consistent stillimage-only configuration if the composite cannot be
  restored.
- Then a controlled repeat probe with the 0.2 s capture.
