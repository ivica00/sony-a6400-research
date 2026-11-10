# E0293 — Reconnect2: PTP child present in PnP, but the WPD API list is empty

Date: 2026-11-09. Physical reconnect2 run (e0288) + host-side observation.

## Result

- Session: **`p4_session_completed`**, receipt ok, `p4_after` ok (module restored, no reboot);
  camera back in Mass Storage (uptime 1670.09 s, 42 modules).
- Capture: parent 21:44:34.6, **parent+PTP child+UVC child 21:44:45.7**, children gone
  21:45:43.7 (teardown), all gone 21:45:44.5 (MSC).
- Probe: **`no_wpd_device`** after 119 attempts (~238 s), `last_error: No Sony camera found...`;
  no connection, no `last_response`/frame. The probe polls `MtpContext.listDevices(0x054C)`.

## Interpretation

The PTP child **was enumerated** (PnP shows `USB\VID_054C&PID_0CAA&MI_00`, Class WPD, "MTP USB
Device") for ~58 s, but the WPD API enumeration used by the probe returned nothing. This is a
host WPD binding/service issue, not a USB enumeration failure: previously the same client saw
`device_count=1`. The composite PTP child may bind WPD without a usable WPD service (the classify
properties are "Access denied"), or the WPD service did not attach for this re-enumeration.

This also explains the earlier intermittent `no_wpd_device` sessions (F8-5, P1/P2 timing) and the
value of the PnP capture: the device is there, the WPD client just cannot list it.

## Next

- Offline/host analysis of the WPD binding for the composite PTP child: SetupAPI log around the
  re-enumeration, WPD service state, driver INF, and why `MtpContext.listDevices` is empty while
  PnP shows the child.
- Then decide: fix the WPD binding (driver/service), or use a transport that does not depend on
  the WPD API (e.g., direct USB PTP via libusb) for the repeat probe.
