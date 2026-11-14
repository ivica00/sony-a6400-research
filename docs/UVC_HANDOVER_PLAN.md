# Sony ILCE-6400: Continuing the Native JPEG → UVC Stream

## Goal and Constraints

Connect original sensor frames to the already-confirmed UVC Bulk IN transport for CinemaHUD: MJPEG 1280×720 at 30 FPS.

- Communicate exclusively in English.
- Restrict all camera writes and payloads to RAM `/tmp_bt`. No SD/NAND/Backup/preload/boot modifications.
- Keep Microsoft inbox `usbvideo.sys`; no Windows driver replacement.
- Preserve all 599 emulator tests. Do not spawn subagents unless explicitly requested.
- Do not present a test image, passing tests, or static analysis as sensor output.

## Required Reading

1. `AGENTS.MD` — the latest E0144 record takes precedence over historical states.
2. `docs/evidence/0144-native-jpeg-receiver-ownership-and-dma-allocation.md`.
3. `docs/evidence/0143-uvc-720p-test-transport-and-30fps-verified.md`.
4. For reference producer and earlier boundaries: E0134 and E0133.

## Last Verified Physical State

- Mass Storage debugger PID703 available; re-check state first.
- Experimental UVC module **removed**, no active UVC session, observer, or hook.
- No preventive camera restart needed.
- No JPEG configuration messages or GET_JPEG sent; real sensor frame not yet retrieved.
- Final tests: 599/599, 14.500 s; 53 ARM bridge controls and 10 original JPEG queue controls pass.

## What Already Works

E0143 confirms PnP without Code10, Bulk IN endpoint 0x81, execution of the original START callback, decoded 1280×720 MJPEG frame, and 180 received frames at 29.9592 FPS. CinemaHUD HTTP monitor accepted the stream. The source was a **static test JPEG image**; the test server has been stopped.

A6400 START already sends `(speed, count, array)`. Endpoint count is only the low byte of r2; upper bytes are not the count. The module expects gadgetcore's wrapper, whose +0x24 points to the raw endpoint from `*(dwc+0xdc)`. Do not replace the wrapper with a raw pointer. The bridge validates Bulk IN 0x81 and monitors the interface for STOP.

## Key Memory Correction

Reference argument `0x50e` is **DMM UnitType**, not 1294 KB. A6400 original DMM reply is -3/handleFFFF: type is not defined. The historical fixed window at PA20000000 is not proof of ownership or original allocation.

`build_uvc_composite_module` now retains the original DMM allocator and visible rejection by default. The fixed window is available only with `--experimental-fixed-buffer`; do not use it to continue the original stream.

Separate MOD policy `--coherent-buffer-allocation` uses the real kernel `dma_alloc_coherent`/`dma_free_coherent` and proper mapping of the returned CPU pointer. A final 256 KiB passed three physical open/close cycles with distinct PAs and confirmed release. Larger requests hit fragmentation. This is **only a lifecycle check**, without streaming and without proof of sufficient capacity for arbitrary 720p JPEG frames.

**Do not run the old feeder with fixed addresses against this allocator.** First add a query for actual address/capacity and size checks for each destination slot.

## Original JPEG Receiver

Use the current camera image:

`artifacts/hardware/av-cam-camera-original.bin`

SHA-256: `dd8f8d0cc74ad4b70100e5728cf8b159b5155e7fb50eaf1147b99c9054740209`, ORIL base `0x635c6000`. Differs from the packaged firmware; do not transfer addresses by assumed offset.

