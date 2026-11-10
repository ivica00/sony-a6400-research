# E0242 — Offline producer submission state machine and opt-in ioctl design

Date: 2026-11-09. Offline only: no camera access, no module build change, no driver Update, no UVC activation. This is step P3b of the UVC/PTP critical path.

## Purpose

Wrap the E0241 admission gate in a bounded one-frame-in-flight state machine, so a future producer ioctl cannot submit a second frame before the first is consumed, and define the opt-in wiring without enabling video.

## Implementation

- `tools/native_camera/uvc_producer_submit.c/.h`:
  - state: one `pending` record, two slot states, a generation counter;
  - `submit`: rejects if a frame is already pending; otherwise calls the E0241 admission and records `{slot, frame_size, phys_addr, generation++}` on success; a rejection leaves the state unchanged;
  - `release(slot)`: requires the pending record to match the slot, clears it and marks the slot ready; the caller asserts that the driver Update/WAIT completed — the function never waits;
  - `get_pending`: returns 1 with fields, 0 when idle (outputs zeroed), -1 on bad arguments.

## Checks

- 10 host cases pass (`artifacts/native/uvc-producer-submit-e0242/producer-submit-check.log`): first submit pending/consumes slot 0; only one frame in flight; wrong-slot release rejected; correct release clears and frees; new generation on reuse; slot 1 path; rejected submit leaves pending/generation unchanged; release without pending rejected; invalid pointers/slots rejected; idle accessor zeroes outputs.
- ARM compile of the state machine succeeds; manifest `artifacts/native/uvc-producer-submit-e0242/manifest.json` records hashes, cases, the proposed ioctl and limitations.

## Proposed opt-in ioctl (design, not implemented)

- Command `0x4008f004`, 84-byte write struct: `frame_size`, `phys_addr`, `slot`, `prefix_len`, `prefix[64]`, `reserved`.
- Handler copies the struct from user, calls `a6400_uvc_producer_submit()` with:
  - `slot_capacity` = half of the owned DMA window;
  - the owned destination window `{g_dma_phys, A6400_UVC_DMA_SIZE}`;
  - the module's two-slot state and the module-constant expected dimensions (1280×720; not user-supplied).
- The handler returns the admitted slot or `-EINVAL`; it does **not** call the driver Update. Update/ENABLE/WAIT stay rejected, and the module remains enumeration-only. The future Update/WAIT completion path calls `release()`.
- The whole branch is behind the `A6400_UVC_PRODUCER_ADMISSION` compile flag; no existing module build changes in this step.

## Boundary

The state machine is a contract, not a driver submission: it does not map the source, read the prefix from camera memory, call Update, wait on DMA completion or prove a sensor frame. The proposed ioctl is a design and has not been added to the shim or built into a module.

## Next

P3c: implement the ioctl handler and build flag with ARM audit, keeping Update/ENABLE/WAIT rejected; or P0 (PC Remote reboot isolation) before any physical teardown rerun.
