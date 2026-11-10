# E0295 — Snapshot timing fixed: capture every 10 attempts with the working PnP classifier

Date: 2026-11-09. Offline fix after the snapshot re-probe returned empty snapshots.

## Why the snapshots were empty

The probe took snapshots only at connect attempts 20 and 60. With ~2 s polls:
- attempt 20 ≈ 21:54:01 — **before** the composite child appeared (21:54:09),
- attempt 60 ≈ 21:55:21 — **after** the children disappeared (21:55:04 teardown).

Both snapshots therefore fell outside the child-present window, and the fallback
`Get-PnpDevice -Class WPD` command returned empty in that context anyway.

## Fix

- `wpd_snapshot()` now uses the **known-working classifier** (`uvc_ptp_windows_host.classify`
  / `query_devices`) and records `ptp_children`/`uvc_children` InstanceIds plus the raw WPD IDs
  (`_listDevices` unfiltered).
- The probe takes a snapshot **every 10 connect attempts** into `wpd_snapshots` (attempt, UTC,
  raw WPD IDs, PTP/UVC children), so the child-present window is covered.
- Smoke-tested in Mass Storage (empty lists, no error). Full suite **669 tests**.

## Next

- Re-run the physical re-probe with the improved snapshots; the manifest will show, during the
  child-present window, whether the raw WPD list contains the MI_00 device while PnP shows it.
  That decides: filter/parse fix vs WPD service/bus-enumeration issue (non-WPD transport).
