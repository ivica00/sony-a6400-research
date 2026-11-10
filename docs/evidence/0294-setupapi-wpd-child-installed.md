# E0294 — SetupAPI: the MI_00 WPD child installed OK, yet the WPD API list was empty

Date: 2026-11-09. Offline analysis of the reconnect2 SetupAPI capture + probe diagnostic.

## SetupAPI evidence (reconnect2 session)

- 22:44:30 the parent `USB\VID_054C&PID_0CAA\CF93603BE631` selected/installed `wpdmtp.inf`
  (MTP.NT, compatible ID `usb\class_06&subclass_01&prot_01`) — the single-function MTP path.
- 22:44:36-22:44:41 the child `USB\VID_054C&PID_0CAA&MI_00\...` selected/installed
  **`wpdmtp.inf`**, "Starting device completed" at 22:44:41, **Exit status: SUCCESS**.
- So Windows *did* install the composite PTP child as a WPD/MTP device, and it was present for
  the session (PnP capture: MI_00 Class WPD, ~58 s).
- The probe's `MtpContext.listDevices(0x054C)` nevertheless returned empty for the whole window
  (119 attempts) — the WPD API did not expose the device.

`parseDeviceId` (pmca) handles `vid_054c&pid_0caa&mi_00` correctly, so a listed `MI_00` ID would
match; the list itself was empty.

## Diagnostic added

`run_ptp_liveview_probe.py` now has `wpd_snapshot()`: it records the **raw WPD IDs**
(`_listDevices()` unfiltered) and the **PnP WPD class instances** (PowerShell
`Get-PnpDevice -Class WPD`) into the manifest at connect attempt 20 and 60. This will show on the
next physical test whether the WPD list is truly empty or the IDs are filtered out.

Smoke-tested in Mass Storage (empty lists, no error). Full suite **669 tests** pass.

## Next

- Physical re-probe with the snapshot; inspect `wpd_snapshot` when `no_wpd_device` occurs.
- If the raw WPD list contains the MI_00 ID but the filter drops it, fix `parseDeviceId`/filter.
- If the raw list is empty while PnP has the WPD child, the WPD service/bus-enumeration is the
  issue (driver/service state, UMDF host) — consider a non-WPD transport or a service restart.
