# Emulator Enhancement Plan for GUI, Menu, and Touch Modes

> Status 2026-11-06: the plan below is a historical working document. The actual main
> menu is `PAS_MenuListTab`, not the previously assumed `PAS_MenuSelectMode`.
> The `MonDrv` queue created during checkpoint restoration is not proven to be original initialization
> and remains an open irregularity. The UIPC size boundary applies to a specific
> verified call, not as a universal rule for every message. Current results
> and limitations are documented in E0106–E0109; main menu touch does not work yet.

## 1. Goal and Context
The goal is to advance the Sony ILCE-6400 camera emulator to the point where the firmware modules responsible for the graphical interface (`libObj.so`, `viewUnified2.so`), menu hierarchy (`PAS_MenuSelectMode`, `GEN_GridList`), and touch input (`ux::wgtsys::WidgetSystem`, `InputService`, `InfraTp`) can execute and be tested authentically inside the emulator without needing immediate flashing/testing on the physical camera.

All contracts and mechanisms are based on the mathematically and telemetry-verified state of a real camera (Sony ILCE-6400, FW 2.00, Serial No. 03925553) connected via the Native Root USB Debugger (`docs/NATIVE_USB_DEBUGGER.md`).

---

## 2. Architectural Analysis and Discovered Contracts

### 2.1. Authentic 12-byte OSAL UIPC Header (`osal_uipc.ko` / `libosal_uipc.so`)
- The user `msg_ptr` returned by `osal_valloc_msg_wait` has the memory layout:
  - `msg_ptr - 12` (`raw + 0`): link/pool descriptor (4 bytes)
  - `msg_ptr - 8` (`raw + 4`): `num_blocks` (1 byte):
    - `0` if requested size `<= 20` bytes (then `osal_msg_size` returns exactly 20)
    - `((size + 43) & ~31) >> 5` if requested size `> 20` bytes (then `osal_msg_size` returns `(num_blocks * 32) - 12`)
  - `msg_ptr - 7` (`raw + 5`): flags / status (1 byte, initially 1)
  - `msg_ptr - 6` (`raw + 6`): uint16 `ref_count` (2 bytes, initially 1, atomically decremented in `osal_free_msg`)
  - `msg_ptr - 4` (`raw + 8`): magic value / sender queue (`0xa5a5a5a5` or queue ID)
  - `msg_ptr + 0` (`raw + 12`): user payload pointer
- `libInfraMediaDetect.so` at address `0xcd10` explicitly checks:
  ```arm
  blx osal_msg_size
  cmp r0, #0x17
  bls error  ; if size <= 23 bytes, rejects the message!
  ```
  Therefore every UIPC message must have `num_blocks >= 2` (raw size >= 64 bytes).

### 2.2. Cause of `SIGFPE` (division by zero) in `MonQueue::EnQueue` (`libMWF.so`)
- `THREAD_INFRA1` (TID 1004) during initialization calls `MonCtrl::ConPutMessage` -> `MonDrv::PutcharSub`.
- `MonDrv::PutcharSub` dereferences `MonDrv::mp_output` (GOT offset `0xc88`).
- In the emulator, `MonDrv::mp_output` was NULL (`0x0`). Due to `null_page_policy='read-zero'`, `MonQueue::IsFull(0)` returned 0 (not full), and then `MonQueue::EnQueue(0, ch)` executed:
  ```arm
  ldr r1, [r3, #0xc]  ; r1 = capacity (reads [0 + 0xc] = 0)
  ldr r0, [r4]        ; r0 = write_idx (0)
  adds r0, #1
  blx __aeabi_uidivmod ; divides (write_idx + 1) / capacity -> 1 / 0!
  ```
  Division by zero raised `SIGFPE` (signal 8) via `sys_tgkill(1000, 1004, 8)`.
- Telemetry from the real camera (`camera_debugger.py` mem dump):
  - `MonDrv::mp_output` on the live camera points to a valid object `0x000218e8`:
    - `read_idx_ptr = 0x0450e408`
    - `write_idx_ptr = 0x0450e40c`
    - `buf_ptr = 0x0450e810`
    - `capacity = 0x00007bf0` (31,728 bytes)
  - The object is mapped from `/dev/mem` at physical address `0x20098000` (WBI log buffer from `backup.ko` items `0x00fa0028` and `0x00fa005d`).

---

## 3. Phased Action Plan

### Phase 1: Hardening Contracts in the Emulator Core
1. **Updating `GuestUipc` (`src/a6400/execution/guest_uipc.py`)**:
   - Implement the authentic 12-byte OSAL header format in `handle_valloc_msg_wait` and `allocate_message`.
   - Store `num_blocks` at `raw + 4` (`msg_ptr - 8`), `ref_count = 1` at `raw + 6`, and marker `0xa5a5a5a5` at `raw + 8`.
   - Update `tests/test_guest_uipc.py` and ensure all unit tests pass.
2. **Initializing `MonDrv::mp_output` / WBI Buffer**:
   - During emulator load or setup, allocate/bind an authentic `MonQueue` object with capacity `0x7bf0` to the `MonDrv::mp_output` pointer in `libMWF.so`.
   - This completely eliminates logging subsystem crashes (`SIGFPE`) during the boot sequence of any thread.

### Phase 2: Advancing Threads to Join
1. **Executing TID 1004 (`THREAD_INFRA1`) and TID 1039 (`IMD-RM`)**:
   - Allow TID 1004 to process the media reply and complete registration.
   - Connect the `THREAD_INFRA0` (TID 1001) synchronization pipeline (`thread_1008` render signal on condvar `0x000284b0`).
2. **Saving a Stable Checkpoint**:
   - Create checkpoint `artifacts/checkpoints/boot-infra-ready.ckpt`.

### Phase 3: Instantiating the `WidgetSystem` Singleton and `viewUnified2.so`
1. **Advancing the main thread (`im.elf`)**:
   - After infra threads signal readiness, the `main` thread continues execution toward instantiating the GUI singleton.
   - Verify existence of `ux::wgtsys::WidgetSystem` at `libObj.so` address `0x07108058` -> `0x000956f0`.
   - Verify the layer table (8 layers) and mouse state at `+0x4a8` / `+0x4b0`.
2. **Loading the menu tree**:
   - Execute entry points in `viewUnified2.so` (`PAS_MenuSelectMode`).
   - Create checkpoint `artifacts/checkpoints/boot-gui-ready.ckpt`.

### Phase 4: Touch Injection and Interactive Tests
1. **Modeling touch input**:
   - Connect the virtual touch interface to `WidgetSystem` fields for coordinates and press state.
   - Simulate touches on MENU items and switching categories via wheel/touch.
2. **Visual verification**:
   - Render real frames via `CameraGuiWindow` and `DmpPicaRasterizer` decoding authentic PICA200 GPU packets.
   - Confirm mode behavior in a pure software environment before testing on the physical camera.
