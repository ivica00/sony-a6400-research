# E0291 — The WPD COM object is shut down at liveview start; probe reconnects

Date: 2026-11-09. Physical re-probe diagnostics + offline fix.

## Diagnostic result (e0288 re-probe)

- `status: no_frame`; `last_response`:
  `COMError(-2144731134, 'Shutdown was already called on this object or the object that owns it.')`.
- The probe connected (`device_count=1`) and then, during the GetObject polls, the WPD COM
  object was invalidated — the device re-enumerated at liveview start and the host's old WPD
  handle died. The e0288 mitigation keeps the **device** enumerated (E0289), but the host
  session object is still shut down.

## Fix (offline)

- `is_wpd_shutdown_error(exc)` detects the "Shutdown was already called" COM error.
- `SonyWpdPTPLiveView.get_frame` now **closes and reconnects** (up to 2 times) on that error,
  then continues polling; records `reconnected`/`reconnect_error` in `last_response`.
- Tests: `tests/test_wpd_shutdown_error.py` (3 cases). Full suite **668 tests**.

## Next

- Re-probe with the reconnect-capable client and e0288: connect → handshake → GetObject;
  at liveview start the object may shut down, the client reconnects to the re-enumerated device
  and retries GetObject; the manifest shows whether frames now arrive.