- `ScalarInfraAsyncMain` at `0x63a90c38` receives at `0x0167046a`; code and relevant data match the physical camera.
- External SET_PATH goes to `0x01670464`; its synchronous conversion into an internal message still needs to be completed. Internal OPEN uses halfword+2=0x8120 and JPEG selector +0xc=0x30/0x31. Not the same message as the external request.
- GET_JPEG predicate: halfword+2=0x0100, byte+0xf=0x20. GET_INFO uses byte+0xf=0x10.
- GET_JPEG handler `0x63a91a3c` acquires READY handles, selects the newest frame by 24-bit counter, and frees remaining old frames. Retrieval transfers ownership.
- JPEG object: slot `0x645c629c` → last observed `0x643c3708`; queue of 12×12 bytes at +0xf4. Last unfrozen capture: all EMPTY/state1, handleFFFF, size0; stage points to idle `0x643c3ad0`. Re-verify before use.
- Reply contains size rounded to 128-byte units and additional field 0x274. DMM meaning of that field still needs confirmation.
- Original JPEG OPEN `0x63a918c0` attempts to allocate DMM type0x276 with retries and two-second waits that can take a very long time. Do not call without checking resources and rollback procedure.
- Decompilation of the preparation helper has bad-instruction/PIC warnings: **not proof of accepted dimensions or encoder limits**.
- `libInfraStreamingServer.so` is not loaded in the latest PID149 maps; do not use historical RAM addresses of that service.

## Recommended Continuation Order

1. Check debugger and module state; save new observations separately from E0144.
2. Implement an explicit MOD query for actual DMA capacity/addresses. Add per-slot checks, including the 12-byte UVC header. Reject oversized frames before DMA access; do not truncate or fabricate success.
3. Complete the external/synchronous SET_PATH receiver, dimension fields, and capacity fields from original instructions. Check resources for type0x276 and rollback to prior state before physical OPEN.
4. Complete DMM open, physical address/capacity, close, and release of all returned handles per the original sequence. Also verify error/timeout paths.
5. Retrieve **one** original JPEG with full cleanup. Verify SOI/EOI, SOF dimensions, and actual length within confirmed capacity. No continuous stream until this cycle is verified.
6. Connect producer to UVC: `WaitVideoReadCmp` before `UpdateVideoBufEvt`, separated source/destination, absolute monotonic deadlines. Re-measure FPS and frame content changes of real frames; the previous 29.96 FPS applies only to the test image.
7. Verify CinemaHUD and clean STOP/return to Mass Storage; save evidence and run all 599 tests.

## Tools and Artifacts

- `tools/research/oril_scalar_elf_view.py`: byte-preserving ELF view of selected ORIL regions for analysis; not a camera executable payload.
- `tools/research/rea_oril_scalar_batch.py`: verifies provenance, hashes, and section bytes before REA/WSL analysis. Standard firmware-only launcher is not weakened.
- `tools/research/scalar_jpeg_buffer_probe.py`: 10 controls of original Thumb helpers; positive states are explicit fixtures.
- `artifacts/hardware/uvc-native-source-e0144/`: physical captures, OSAL/DMM reports, logs, and manifest.
- `artifacts/tools/rea/oril-*e0144*`: receiver and ownership analyses. Preserved failed batch is not completed proof.
- Physically tested DMA module: `artifacts/native/uvc-owned-dma-256k-e0144/usbg_video_a6400.ko`, 40196 bytes, SHA-256 `c9bbb01584874aa76ddce18dfa704d8bbced64a3b573e75806c9cc52efd0de45`.

`/proc/osal/uipc` must be read in the same open stream, e.g., `cat` into `/tmp_bt`, then fetch the regular file. Re-opening with a byte-offset skips its internal phases.

## Basic Commands

```powershell
py -3.12 tools/camera_debugger.py info
py -3.12 -m unittest discover -s tests
py -3.12 -m tools.research.scalar_jpeg_buffer_probe
py -3.12 -m tools.research.build_uvc_composite_module --output-dir artifacts/native/NEW-NAME --coherent-buffer-allocation
```

The last command only builds the module. It does not imply verified streaming, capacity, or approval for old fixed feeder addresses. Continue within the already-authorized RAM scope, without routine confirmations and without claims exceeding evidence.
