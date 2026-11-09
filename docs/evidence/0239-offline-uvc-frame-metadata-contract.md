# E0239 — Offline UVC frame-metadata contract (JPEG SOF validation)

Date: 2026-11-09. Offline only: no camera access, no module deployment, no DMA or SD write. First bounded building block of the offline UVC/PTP implementation.

## Purpose

The composite UVC path still lacks a verified "decoded-dimension" gate: the current `IOCTL_UVC_UPDATE` admission checks frame length, 32-bit wrap and source/destination overlap, but it does not prove that the produced JPEG is the announced 720p frame. This step adds a pure, bounded parser for the JPEG SOF dimensions that a future producer must call before `Update`.

## Implementation

- `tools/native_camera/uvc_frame_validate.c/.h`: `a6400_jpeg_sof_dimensions(data, len, &width, &height)`.
- Pure C, no allocation, no I/O, no DMA and no global state; it never reads past `len`.
- Accepts SOF0–SOF3, SOF5–SOF7, SOF9–SOF11 and SOF13–SOF15; skips length-delimited segments with 16-bit big-endian lengths; handles JPEG fill bytes; rejects missing SOI, EOI/SOS before SOF, truncated or undersized segments, 0xffff length overflow and zero width/height.

## Checks

- Host fixture `tools/research/check_uvc_frame_validate.c`: **15 cases pass** (`artifacts/native/uvc-frame-validate-e0239/frame-validate-check.log`), including valid 1280×720, 1024×680, 640×480 and 1920×1080 frames plus all rejection paths.
- ARM compile with the project flags succeeds (`uvc_frame_validate.o`), so the source is usable by the on-camera module build.
- Manifest: `artifacts/native/uvc-frame-validate-e0239/manifest.json` with source/object/executable hashes and explicit limitations.

## Boundary

This is a parser contract, not a sensor frame or a UVC stream. The `IOCTL_UVC_UPDATE` path does **not** call it yet: a producer must first map/validate the source span, confirm the decoded dimensions match the committed descriptors, wait for the destination slot to be free, and only then copy and update. DMM lifetime, per-slot frame lengths, matched unmap/free, the shooting-pipeline preservation and the composite parent/Code 10 diagnosis all remain open. No UVC activation or module load occurred, and the camera was not used.
