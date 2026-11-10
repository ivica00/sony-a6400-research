# E0292 — Reconnect retry: no AttributeError; timing window note

Date: 2026-11-09. Offline fix after the reconnect probe failed at the WPD shutdown.

## Failure observed

The reconnect probe's `last_response` was
`AttributeError("'NoneType' object has no attribute 'sendReadCommand'")`: the COM shutdown
triggered `close()` (driver set to None), the immediate `connect()` failed while the device was
still re-enumerating, and the next poll dereferenced the None driver.

## Fix

`SonyWpdPTPLiveView.get_frame` now:
- at the top of each retry, if `drv` is None, **retries `connect()`** (records `reconnected` or
  `reconnect_error`);
- on a WPD shutdown error, closes the driver and continues (the next iteration reconnects);
- never calls `sendReadCommand` on a None driver.

Tests: `tests/test_wpd_shutdown_error.py` now includes a no-driver reconnect-retry case; 4 cases
in that file; full suite **669 tests**.

## Timing note

The capture shows the re-enumeration window: parent 21:36:00.2, brief disconnect 21:36:01.1,
composite back 21:36:08.8 — about **8 seconds**. The probe's `--retries` budget must cover it
(each retry ≈ 15–50 ms); `--retries 120` is borderline (~6–9 s). For the next re-probe use a
larger budget (e.g. `--retries 400`) so the client keeps retrying connect until the device is
back, then resumes GetObject.

## Next

- Reconnect re-probe with the fixed client and a larger retry budget, plus the 0.2 s capture and
  LCD observation; inspect `last_response` (`reconnected`, then `rc`/`len`) or a captured frame.
