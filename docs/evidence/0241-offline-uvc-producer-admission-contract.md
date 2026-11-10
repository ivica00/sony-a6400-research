# E0241 — Offline UVC producer admission contract

Date: 2026-11-09. Offline only: no camera access, no module load, no UVC activation, no DMA. This is step P3 of the UVC/PTP critical path.

## Purpose

Define a pure admission gate that a bounded sensor producer must pass before the driver's `IOCTL_UVC_UPDATE`: the frame must fit the destination slot, be disjoint from the owned DMA window, target a free slot, and declare the expected decoded dimensions. It complements the bounds already in the shim and the E0239 JPEG SOF parser.

## Implementation

- `tools/native_camera/uvc_producer_admission.c/.h`: `a6400_uvc_producer_admit()`.
- Inputs: `frame {frame_size, phys_addr, slot, prefix, prefix_len}`, caller slot capacity, the owned destination window `{phys, size}`, a two-slot state `{ready, last_len}`, and expected width/height. `prefix` is a caller-read bounded JPEG prefix (SOI through SOF); the contract never dereferences beyond `prefix_len`.
- Checks: valid pointers and slot 0/1; non-zero size/address; `frame_size + 12 <= slot_capacity`; 32-bit source and destination window non-wrap; source span disjoint from the destination window; slot `ready` (no busy wait — not ready is a rejection); E0239 parser success; decoded dimensions equal the expected UVC dimensions.
- On success it returns the slot index and atomically sets that slot `ready=0` and `last_len=frame_size`. On any rejection it returns `-1` and leaves both slots untouched.

## Checks

- 16 host cases pass (`artifacts/native/uvc-producer-admission-e0241/producer-admission-check.log`): valid slot 0/1 with only the selected slot consumed; maximum payload accepted; one byte over rejected; not-ready rejected without state change; invalid slot/size/address; source 32-bit wrap; source alias from below/inside/above; disjoint neighbours accepted; destination-window wrap; short/null/malformed prefixes; dimension mismatch (1024×680 against 1280×720) rejected and a matching 1024×680 frame accepted; zero expected dimensions rejected.
- ARM compile of the contract succeeds; manifest `artifacts/native/uvc-producer-admission-e0241/manifest.json` records source/executable/object hashes and limitations.

## Boundary

The module does **not** call this contract yet. The current `IOCTL_UVC_UPDATE` ABI is `{frame_size, phys_addr}`, the module is enumeration-only, and a kernel-side caller would need a safe mapped prefix, a selected destination slot and DMA-completion WAIT state. Sensor-source mapping, DMM lifetime, cache coherency, DMA completion and the actual Update call remain open. The expected UVC dimensions are 1280×720 per the committed descriptors; the demonstrated PTP liveview JPEG is 1024×680 and is used here only as a mismatch case.

## Next

P3b: define the producer submission path (ioctl/struct, slot selection, bounded prefix read, WAIT handshake) and wire admission + Update behind an opt-in compile flag with ARM audit. P0 (PC Remote reboot isolation) still gates P4 physical teardown reruns.
