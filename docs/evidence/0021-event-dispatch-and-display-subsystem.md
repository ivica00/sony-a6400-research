# Evidence Record 0021: Event Dispatch and Display Subsystem Discovery

## Context and Goal

Evidence Record 0020 established the continuous 1 Hz heartbeat event loop of `im.elf` (Task 94) over 8.77 million instructions and 17,000+ cycles. The objective of this milestone is Package G: analyzing Task 94 event callback `0x9a5c`, identifying the boot event sequence and plugin architecture in `libIMDB.so`, validating authentic event stimulus injection on queue `0x0094016a`, and discovering the display/framebuffer subsystem (`/dev/fb0`, `libObj.so`).

## Findings

### 1. Task 94 Event Callback (`0x9a5c`) Architecture
Disassembly of `im.elf` function `0x9a5c` revealed the exact message handling contract for Task 94:
- Receives `r0 = msg_ptr` allocated in the UIPC shared pool.
- Reads `event_id = [msg_ptr]` and dispatches to specific handlers:
  - `0x00940031`: Camera initialization Phase 1 (`0xb694(0, 1, 1)`).
  - `0x00940032`: Camera initialization Phase 2 (`0xb694(0, 1, 0)` then `0xb694(0, 2, 1)`).
  - `0x00940033` through `0x00940037`: Initialization Phases 3 through 8.
  - `0x00920152`: Power-on / boot state notification from Task 92 (triggers synchronous query `0x00920111` to `0x00924127`, sets boot mode at `0x14ed4`, executes `sen.elf &`, and initiates plugin initialization via `0xae8c`).
  - `0x00940001`: Registers callback `0x9a5d` at `[0x14ee4]` via `0xaaf4`.

### 2. Initialization Manager Database (`libIMDB.so`)
Inspection of `.data.rel.ro` in `dev/nflasha15_unpacked/lib/libIMDB.so` uncovered 198 structured records (44 bytes each):
- Kernel modules: `/kmod/dmm.ko`, `/kmod/upm.ko`, `/kmod/stream.ko`, `/kmod/ms_drv.ko`, `/kmod/mmc_drv.ko`.
- Userland daemons: `/usr/bin/qsi.elf`, `sen.elf &`, `/usr/bin/network.sh`.
- Subsystem shared libraries initialized during Phase 1 (`0x00940031`):
  - `libDpro_EVF.so`: `evf_init` (Electronic Viewfinder).
  - `libBizInitializer.so`: `BIZ_Init` (Business Logic Initializer).
  - `appFw.so`: `Application_System_Init` (Application Framework).
  - `gui.so`: `DPro_App_UI_init` (GUI System).

### 3. Display and Framebuffer Character Device Discovery
Analysis of string literals and symbol tables revealed the display stack:
- `/dev/fb0` (major 29, minor 0): the primary Linux framebuffer device opened by `/usr/lib/libObj.so`.
- `/dev/dmac`: DMA controller character device accessed by `libmpr.so` (`MprIf::DrawPixels`).
- `libObj.so` houses the core camera windowing and rendering engine (`ux::wgtsys`):
  - `ux::wgtsys::WidgetSystem::createLayer`
  - `ux::wgtsys::Layer::setActive`, `setClear`
  - `ux::gfxeng::TextSprite::drawText`
  - `GRM_fbrmInitializeYUV`, `GRM_fbrmUpdateYUV`, `GRM_fbrmRectblitYUV`, `GRM_fbrmFillrectYUV`
  - `ObjDisplay_Create`, `ObjDisplay_Init`, `ObjDisplay_Start`, `ObjDisplay_Destroy`

### 4. UIPC Message Receive ABI Alignment
In `libosal_uipc.so`, `u_osal_rcv_msg_tmo` passes a 16-byte parameter block to `ioctl(fd, 0x80000007)`:
`{ uint32_t queue, uint32_t *p_out_msg, uint32_t out_msg, uint32_t timeout }`.
Previously, `handle_rcv_msg_tmo` wrote the returned message pointer to `p_out_msg` (local stack frame pointer) rather than `out_msg` (the caller's destination pointer). Aligning `handle_rcv_msg_tmo` to write directly to `out_msg` when nonzero resolved the ABI mismatch.

### 5. Verified Event Stimulus Execution
Injecting authentic Event `0x00940031` (Phase 1) into queue `0x0094016a`:
- `im.elf` received the message pointer and invoked callback `0x9a5c(0x503309c0)`.
- Callback logged `94 B  Ib 094_0` (Begin Phase 1) via synchronous UIPC messaging.
- Executed `0xb694(0, 1, 1)` iterating through `libIMDB.so` phase entries.
- Logged `94 E  Ib 094_0` (End Phase 1).
- Returned cleanly to `0xa364` where `im.elf` freed the message buffer via `osal_free_msg`.
- Returned to the main event loop, servicing subsequent `rcv_msg_tmo` calls and continuing the 1 Hz nanosleep heartbeat.

## Verification

- `tests/test_guest_uipc.py`: added `test_message_queue_receive_with_out_msg_dest` and `test_message_queue_allocate_and_enqueue_helpers`.
- Full regression suite: **195 passing tests** (100% pass rate, 0 failures).
- All 10 historical baselines maintained strictly intact.
