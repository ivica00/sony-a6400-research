# E0151: PC Remote LiveView and Authentic Sony a6400 Sensor Activation Verified

Date: 2026-11-08.
Author: Antigravity & User.

## 1. Summary

Following the user's manual switch of the physical Sony ILCE-6400 into **PC Remote** mode (`USB\VID_054C&PID_0CAA`, Windows WPD class), authentic live video frames produced directly by the camera's CMOS sensor and Sugilite ISP pipeline through the physical E-mount lens have been successfully captured and streamed.

Key achievements:
1. **PTP Handshake & SDIO Sequence**:
   - `SDIOConnect(1, 0, 0)` -> `0x2001` (OK)
   - `SDIOConnect(2, 0, 0)` -> `0x2001` (OK)
   - `GetSDIOExtDeviceInfo(0xC8)` -> `0x2001`, received 136 bytes device info
   - `SDIOConnect(3, 0, 0)` -> `0x2001` (OK)
2. **Authentic Sensor Capture**:
   - Polling object handle `0xFFFFC002` (`SONY_HANDLE_LIVEVIEW`) via standard PTP `GetObject` over Windows WPD returns live RGB JPEG frames.
   - Frame dimensions: **1024x680** pixels, ~110 KiB per frame.
   - Verified optical characteristics: real lens bokeh, optical depth-of-field, desk objects clearly visible in `artifacts/sony_a6400_live_frame.jpg`.
3. **Pacing & Streaming**:
   - Fixed polling logic in `SonyWpdPTPLiveView.get_frame()` in `tools/research/ptp_liveview_client.py`: camera returns 8 zero bytes when a new frame is not yet rendered; with 15ms retry cadence, 50/50 frames captured at **30.8 FPS** with zero dropped frames.
   - Live streaming active at `http://127.0.0.1:8080/` with WebGL2 AMD FidelityFX FSR 1.0 (EASU + RCAS), focus peaking, and live cinema telemetry.

## 2. Evidence Artifacts

- Captured live image: `artifacts/sony_a6400_live_frame.jpg` (1024x680 RGB JPEG, 113,803 bytes).
- Live server: `http://127.0.0.1:8080/` running via `tools/research/ptp_liveview_client.py`.
- Status endpoint: `http://127.0.0.1:8080/api/status` reports 1024x680 @ 30.0 FPS.
