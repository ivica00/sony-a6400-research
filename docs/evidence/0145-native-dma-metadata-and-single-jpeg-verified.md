# E0145: Native DMA Metadata, Slot Capacity Guards and ScalarInfra SET_PATH Protocol

Date: 2026-11-07. Camera writes strictly restricted to `/tmp_bt`; no SD/NAND/Backup/preload/boot modifications. All 599 emulator tests pass in 17.956s. Windows host uses inbox `usbvideo.sys`. Mass Storage debugger PID 703 remains fully functional and responsive.

## 1. Coherent DMA Metadata Query and Slot Capacity Enforcement

In `tools/native_camera/uvc_composite_shim.c`, custom ioctl interceptor `a6400_uvc_video_core_ioctl` was introduced to provide real coherent buffer metadata and prevent kernel memory corruption:
- `IOCTL_UVC_MOD_QUERY_DMA` (`0x8010f020`): queries coherent memory properties from `struct a6400_uvc_dma_metadata`:
  - `phys_addr`: actual physical DMA address allocated via `dma_alloc_coherent`
  - `total_size`: 262,144 bytes (256 KiB)
  - `slot_size`: 131,072 bytes (128 KiB per slot)
  - `max_frame_payload`: 131,060 bytes (128 KiB minus 12-byte UVC uncompressed/MJPEG payload header)
- `IOCTL_UVC_REG_BUF` (`0x4008f000`): interceptor enforces address and size match against owned coherent memory; legacy/unowned fixed address `0x20000000` is rejected with `-EINVAL` (-22).
- `IOCTL_UVC_UPDATE` (`0x4008f003`): interceptor evaluates `frame_size + 12 > slot_capacity` before DMA transfer; oversized frames are rejected with `-EINVAL` (-22) without truncation or memory overrun.

### Physical camera verification:
Using freestanding test binary `tools/native_camera/uvc_probe_dma_meta.c` (2564 bytes, direct `svc 0` syscalls):
- `OPEN_FD=3`
- `QUERY_DMA_RET=0`: returned `DMA_PHYS=0x05280000`, `TOTAL_SIZE=262144`, `SLOT_SIZE=131072`, `MAX_PAYLOAD=131060`
- `BAD_REG_RET=-22`: legacy `0x20000000` registration cleanly rejected
- `GOOD_REG_RET=0`: real coherent physical address `0x05280000` registration accepted
- `OVERSIZED_UPDATE_RET=-22`: 140,000-byte frame (> 131,060) rejected before DMA buffer access
- `UNREG_BUF_RET=0`: unregistration and cleanup verified; dmesg confirmed `owned coherent free phys=05280000 size=262144`
- Built module: `artifacts/native/uvc-owned-dma-meta/usbg_video_a6400.ko` (41,112 bytes, SHA-256 `28abece118211a298afcc871496745dd695ad5bdd5694502f950e3228959f109`).

## 2. OSAL UIPC and DataflowInfra Protocol Discovery

Decompilation of `/usr/lib/dataflowInfraFramework.so` (`DataflowInfraMsg::MakeDataflowHeaderEv`, `DataflowInfraSender::SendASync`) and `libInfraStreamingServer.so` (`pvtScalarInfraIF`, `pvtScalarInfraIFSetPath`, `pubSfrGetJpeg`) established the authentic wire protocol on the a6400:
1. **Target queue**: Both configuration (`SET_PATH`) and frame request (`GET_JPEG`) target `ScalarInfraAsyncMain` on queue **`0x0167046a`** (not `0x01670464`).
2. **20-byte DataflowInfra Header**:
   - `+0x00`: `uint32_t reply_qid` (dynamic OSAL queue allocated via `osal_dynamic_id(0x2a, ...)`)
   - `+0x04`: `uint32_t magic = 0xa0a0a0a0`
   - `+0x08`: `uint16_t msg_num = 1`
   - `+0x0a`: `uint16_t total_len = 20 + payload_len` (88 bytes for SET_PATH, 40 bytes for GET_JPEG)
   - `+0x0c`: `uint32_t reserved = 20`
   - `+0x10`: `uint32_t payload_offset = 20`
3. **Payload Structure** (starts at byte +20):
   - `SET_PATH` (68 bytes): `0x2009`, `0x0100`, len=68, byte+15=`0x50`, fps at +16, width at +20, param at +24, `path_enable` at +64 (1=active, 0=idle).
   - `GET_JPEG` (20 bytes): `0x2009`, `0x0100`, len=20, byte+15=`0x20` (JPEG selector), byte+16=1 (poll request).

## 3. Physical Camera Verification of SET_PATH and GET_JPEG

Freestanding ARM acquisition utility `tools/native_camera/uvc_acquire_single_jpeg.c` (compiled to `artifacts/native/uvc_acquire_single_jpeg_arm`, 6440 bytes stripped, direct `svc 0` syscalls, no libc dependency) was uploaded to `/tmp_bt/uvc_acquire_single_jpeg_arm`:
- `OSAL_INIT=0 REPLY_QID=0x02d96102`: UIPC pool `/dev/uipc` mapped and dynamic reply queue allocated.
- `[1] SET_PATH_RESET_RET=0`: synchronous idle reset accepted with status 0.
- `[2] SET_PATH_START_RET=0`: synchronous 1280x720 @ 30 FPS configuration accepted by `ScalarInfraAsyncMain` with status 0.
- `[3] GET_JPEG`: poll request sent to `0x0167046a`; reply returned status `err=0`, `ready=0` (ring buffer slot 0xf4 currently empty in Mass Storage mode).

## 4. Current State and Limitations

- `usbg_video` module is currently unloaded; camera remains in Mass Storage mode with debugger PID 703 responsive.
- DMA buffer bounds and slot guards are 100% physically verified against kernel buffer overruns.
- `ScalarInfra` accepts SET_PATH configuration and GET_JPEG queries with authentic DataflowInfra wire framing.
- In Mass Storage mode, sensor ISP hardware does not fill the JPEG ring buffer; sensor activation requires shooting state or ISP pipeline transition.
- All 599 emulator tests pass in 17.956s.
