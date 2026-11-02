# E0017 — Main Application Entry Point and /dev/uipc IPC Contract

Date: 2026-10-18. Scope: bounded guest process execution under the explicit `uipc` syscall policy (`--syscalls uipc`). Original ELF interpreter `ld-2.11.2.so` and Sony application `/usr/bin/im.elf`. No camera write, updater execution, or synthetic application logic is invoked.

## Findings

1. **Analysis and Reversal of `/dev/uipc` Driver Contract (`osal_uipc.ko`)**:
   Analysis of `/usr/kmod/osal_uipc.ko` (offset in partition 15 `nflasha15`) and `/usr/lib/libosal_uipc.so` resolved the complete character device contract for `/dev/uipc`:
   - Driver registers character device ioctl handler `__k_uipc_cdev_ioctl` dispatching via an internal table in `.rodata` matching `libosal_uipc.so` calls.
   - Command 16 (`0x80000010`, `__k_4u_connect`): user passes pointer to `struct { uint32_t cmd; void *user_buf; }`. Driver returns pool dimensions:
     - `total_pool_size = 0x100000` (1 MiB shared pool)
     - `vpool_size = 0x40000` (256 KiB)
     - `fblock_size = 0x8000` (32 KiB)
     - `reserved = 0`
   - Command 10 (`0x8000000a`, `__k_4u_valloc_msg_wait`): user passes pointer to `struct { uint32_t pool_id; void *params; }` where `params` points to `struct { void **out_msg_ptr; uint32_t size; uint32_t flag; }`. Driver allocates a buffer from the shared pool and writes the user-mapped address to `*out_msg_ptr`.
   - Command 5 (`0x80000005`, `__k_4u_snd_sync_msg`): user passes `struct { uint32_t target_queue; void *params; }` where `params` points to `struct { void *msg_ptr; uint32_t timeout; uint32_t flag; }`. Synchronously delivers message to destination queue.
   - Command 11 (`0x8000000b`, `__k_4u_free_msg`): user passes `struct { uint32_t pool_id; void *msg_ptr; }` to return allocated message memory to the pool.
   - Syscall 221 (`fcntl64`): userland library configures file descriptor flags `F_SETFD` (`FD_CLOEXEC = 1`).
   - Syscall 192 (`mmap2`): userland library maps the 1 MiB shared pool (`0x50330000..0x50430000`) and a 256 KiB private anonymous buffer.

2. **Crucial Milestone: Main Application Entry Point Reached**:
   Once `libosal_uipc.so` initializes its message subsystem, all 12 shared library initializers complete.
   The dynamic linker (`ld-2.11.2.so`) completes relocation and library initialization, then transitions control via `blx r3` into the main application:
   - Target address: `0x9140` (Thumb entry point `0x9141`) in `/usr/bin/im.elf`.
   - Instruction counter: **2,073,233**.
   - Original Sony camera application code is now actively running!

3. **Sony Application Task 94 Initialization**:
   Inside `/usr/bin/im.elf`, the application begins its runtime setup:
   - Calls `osal_valloc_msg_wait` to allocate a 52-byte message in the shared UIPC pool.
   - Formats task registration message:
     `\t\x00  94 B  Ib 094_main()\x00`
   - Sends synchronous message via ioctl `0x80000005` to system queue `0x8f013a`.
   - Frees message via ioctl `0x8000000b`.
   - Performs subsequent task-to-task messages with queues `0x3e014d` and `0x94016a` (task 94 queue).

4. **Standard I/O Boundary Reached at 2,107,153 Instructions**:
   Following task and message initialization, `im.elf` initiates standard library I/O and console initialization.
   At **2,107,153 instructions**, execution halts cleanly at `PC: 0x50215796` (inside `fstat64` in `libc-2.11.2.so`):
   - `status`: `unsupported_filesystem`
   - `reason`: `inherited_stdio_not_supplied`
   - `fd`: `1` (standard output)
   - `r7`: `197` (sys_fstat64)
   - Arguments: `[1, 0x7feff110, 0x7feff110]`

## Regression Baselines

All historical baselines remain intact:

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
| `uipc` | 2,107,153 | `unsupported_filesystem` (`fstat64` on fd 1 / stdio) |

## Limitations and Next Steps

- **Standard I/O Descriptor Policy**: File descriptors 0, 1, and 2 are currently unsupplied under the fail-closed guest filesystem policy. Adding an explicit stdio contract (e.g. connected to host streams, in-memory capture buffers, or virtual console device `/dev/console`) will allow `im.elf` to complete its standard library output initialization.
- **Multitasking and UIPC Daemons**: Currently, `im.elf` executes in a single-process probe. IPC messages sent to other camera daemons (e.g. `app_mgr`, `gui`) are acknowledged synchronously. Emulating or running peer daemons will be required as application logic deepens.
