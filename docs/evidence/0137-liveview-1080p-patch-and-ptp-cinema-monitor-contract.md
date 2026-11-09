# E0137: Live View 1080p Persistent NVRAM Patch and PTP Cinema Monitor Contract

Date: 2026-11-07. User authorized Experiment 1 (PTP 1080p Live View via persistent NVRAM configuration) and requested testing integration with `https://github.com/shivvyas2/Sony-Alpha-A6400-Cinema-Monitor`.

## 1. CinemaHUD / Cinema Monitor Architecture Analysis

Inspection of `shivvyas2/Sony-Alpha-A6400-Cinema-Monitor` confirmed the remote protocol and LiveView contract:
- **Transport**: USB PTP in camera mode `PC Remote` (USB class 6, subclass 1, protocol 1).
- **Handshake Sequence**:
  - `PTP_OC_OpenSession` (`0x1002`, session 1)
  - `PTP_OC_SonySDIOConnect` (`0x9201`, `[1, 0, 0]`)
  - `PTP_OC_SonySDIOConnect` (`0x9201`, `[2, 0, 0]`)
  - `PTP_OC_SonyGetSDIOExtDeviceInfo` (`0x9202`, `[0xC8]`)
  - `PTP_OC_SonySDIOConnect` (`0x9201`, `[3, 0, 0]`)
  - `PTP_OC_SonySetControlDeviceA` (`0x9205`, `[0xD25A]`, `value=1`) - prioritizes PC control over body buttons.
- **LiveView Stream Extraction**:
  - Transaction: `PTP_OC_GetObject` (`0x1009`, `[0xFFFFC002]`).
  - Framing: Strips Sony vendor envelope by searching for JPEG SOI (`0xFF 0xD8`) and EOI (`0xFF 0xD9`).

## 2. Freestanding Native Flash Patcher (`patch_backup_tiny`)

To safely update `/setting/Backup.bin` on camera flash without relying on busybox applets (which lack `conv=notrunc` and truncate on output redirection):
- Built `tools/native_camera/patch_backup_tiny.c`:
  - Size: 2,312 bytes stripped.
  - Architecture: ARMv7-A (`-march=armv7-a -marm -nostdlib -fno-builtin`).
  - Syscalls: Direct Linux kernel EABI syscalls (`sys_open`, `sys_lseek`, `sys_read`, `sys_write`, `sys_close`, `sys_sync`, `sys_exit` via `svc 0`).
  - Pre-image guards:
    - Verifies exact file size: 1,171,036 bytes.
    - Checksum byte (offset 32): expected `0x25` (original) / `0x2b` (patched).
    - `force_backup` byte (offset 1,145,720): expected `0x00` (original) / `0x01` (patched).
    - `default_width_hi` byte (offset 1,145,723): expected `0x02` (640 px) / `0x07` (1920 px).
  - Actions:
    - `check`: Validates and reports status without modifying flash.
    - `apply`: Applies 3-byte modification, calls `fsync()` and `sync()`.
    - `revert`: Deterministically restores original 3 bytes, calls `fsync()` and `sync()`.

## 3. Physical Camera Execution & Verification

Executed via root debugger (PID 1793):
1. **Initial Status Check**:
   ```text
   Backup.bin state: chk=25 force=00 width_hi=02
   STATUS: ORIGINAL (640x480 LiveView, force_backup=0)
   ```
2. **Apply Patch**:
   ```text
   SUCCESS: 1080p LiveView patch applied
   Backup.bin state: chk=2b force=01 width_hi=07
   STATUS: PATCHED (1920x1080 LiveView, force_backup=1)
   ```
3. **PMCA Checksum & Property Integrity Readback**:
   - Length: 1,171,036 bytes (truncated: False).
   - Header Checksum: `0x696a22b` (VALID).
   - Property `0x01710000`: `01` (`force_backup = 1`).
   - Property `0x01710002`: `8007` (`default_width = 1920`).
4. **Revert & Re-apply Cycle**:
   - `revert` confirmed restore of `chk=25 force=00 width_hi=02`.
   - `apply` restored `chk=2b force=01 width_hi=07`.

## 4. Live View Client & Streamer (`ptp_liveview_client.py`)

Implemented `tools/research/ptp_liveview_client.py`:
- Connects to camera in PC Remote mode via `libusb` PTP transport.
- Executes Sony SDIO handshake.
- Fetches frames from handle `0xFFFFC002`.
- Decodes JPEG SOF0 marker to report exact pixel width and height.
- Embeds HTTP MJPEG streamer (`http://127.0.0.1:8080/`) for live viewing in any browser, OBS, or CinemaHUD.

## 5. Regression Verification

Ran full test suite: 599 tests pass in 17.198s.
Camera flash state: 1080p patch persistently applied; debugger PID 1793 intact.
