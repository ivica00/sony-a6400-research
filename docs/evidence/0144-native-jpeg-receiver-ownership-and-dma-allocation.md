# E0144: Native JPEG receiver, ownership and real DMA allocation

Date: 2026-11-07. Camera payload/log writes only in `/tmp_bt`; no SD/NAND/backup/preload/boot changes. No JPEG configuration, GET_JPEG request, sensor activation or application hook was issued. E0143 remains static-pattern transport evidence, not sensor LiveView.

## Source-checked native receiver

Current retained camera LIRO image: `artifacts/hardware/av-cam-camera-original.bin`, 16,803,048 bytes, SHA-256 `dd8f8d0cc74ad4b70100e5728cf8b159b5155e7fb50eaf1147b99c9054740209`, ORIL linked base `0x635c6000`. It differs from the packaged image (`90d515cf...`); no guessed address delta was used.

Thumb PIC references identify ScalarInfraAsyncMain and scalar JPEG handling. Physical `/dev/mem` reads matched original bytes for receiver `0x63a90c38` (1280 bytes), strings `0x63f77958` (256), queue-related static table `0x63e43400` (256), and helpers `0x63d94894` (256). Receives explicitly target `0x0167046a`. Original dispatch covers GET_INFO, SET_PATH open/close, GET_JPEG and other operations.

GET_JPEG predicate `0x63d9521e` requires halfword+2=`0x0100`, byte+0xf=`0x20`; GET_INFO uses byte+0xf=`0x10`. Internal asynchronous SET_PATH OPEN uses halfword+2=`0x8120`, with the JPEG selector at +0xc equal to 0x30/0x31. This differs from the reference external request to `0x01670464`. The synchronous external-to-internal conversion is not yet fully verified.

## Proc streaming and current state

`/proc/osal/uipc` is multi-stage: reopening and byte-seeking does not collect all stages. The initial direct 3609-byte debugger read was incomplete. Streaming it into `/tmp_bt`, then reading that regular file, preserved 43,289 bytes, including queues 0x464/0x46a. Statistics do not identify their waiting thread owners. Maps/thread reports were preserved; `libInfraStreamingServer.so` remains absent. Stack/syscall proc probes returned ENOENT.

JPEG object slot `0x645c629c` currently points to `0x643c3708`. Its stage pointer equals idle-stage slot value `0x643c3ad0`. A non-frozen 512-byte snapshot contains twelve 12-byte entries at +0xf4, all state1/handleFFFF/size0. This is not an atomic lifetime epoch.

## Original ownership contract

Helper `0x63d948ca` searches exactly twelve entries. Mode1 selects newest by 24-bit age with wrap handling; mode2 selects oldest. Handler `0x63a91a3c` takes READY/state3 handles, reports `(size+127)>>7`, and returns an additional `0x274` field whose DMM meaning must not be guessed. Detach `0x63d948b0` invokes clear `0x63d94894`: state1, handleFFFF, size0, ageFFFFFFFF. The handler frees remaining unreturned READY buffers through original DMM calls. GET_JPEG therefore transfers ownership.

`tools.research.scalar_jpeg_buffer_probe` executes original helpers on the captured negative state and explicit positive fixtures: **10 controls pass**, covering selection, age wrap, detach and duplicate-detach rejection. These fixtures are not camera frames; no DMM/encoder/DMA success is synthesized.

Original JPEG OPEN `0x63a918c0` retries DMM UnitType `0x276` with two-second sleeps and potentially very long retry loops. Resource preflight and rollback are required before issuing it. Decompilation of the preparation helper reported bad-instruction/PIC warnings and is **not accepted as dimension or encoder-limit evidence**.

## Allocation ABI correction and default policy

Reference `usb_sync_alloc_phys_buffer(task, 0x50e, ...)` takes a **DMM UnitType**, not 1294 KB. The earlier shim independently returned a fixed 1294*1024-byte window. E0140/E0141 observed that shim, not native ownership/allocation of a 1294 KB request.

