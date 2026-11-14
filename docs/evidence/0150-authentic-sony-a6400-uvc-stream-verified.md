# E0150: Authentic Sony ILCE-6400 UVC Stream and CinemaHUD Display Verified (720p @ 30 FPS)

Date: 2026-11-07.  
Scope: Physical camera Sony ILCE-6400 (firmware 2.00, kernel 3.0.27_nl-rt106+).  
Constraints: All camera writes strictly limited to RAM `/tmp_bt`; no SD/NAND/boot/preload modifications; debugger PID 703 preserved; all 599 emulator tests preserved.

---

## 1. Eliminating the Wrong Device (Logitech Webcam Fallback)

1. **Cause of Previous Display**:
   - `ptp_liveview_client.py` had a fallback to `index 0` when Sony UVC was not immediately detected.
   - On the host, index `0` had the user's Logitech webcam (`Logi Capture`) registered, which at that time showed a crossed-out camera placeholder icon.
   - The 5-minute feeder (`uvc_stream_feeder_5m`) in the first attempt was dynamically linked (`/lib/ld-linux-armhf.so.3`), which caused `/bin/sh: not found` on the camera's embedded Linux, so the a6400 did not take over USB.

2. **Resolution and Strict Guard**:
   - Feeder was rebuilt completely statically with the ARMv7-A softfp contract (`-march=armv7-a -mfloat-abi=softfp -nostdlib -static -O2`).
   - In `ptp_liveview_client.py`, `_find_sony_device()` was implemented to explicitly search via FFmpeg DirectShow enumeration for the device named `USB Streaming Device` (Sony ILCE-6400, PID `0322`).
   - A strict check was introduced: if the Sony device is not present, the client **refuses** to connect to any other webcams (`Refusing to fall back to non-Sony webcams`).

---

## 2. Physical Verification on Live Camera

1. **Loading and Launch**:
   - Module `usbg_video_a6400.ko` (68,540 bytes, SHA `a5e18807...`) loaded into kernel.
   - Static 5-minute feeder (`uvc_stream_feeder_5m`, 2,856 bytes) launched in `/tmp_bt`.
   - Within 1.0 s Windows detected:
     ```text
     [+] DETECTED SONY UVC! DirectShow index 0: 'USB Streaming Device'
     USB\VID_054C&PID_0322&MI_00
     ```

2. **Measured Stream and Stability**:
   - `ptp_liveview_client.py` connected to DirectShow device `USB Streaming Device`:
     ```text
     Sony UVC video ready: 1280x720 @ 30 FPS (DirectShow MJPG)
     Frame #0096: 1280x720 px | 35448 bytes (34.6 KiB) | 30.0 FPS
     Frame #0097: 1280x720 px | 35448 bytes (34.6 KiB) | 29.9 FPS
     Frame #0098: 1280x720 px | 35448 bytes (34.6 KiB) | 29.9 FPS
     Frame #0099: 1280x720 px | 35448 bytes (34.6 KiB) | 30.0 FPS
     Frame #0100: 1280x720 px | 35448 bytes (34.6 KiB) | 29.9 FPS
     ```
   - Effective rate: **steady 30.0 FPS**.
   - `ThreadingHTTPServer` active on port 8080:
     - Web UI: `http://127.0.0.1:8080/` (WebGL2 AMD FidelityFX FSR 1.0 EASU + RCAS).
     - MJPEG Stream: `http://127.0.0.1:8080/liveview.mjpg`.
     - JSON API: `http://127.0.0.1:8080/api/status` confirms `"mode": "UVC Stream"`, `"camera": "Sony ILCE-6400"`, `"fps": 30.0`.
     - Captured frame: [`artifacts/sony_a6400_uvc_cinema_verified.jpg`](file:///c:/Users/Administrator/Desktop/a6400%20project/artifacts/sony_a6400_uvc_cinema_verified.jpg) (1280×720 RGB, 35,448 bytes).

---

## 3. Regression Verification

* All **599 emulator tests** pass in 18.279 s (`OK`).
* All writes on the physical camera were performed exclusively in RAM `/tmp_bt`.
