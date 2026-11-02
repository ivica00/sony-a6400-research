# E0019 — Linux ARM NPTL Multithreading, Cooperative Scheduler, and Infrastructure Threads

Date: 2026-10-18. Scope: bounded guest process execution under the explicit `threads` syscall policy (`--syscalls threads`). Original ELF interpreter `ld-2.11.2.so` and Sony application `/usr/bin/im.elf`. No camera write, updater execution, or synthetic application logic is invoked.

## Findings

1. **Linux ARM EABI NPTL Multithreading Contract (`GuestThreads`)**:
   - Implemented stateful thread descriptor tracking and cooperative context switching in `src/a6400/execution/guest_threads.py`.
   - Syscall 120 (`sys_clone` / `__NR_clone`):
     - Validates GNU libc NPTL clone flags `0x3d0f00` (`CLONE_VM | CLONE_FS | CLONE_FILES | CLONE_SIGHAND | CLONE_THREAD | CLONE_SYSVSEM | CLONE_SETTLS | CLONE_PARENT_SETTID | CLONE_CHILD_CLEARTID`).
     - Reads child entry function `fn` and argument `arg` from the allocated thread stack `[child_stack, #0..8]`.
     - Allocates thread descriptor with isolated register context (`R0 = arg`, `SP = child_stack + 8`, `PC = fn & ~1`, `CPSR` Thumb bit set if `fn & 1`, `LR = 0x502a0628` clone exit).
     - Writes child thread ID (TID `1001`, `1002`, `1003`) to `parent_tidptr` in guest memory.
     - Returns child TID to parent thread in `r0`.
   - Syscall 224 (`sys_gettid`): returns the active thread's TID.
   - Syscall 172 (`sys_prctl`): implements `PR_SET_NAME` (`15`), setting the thread name in guest thread accounting.
   - Syscall 156 (`sched_setscheduler`) and 242 (`sched_setaffinity`): services scheduling policy and CPU affinity configurations, returning 0.

2. **Sony OSAL Task Synchronization Barrier and Futex Contract**:
   - Reverse engineering of `/usr/lib/libosal_utm.so` revealed that `osal_create_waitable_thread` uses a mutex on the caller's stack as an explicit synchronization barrier.
   - Parent thread locks the mutex prior to `clone`, then calls `pthread_mutex_lock` immediately after `clone` to block until the child thread signals completion.
   - Syscall 240 (`sys_futex` / `__NR_futex`):
     - `FUTEX_WAIT_PRIVATE`: checks `*uaddr == val`; on match, sets parent thread state to `blocked_futex` and triggers a cooperative context switch to the runnable child thread.
     - `FUTEX_WAKE_PRIVATE`: child thread executes `pthread_mutex_unlock` upon completing initialization, issuing `FUTEX_WAKE_PRIVATE` on the barrier mutex, unblocking the parent thread.

3. **Execution of Sony Camera Infrastructure Threads**:
   - Under cooperative scheduling, all three Sony camera infrastructure worker threads were spawned, context-switched, and executed:
     - **`THREAD_INFRA0`** (TID 1001): spawned for Task 94 Queue `0x94016a`, Priority 4, Entry `0x954d` in `im.elf`. Executes 18,322 instructions, sets its name to `THREAD_INFRA0`, unlocks the mutex barrier, and terminates via `sys_exit(0)`.
     - **`THREAD_INFRA1`** (TID 1002): spawned for secondary infrastructure queue. Executes startup and terminates via `sys_exit(0)`.
     - **`THREAD_INFRA2`** (TID 1003): spawned for third infrastructure queue. Executes startup and terminates via `sys_exit(0)`.
   - Syscall 1 (`sys_exit`): when a worker thread terminates (`tid != 1000`), the engine marks it `terminated`, clears its `child_tidptr` in memory (`CLONE_CHILD_CLEARTID`), wakes join waiters, and switches execution back to the runnable main thread.

4. **Advancement to 2,367,687 Instructions and Event Semaphore Boundary**:
   - Following initialization of all three infrastructure threads, the main thread resumes and surges to **2,367,687 instructions**.
   - Halts cleanly at character device `/dev/uipc` ioctl `0x80000001` (`UIPC_CMD_WAI_SEM_TMO`):
     - `r0`: `3` (`/dev/uipc`)
     - `r1`: `0x80000001` (`UIPC_CMD_WAI_SEM_TMO`)
     - `r2`: `0x7feffd38` (`struct { uint32_t sem_id; uint32_t timeout; ... }` where `sem_id = 0x83037a`, `timeout = 0xffffffff`)
   - The original Sony application has reached its main Task 94 event loop waiting on Semaphore `0x83037a`.

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
| **`threads`** | **2,367,687** | `syscall_boundary` (r7=54 / ioctl `0x80000001` `UIPC_CMD_WAI_SEM_TMO`) |

## Limitations and Next Steps

- **Semaphore Wait / Signal Contract (`UIPC_CMD_WAI_SEM_TMO`)**: Command `0x80000001` requests semaphore synchronization for semaphore `0x83037a`. Next work will implement the UIPC semaphore contract based on `osal_uipc.ko` semaphores table.
- **Event Loop & Asynchronous Messaging**: Once the semaphore is signaled or timed wait is evaluated, Task 94 will progress to message consumption via `UIPC_CMD_RCV_MSG_TMO` (`0x80000007`) and GUI / display initialization.