Original helper sends DMM operation1 with UnitType at packet+4. Physical test replied status `0xfffd` (-3), handleFFFF, no memory; open returned -ENOMEM. Original a6400 `dmm_unit_ctrl_Alloc` returns -3 when the type is absent from the configured table or has no definition. This path does not establish ordinary pool exhaustion.

Added explicit native DMM build and diagnostic wrappers preserving full logical queue IDs/results. **Default builds now retain original DMM allocation**, exposing the absent-type failure. The historical fixed window requires `--experimental-fixed-buffer`; it is not silently selected.

## Real kernel-owned DMA lifecycle

Separate `--coherent-buffer-allocation` MOD policy calls native `dma_alloc_coherent`/`dma_free_coherent`. Original kernel instructions verify NULL-device support. Only this allocation's physical-to-CPU conversion is redirected to its actual coherent CPU pointer. Handle1 is private MOD bookkeeping, not a fabricated DMM handle.

The 1,325,056-byte attempt failed order9 allocation. Buddy reports had no 2 MB contiguous blocks. 512 KiB succeeded twice with matched frees and failed other attempts as fragmentation increased. These failures remain failures.

The final **256 KiB lifecycle-only** build completed three consecutive physical open/close cycles, each open=3/close=0, CPU mapping `ffd80000`, with respective physical addresses `00780000`, `007c0000`, `05280000`. All three had matching native frees. Varying addresses establish this is not a fixed RAM window.

No stream was attempted with this allocator. Actual address/capacity metadata and per-slot bounds must be implemented first. Never run the old fixed-PA feeder against it. 256 KiB is not proof of capacity for arbitrary 720p JPEGs.

Physical artifact: `artifacts/native/uvc-owned-dma-256k-e0144/usbg_video_a6400.ko`, 40,196 bytes, SHA-256 `c9bbb01584874aa76ddce18dfa704d8bbced64a3b573e75806c9cc52efd0de45`; 44 native imports verified and original executable prefixes unchanged. Default DMM artifact: `artifacts/native/uvc-safe-default-e0144/usbg_video_a6400.ko`, SHA-256 `79329a7414fb6036a7cb1bdd9f8c573b4f2e35259c1dcf7e19e1e8641a7e4ec5`; its absent-type failure is not a working stream.

## Static views, evidence and checks

`oril_scalar_elf_view` creates selected byte-preserving sections at original addresses, with explicitly inferred Thumb entry annotations. It is not runnable camera firmware. `rea_oril_scalar_batch` validates source/view hashes and each section's bytes/address before using existing REA/WSL. Original firmware inputs and the firmware-only launcher guard remain unchanged.

Reports: `artifacts/tools/rea/{uvc-jpeg-routing-e0144,uvc-osal-queue-contract-e0144,oril-scalar-receiver-e0144,oril-jpeg-ownership-e0144-v2,oril-jpeg-open-close-e0144,oril-jpeg-dimensions-e0144,uvc-native-allocation-e0144,uvc-dmm-allocation-status-e0144}`. Earlier `oril-jpeg-ownership-e0144` failed on an unannotated indirect target; retained partial results are not a completed batch. Preparation-helper decompiler warnings remain explicit.

Physical data: `artifacts/hardware/uvc-native-source-e0144`. All **599 tests pass in 14.500 seconds**, recorded in `emulator-tests-final.log`; 53 existing ARM bridge controls and 10 new original JPEG queue controls pass.

## Final state and next boundary

Experimental module unloaded; no active UVC session, sensor configuration, observer or hook. Mass Storage debugger PID703 responsive. No user battery action required.

Next add explicit MOD metadata and per-slot size checks for owned DMA memory; finish synchronous SET_PATH conversion, dimension/capacity requirements and DMM handle open/close/free semantics. Then acquire one native JPEG with full cleanup before continuous sensor UVC. An unowned fixed-address test is not a substitute for these contracts.
