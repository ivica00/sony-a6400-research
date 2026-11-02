# E0018 — Standard I/O Contract, UIPC Callbacks, and Thread Creation (sys_clone)

Date: 2026-10-18. Scope: bounded guest process execution under the explicit `uipc` syscall policy (`--syscalls uipc`). Original ELF interpreter `ld-2.11.2.so` and Sony application `/usr/bin/im.elf`. No camera write, updater execution, or synthetic application logic is invoked.

## Findings

1. **Standard I/O & Console / TTY Contract (`GuestStdio`)**:
   - Glibc initial stream setup requires metadata and device attributes on inherited standard descriptors 0, 1, and 2.
   - Descriptors are backed by verified `/dev/console` metadata extracted from ext2 rootfs partition `nflasha7` (inode 118, mode 8576 `S_IFCHR | 0600`, major 5 minor 1 `rdev 0x501`, uid 0, gid 5).
   - Syscall 54 (`ioctl`) handling for `TCGETS` (`0x5401` / `isatty(1)`): returns `-ENOTTY` (`0xffffffe7` / `-25`), informing libc that standard streams are character console devices rather than pseudo-terminals, enabling standard block buffering and allowing stdout initialization to complete cleanly.
   - Syscalls 4 (`write`) and 146 (`writev`): output bytes are captured in diagnostic stream logs without host leakage.

2. **UIPC Callbacks and Direct Synchronous Messaging**:
   - Command 8 (`0x80000008`, `__k_4u_reg_msg_queue_cb`): user passes pointer to `struct { uint32_t queue; void *params; }` where `params` points to `struct { uint32_t *out_handle; uint32_t cb; uint32_t user_data; uint32_t flags; }`. Application registers multiple asynchronous event callbacks:
     - Queue `0x94016a` (Task 94) -> callback `0x9635` (inside `im.elf`)
     - Queue `0x0` -> callback `0x50031d35` (inside `libosal_uipc.so`)
     - Queue `0x940270` -> callback `0x95f7` (inside `im.elf`)
   - Command 6 (`0x80000006`, `__k_4u_snd_sync_direct`): user passes pointer to `struct { uint32_t queue; void *buf; }` where `buf` begins with a 16-byte header `[total_size, f1, f2, f3]` followed by `total_size - 16` payload bytes. `im.elf` sends a direct synchronous configuration packet to queue `0x920277`.

3. **Sony Application Task 94 Execution Phases**:
   - Following callback registration, `im.elf` progresses through all five Task 94 initialization phases via diagnostic profiling events sent to system queue `0x8f013a`:
     - Phase 0: `Ib 094_0` Begin (`94 B`) and End (`94 E`)
     - Phase 1: `Ib 094_1` Begin (`94 B`) and End (`94 E`)
     - Phase 2: `Ib 094_2` Begin (`94 B`) and End (`94 E`)
     - Phase 3: `Ib 094_3` Begin (`94 B`) and End (`94 E`)
     - Phase 4: `Ib 094_4` Begin (`94 B`) and End (`94 E`)

4. **Emulator IT-Block Bug Resolution in glibc `_int_malloc`**:
   - During heap allocation in Phase 4, an emulator issue was identified: a 32-bit Thumb instruction `0x50259c20: c7f84824` inside an `it hi` block at `0x50259c1e` failed to clear IT state in Unicorn CPSR (`IT=0x22`).
   - This caused Unicorn to skip subsequent non-IT instructions at `0x50259c2e` (`ldr.w r2, [pc, #0x43c]`), preventing `main_arena` address resolution and corrupting the chunk arena flag (`NON_MAIN_ARENA`).
   - Extending the IT-block leftover workaround to address `0x50259c24` allows `_int_malloc` to complete properly and returns valid memory chunks.

5. **Thread Creation Boundary: Syscall 120 (`sys_clone`) Reached at 2,218,147 Instructions**:
   - At instruction **2,218,147**, `im.elf` completes Task 94 initialization and initiates thread spawning via `pthread_create` inside `/lib/libpthread-2.11.2.so` (return address `0x5008451d`).
   - Halts cleanly at Linux ARM EABI `sys_clone` (syscall 120 / `0x78`):
     - `r0`: `0x3d0f00` (`CLONE_VM | CLONE_FS | CLONE_FILES | CLONE_SIGHAND | CLONE_THREAD | CLONE_SYSVSEM | CLONE_SETTLS | CLONE_PARENT_SETTID | CLONE_CHILD_CLEARTID`)
     - `r1`: `0x50c7ef98` (child thread stack pointer, from an 8 MiB mmap allocation at `0x50480000..0x50c80000`)
     - `r2`: `0x50c7f4c8` (`parent_tid`)
     - `r3`: `0x50c7f920` (`tls_val`)
     - `r4`: `0x50c7f4c8` (`child_tid`)
     - PC: `0x502a05d8` (inside `clone` in `libc-2.11.2.so`)

## Regression Baselines

All historical baselines remain strictly intact:

| Policy | Instructions | Boundary / Status |
| --- | --- | --- |
| `stop` | 1,183 | `syscall_boundary` (r7=45 / `brk`) |
| `brk` | 2,222 | `syscall_boundary` (r7=122 / `uname`) |
| `brk-uname` | 3,091 | `syscall_boundary` (r7=33 / `access` -> `/etc/ld.so.preload`) |
| `files` | 5,078 | `unsupported_filesystem` (`stat64` on `/lib`) |
| `metadata` | 6,493 | `unverified_metadata_read` (guarded `st_dev` on `/lib`) |
| `--respect-runtime-mounts` | 3,091 | `unsupported_filesystem` (unsupplied `/etc`) |
| `mmap` | 56,230 | `memory_boundary` (unmapped `__kuser_cmpxchg` at `0xffff0fa0`) |
| `kuser` | 2,029,074 | `unsupported_filesystem` (`open` on `/dev/uipc`) |
| `uipc` | 2,218,147 | `syscall_boundary` (r7=120 / `clone`) |

## Limitations and Next Steps

- **Multithreading Contract (`sys_clone`)**: Spawning concurrent threads in Unicorn requires thread state management (separate CPU register contexts, shared virtual address space, per-thread TLS pointers via CP15/kuser, and thread scheduling/switching).
- **Asynchronous Callback Dispatch**: Three message queue callbacks (`0x9635`, `0x50031d35`, `0x95f7`) have been registered by the application; future work will evaluate event polling mechanisms and callback invocation models.
