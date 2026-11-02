# E0020 — UIPC Semaphores, Message Queues, and 1 Hz Application Event Loop Heartbeat

Date: 2026-10-18. Scope: bounded guest process execution under the explicit `threads` syscall policy (`--syscalls threads`). Original ELF interpreter `ld-2.11.2.so` and Sony application `/usr/bin/im.elf`. No camera write, updater execution, or synthetic application logic is invoked.

## Findings

1. **UIPC Binary Semaphore Contract (`0x80000000` - `0x80000002`)**:
   - Reverse engineering of `/usr/kmod/osal_uipc.ko` (`__k_4u_wai_sem_tmo`, `__k_4u_sig_sem`, `osal_wai_sem_tmo`, `osal_sig_sem`, `get_bsem`) and `/usr/lib/libosal_uipc.so` revealed the binary semaphore (`bsem`) contract:
     - `UIPC_CMD_WAI_SEM_TMO` (`0x80000001`): argument points to `struct { uint32_t sem_id; uint32_t timeout; }`.
       - Initial state: available (unlocked). When requested on semaphore `0x83037a` (Task 94 primary semaphore), it is acquired immediately without blocking and returns 0.
     - `UIPC_CMD_SIG_SEM` (`0x80000002`): argument points to `struct { uint32_t sem_id; uint32_t reserved; }`. Releases ownership, wakes waiters if any, and returns 0.
     - `UIPC_CMD_STAT_SEM` (`0x80000000`): returns binary semaphore state, current owner TID, and waiter count.

2. **Fourth Infrastructure Thread (TID 1004) & Message Queue Contract**:
   - After acquiring semaphore `0x83037a`, the Sony application spawned a 4th camera infrastructure worker thread (TID 1004) via `sys_clone(0x3d0f00)`, which initialized and terminated cleanly.
   - The main thread advanced into subsystem message exchange:
     - `UIPC_CMD_SND_MSG` (`0x80000004`): argument points to `struct { uint32_t queue_id; void *msg_ptr; }`. Task 94 sent an asynchronous message to Task 92 (Queue `0x00920021`), the central subsystem manager.
     - `UIPC_CMD_STAT_MSGQ` (`0x80000003`): queries queue depth and waiter status.
     - `UIPC_CMD_RCV_MSG_TMO` (`0x80000007`): argument points to `struct { uint32_t queue_id; uint32_t *p_out_msg; uint32_t out_msg; uint32_t timeout; }`.
       - When the queue is empty, the kernel returns `-11` (`-EAGAIN`), which libc's `ioctl` translates via TLS `errno` into an OSAL timeout/empty code (`0xfffffc00`).

3. **ARM Linux TLS Restoration Across Context Switches**:
   - Fixed a critical thread context restore boundary: when switching context back from worker threads to the main thread (TID 1000), the main thread's TLS value (configured via `set_tls` `0xf0005`) was not previously updated in the thread descriptor. Restoring `0xffff0ff0` ensures `__kuser_get_tls` and libc `errno` function correctly on the main thread.

4. **1 Hz Application Event Loop Heartbeat (`sys_nanosleep`, Syscall 162)**:
   - When Task 94's primary message queue (`0x0094016a`) has no pending events, the Sony camera application transitions to its 1 Hz event loop sleep:
     - Syscall 162 (`sys_nanosleep`): passes `struct timespec { tv_sec: 1, tv_nsec: 0 }`.
     - Returns 0, allowing the application to wake periodically, poll subsystem queues, update signal masks (`rt_sigprocmask`), and maintain its execution heartbeat.

5. **Milestone: Over 8,777,210 Instructions Executed**:
   - The execution engine executed over **8.77 million instructions** and completed over **17,000 continuous event loop cycles** before reaching the bounded timeout without faults, memory access violations, or unhandled syscall boundaries.
   - The complete test suite contains **193 passing tests** (100% pass rate).

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
| **`threads`** | **8,777,210+** | Continuous 1 Hz event loop heartbeat (`nanosleep` / `rcv_msg_tmo`) |

## Next Steps

- Supply authentic event stimuli into Queue `0x0094016a` and evaluate callback dispatch into Sony UI/rendering components.
- Map Sony display buffer / frame rendering character devices.
