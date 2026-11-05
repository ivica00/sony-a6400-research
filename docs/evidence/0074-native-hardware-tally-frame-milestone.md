# Evidence 0074: Native Hardware Tally REC Frame Milestone on Sony ILCE-6400

## Summary
Visual milestone achieved on physical Sony ILCE-6400 (Serial 03925553, FW 2.00). Direct physical framebuffer memory mapping through `/dev/stream` (`O_RDWR | O_DSYNC`, major 249 minor 7) to OSD layer hardware double-buffers (`PA 0x23a80000` Buffer A, `PA 0x23b16000` Buffer B) renders a rock-solid, flicker-free, 16-pixel thick bright red Tally REC frame overlaid over live camera sensor video and camera UI icons at 60 FPS.

## Hardware Photo Evidence
![Native Tally REC Border on Sony ILCE-6400](C:/Users/Administrator/.gemini/antigravity/brain/b939325a-d3f9-463f-a89d-46a34637e2f0/.user_uploaded/media_1793810550460_4192a6e9.png)

## Key Technical Discoveries

### 1. OSD Display Layer Format
* **Format:** `RGBA4444` (16 bits per pixel, little-endian).
  * Bits 12-15: Red (4 bits)
  * Bits 8-11: Green (4 bits)
  * Bits 4-7: Blue (4 bits)
  * Bits 0-3: Alpha (4 bits)
* **Pure Opaque Red Value:** `0xF00F` (`R=15, G=0, B=0, A=15`).
* **32-Bit Pixel Pair:** `0xF00FF00F` (2 pixels per word).
* **Dimensions:** 640 x 480 pixels (`614,400` bytes per buffer).

### 2. Double-Buffering & Flicker Resolution
* **Buffer A Physical Address:** `PA 0x23a80000`
* **Buffer B Physical Address:** `PA 0x23b16000`
* **Contiguous Stride:** `0x96000` (614,400 bytes).
* **Flicker Cause:** Sony's display hardware alternates scan-out between Buffer A and Buffer B at 60 Hz. Mapping only Buffer A produces a 30 Hz flicker. Mapping both buffers and painting both per frame cycle produces a 100% rock-solid, flicker-free overlay.

### 3. Execution Pipeline
* Autonomous execution on boot via `autoexec_hook.so` -> `autoexec.sh`.
* Zero flash modification; payload lives in `/tmp` (non-volatile partition `nflasha10`).
* Killswitch safety intact (`/mnt/disable_hook`).
