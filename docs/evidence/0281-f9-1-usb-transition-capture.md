# E0281 — F9-1: read-only high-frequency USB transition capture

Date: 2026-11-09. Offline/host tool only.

## Tool

`tools/research/capture_usb_events.py`:
- Polls the existing PnP classification (`query_devices`/`classify`) at a configurable interval
  (default 0.2 s, minimum 0.05 s) for a bounded duration.
- Writes `samples.jsonl` (UTC, elapsed, summarized binding: parent/PTP/UVC counts and readiness)
  and `manifest.json` with only the **state transitions** (`detect_transitions`).
- Read-only: no camera access, no device writes.

Tests: `tests/test_capture_usb_events.py` (3 cases: summary counts/flags, transition detection,
empty). Smoke run in Mass Storage wrote the expected single "no parent" sample. Full suite
**660 tests** pass.

## Use

For the next PC Remote test, start this capture just before the user switches to PC Remote and
stop it after the liveview transition. The transitions show the disconnect, the re-enumeration,
and whether the PTP/UVC children return (or a descriptor failure appears), which the 1.5 s session
monitor can miss.

## Limits

PnP polling only (no USB bus capture); a transition shorter than the interval can still be
missed. No camera-side events.
