# E0253 — F5-0 offline: PTP liveview frame validator and WPD probe ready

Date: 2026-11-09. Offline only: no camera access, no WPD session, no module load.

## Validator

`tools/research/ptp_frame.py`:

- `jpeg_sof_dimensions()` — bounded SOF scan (SOF0–3/5–7/9–11/13–15), 16-bit segments, fill bytes; rejects missing SOI, EOI/SOS before SOF, truncation, zero dimensions.
- `evaluate_frame(data, expected, min_bytes=100)` — returns `ok`, bytes, SHA-256, dimensions, expected and reasons (`too_small`, `no_sof`, `dimension_mismatch`).
- `parse_expect("1024x680")`.

Tests `tests/test_ptp_frame.py`: 5 cases (valid SOF variants, malformed/truncated/zero, too-small/no-SOF/mismatch, parser). Full suite: **641 tests pass**.

## WPD probe

`tools/research/run_ptp_liveview_probe.py`:

- Waits up to `--timeout` (default 240 s) for a Sony WPD device, then uses the existing `SonyWpdPTPLiveView` (Sony SDIO handshake + `GetObject(0xFFFFC002)`).
- Captures **one** JPEG, validates it with the pure validator, saves `liveview.jpg` and `manifest.json` (status, dimensions, bytes, SHA, validation, timings).
- Statuses: `captured`, `no_wpd_device`, `ptp_error`, `no_frame`, `invalid_frame`; every outcome is recorded.
- Read-only; no camera writes, no module changes. `--validate-only FILE` validates an existing JPEG without a camera.
- CLI check: the existing 1280×720 UVC test JPEG is correctly flagged `dimension_mismatch` against the expected 1024×680.

## Limits

The probe has not been run against the camera or WPD yet. The client path is the one demonstrated in E0151 (1024×680 PTP liveview); this step only packages it as a bounded, recorded probe. Expected frame dimensions are recorded, not assumed.

## Next

F5a: two repeated e0251 clean-teardown sessions. F5b: the same session with the PTP probe running, to capture one liveview JPEG and still return to Mass Storage.
