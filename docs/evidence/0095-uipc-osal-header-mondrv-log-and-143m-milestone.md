# Evidence 0095: Authentic UIPC OSAL Header, MonDrv WBI Log Buffer, and 143.74M Instruction Milestone

## 1. Context & Objective
Advance the Sony ILCE-6400 execution environment toward running GUI, menu (`viewUnified2.so`), and touch (`WidgetSystem` / `InputService` / `InfraTp`) modes. Previous execution from `boot-125m.ckpt` reached `SIGFPE` (`sys_tgkill(1000, 1004, 8)`) when `THREAD_INFRA1` (TID 1004) performed debug logging during `libInfraMediaDetect.so` initialization.

## 2. Reverse Engineering Findings & Ground Truth Verifications

### 2.1. Authentic 12-byte OSAL UIPC Header (`osal_uipc.ko` / `libosal_uipc.so`)
- Disassembly of `__k_4u_valloc_msg_wait` (0x10e8), `osal_valloc_msg_wait` (0x36e4), and `osal_msg_size` (0x4780 in `osal_uipc.ko` and 0x4b80 in `libosal_uipc.so`) revealed the exact OSAL message layout:
  - `msg_ptr - 12` (`raw + 0`): link/pool descriptor (4 bytes)
  - `msg_ptr - 8` (`raw + 4`): `num_blocks` (1 byte). If `req_size <= 20`, `num_blocks = 0` (returns 20). If `req_size > 20`, `alloc_size = (req_size + 43) & ~31`, `num_blocks = alloc_size >> 5` (returns `(num_blocks * 32) - 12`).
  - `msg_ptr - 7` (`raw + 5`): flags (1 byte, 1)
  - `msg_ptr - 6` (`raw + 6`): uint16 `ref_count` (2 bytes, 1, decremented by `osal_free_msg`)
  - `msg_ptr - 4` (`raw + 8`): magic marker `0xa5a5a5a5` / queue ID (4 bytes)
  - `msg_ptr + 0` (`raw + 12`): user payload pointer returned to caller.
- `libInfraMediaDetect.so` at `0xcd10` requires `osal_msg_size >= 24`. With authentic `num_blocks = 2`, `osal_msg_size` evaluates to 52, satisfying the boundary condition.

### 2.2. Root Cause of `SIGFPE` (division by zero) in `MonQueue::EnQueue` (`libMWF.so`)
- In `libMWF.so`, `MonCtrl::ConPutMessage` invokes `MonDrv::PutcharSub` (0x25250), which dereferences global pointer `MonDrv::mp_output` at GOT offset `0xc88`.
- In the emulator, `MonDrv::mp_output` was `NULL` (0x0). `MonQueue::IsFull(0)` evaluated to false (not full). Next, `MonQueue::EnQueue(0, ch)` attempted to compute `(write_idx + 1) % capacity`. Because capacity at `[0 + 0xc]` read 0 under `null_page_policy='read-zero'`, `__aeabi_uidivmod` triggered integer division by zero, raising `SIGFPE`.
- Live hardware telemetry (`tools/camera_debugger.py` `mem 149 0x04138fe0 16` and `0x000218e8 16` on Sony ILCE-6400 Serial 03925553) confirmed that on live camera:
  - `MonDrv::mp_output` points to an authentic 16-byte `MonQueue` object at `0x000218e8` with `capacity = 0x7bf0` (31,728 bytes).
  - Backed by `/dev/mem` PA `0x20098000` (length `0x7c000`), corresponding to WBI monitor log backup presets `0x00fa0028` and `0x00fa005d`.

## 3. Implementations & Breakthrough Milestone

1. **`src/a6400/execution/guest_uipc.py`**:
   - Updated `handle_valloc_msg_wait` and `allocate_message` to allocate with the authentic 12-byte OSAL header and compute `num_blocks`.
2. **`src/a6400/execution/guest_checkpoint.py`**:
   - Initialized authentic 16-byte `MonQueue` object (capacity `0x7bf0`) and bound `MonDrv::mp_output` (`0x52201fe0`), resolving `SIGFPE`.
3. **Execution Milestone (143.74M instructions)**:
   - Resuming from `boot-125m.ckpt` advanced from 132,956,105 past **143,736,126 instructions** (+10.78M instructions, 593,090 serviced syscalls, 39 concurrent threads, 100 open files) at up to **38.57 MIPS**.
   - Spawns child thread TID 1039 (`IMD-RM`), completes media detection, logs `[` character into `MonQueue`, and runs steady-state render loops in `libObj.so` at `0x72bb18` without crashing.
   - Saved verified snapshot checkpoint `artifacts/checkpoints/boot-140m.ckpt` (166.77 MB).
   - 561 tests pass.
