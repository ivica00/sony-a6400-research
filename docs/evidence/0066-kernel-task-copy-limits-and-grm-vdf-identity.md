# Evidence 0066: Kernel task copy bounds and grm_dn_vdf_if identity resolution

Date: 2026-10-24

## Result

Analysis of `tools.research.kernel_task_copy_trace`, captured WBI memory, and `libObj.so` resolves the true identity of task 358 and establishes the origin of `grm_dn_vdf_if`:

1. **Original task copy execution (409 instructions)**:
   Original kernel task copying routines (`copy_process`, `copy_thread`, `copy_thread_info`, `arch_task_copy`) execute 409 instructions up to the thread notifier boundary (`NOTIFIER_CALL` at `0x6010f1d4`). The isolated child frame inherits the parent's user registers with child r0 = 0 and sp pointing to the supplied user stack control.

2. **Strict user address limit `0x5f000000`**:
   The user space boundary `0x5f000000` is enforced across multiple compiled kernel limit windows (`0x601381c8`, `0x6019cb54`, `0x601c4e0c`, `0x601c5284`). `execute_area_prefix` verifies that allocations with `length=0x5f000001` return `-ENOMEM` (-12), while unaligned/invalid fixed addresses return `-EINVAL` (-22) without supplying unverified MMIO or callback responses.

3. **Task 358 resolved as `THREAD_INFRA0`**:
   `observed_task_name` (evaluating the kernel's authentic `get_task_comm` source offset at `task + 0x1e8`) proves that captured task `0x60a4a800` (PID 358, TGID 152) is actually `THREAD_INFRA0`.

4. **Real `grm_dn_vdf_if` located in adjacent dead task 356**:
   In E0064, the string `grm_dn_vdf_if` was observed at `0x60a4a800 + 0x5c8` (`0x60a4adc8`).
   - Kernel `sizeof(task_struct)` is verified as `0x3d0` (976 bytes) via `COPY_TASK` at `0x60131740` (`mov r2, #0x3d0; bl memcpy`).
   - The slab allocator object stride is `0x3e0` (992 bytes).
   - The next slot in the slab is `0x60a4a800 + 0x3e0 = 0x60a4abe0`, which holds task 356.
   - Task 356's `comm` at `0x60a4abe0 + 0x1e8` is precisely `0x60a4adc8` (`grm_dn_vdf_if`).
   - Task 356 has PID 356, TGID 152, and `state = 0x40` (`TASK_DEAD`).
   - Following task 356's termination, its thread_info/stack page `0x684a4000` was reallocated to task 481 (`liro-kliro_33`).

5. **Userland origin of `grm_dn_vdf_if`**:
   In `libObj.so`, `vdf_if_port_init` at `0x70f188` / `0x70f358` creates thread `grm_dn_vdf_if` via `osal_create_waitable_thread` (`0x10073c`), binding to queue `0x0080003b`.
   In full firmware execution (`docs/experiments/0005-uipc-blocking-receive.md`), this corresponds to userland thread TID 1005 (`grm_dn_vdf_if`), which performs a blocking receive on queue `0x0080003b` before yielding to TID 1003.

6. **Connection of main process (`im.elf`) to GLES kernel (`grm_gles.ko`)**:
   In `artifacts/execution/ui-boot-task-copy-mmap-150m.json`, the main process executes 80,739,451 instructions, maps `/dev/stream` (32 MiB at VA `0x53f00000` / PA `0x202e0000`), performs thread clones, and attempts `open("/dev/dmpgles2")`.
   `sugilite_open` requires an authentic kernel process binding respecting `TASK_SIZE = 0x5f000000` and reciprocal `thread_info` backlinks.

## Inputs and evidence references

- `artifacts/analysis/kernel-task-copy-names-and-user-bounds/report.json`:
  Captures copy traces, observed group tasks, compiled limit windows, and area prefix boundary cases.
- `artifacts/execution/ui-boot-task-copy-mmap-150m.json`:
  Main process execution stopping at 80,739,451 instructions with `gles_kernel_process_binding_not_supplied`.
- Preserved inputs:
  - `dev/nflasha5`: WBI memory dump (SHA `19a702b030306a32f4287131da314e5c89d66163997f0f9a23b0967981b0001b`).
  - `dev/nflasha15_unpacked/kmod/grm_gles.ko`: GLES kernel module (SHA `a8d1dbe8c66be365d32371b13f35a0e7d598c415c0ff17f2c8f544084ccc6882`).
  - `dev/nflasha3_unpacked/vmlinux.bin`: Kernel binary (SHA `12eeec829407595e28265f7d0db3b88c56f63a9f0fdd725c9c53c66a49643707`).
  - `dev/nflasha15_unpacked/lib/libObj.so`: Userland middleware binary.

## Validation

All **446 tests pass** (15.262 seconds).
New tests in `tests/test_kernel_task_copy_trace.py`:
- `test_task_358_is_thread_infra0_and_task_356_is_grm_dn_vdf_if`: Verifies authentic task comm for 358 (`THREAD_INFRA0`), adjacent dead task 356 (`grm_dn_vdf_if`, state `0x40`), PID/TGID (356/152), and source address `0x60a4a800 + 0x5c8`.
- `test_libobj_vdf_if_port_registers_queue_and_thread_name`: Verifies `libObj.so` literal pool binding for queue `0x0080003b` and target string `grm_dn_vdf_if` at `0xfd8860`.

Physical card volume `E:\` remains strictly read-only. No host-faked kernel replies, synthetic draw calls, or unverified VRAM pixels are supplied.
