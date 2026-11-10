# E0290 — Probe records the PTP GetObject response code and length

Date: 2026-11-09. Offline code/tests only.

## Change

- `SonyWpdPTPLiveView.get_frame` now records `last_response`: the PTP return code and data
  length of every GetObject attempt (or the exception text).
- `run_ptp_liveview_probe` writes `last_response` to the manifest when the result is `no_frame`.
- Tests: `tests/test_ptp_response_diagnostics.py` (3 cases: error code/empty data, OK short data,
  exception). Full suite **665 tests** pass.

## Why

The previous `no_frame` result hid whether the camera answered with an error, an empty data
phase, or short data. With the e0288 liveview-consistency module keeping the device enumerated
(E0289), the next probe can now distinguish:

- camera returns a PTP error code (application rejected the GetObject),
- camera returns OK with 0/short data (app-side frame not produced),
- driver transport error.

That selects the next app-side investigation (E0266–E0270 path) instead of guessing.

## Next

- Physical re-probe with the e0288 module (device stays enumerated) and read
  `last_response` from the manifest, with the 0.2 s capture and the LCD observation.
