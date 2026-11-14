# L3 User-Space (`im.elf`), OSAL/UIPC & Heap Findings

Consolidated technical reference from `E0298–E0340` and `E0473` for user-space process execution under `InterpreterProbe`.

## 1. Execution Model & Thread Scheduling

- **Entry & Argv (`E0301`)**: Physical PID 149 runs `im.elf debug s g r u l i a lazy-global`.
- **Cooperative-Scheduler Fix (`E0473`)**: `GuestThreads` previously switched only on block/yield/≥100 ms sleep, allowing non-blocking UIPC poll loops to starve other threads. Opt-in `--thread-timeslice N` enforces deterministic timer preemption across runnable threads, unlocking 88+ threads (`THREAD_INFRA0` completion, `THREAD_APP`, `Appframework`, `gui.so`, font loading).
- **Task Identity (`E0302`)**: `KernelTaskIdentityTable` tracks per-clone `pid`/`tgid`/backlinks (`0x5F000000` range) and rejects unobserved callers.

## 2. OSAL / UIPC & `MWF::ObjMsg` Protocol (`E0300–E0338`)

- **Bit-15 Queue Dispatch (`E0331`)**: `libosal_uipc` routes queue IDs with bit 15 set (e.g., `0x00CA8192` for `UsbControl`, `0x012182EB` for `UsbBusPower`, `0x012282F6` for `BusPower`) through process-local user-space queue objects (`+4 flags`, `+8 wait list`, `+0xC head = payload - 0xC`) + `FUTEX_WAKE_PRIVATE`, rather than kernel UIPC ioctls.
- **Kernel Sync Queues (`E0332–E0334`)**: `0x00CA0288` (handle `4109`, `UFW::AdjBase::funcOsalSyncCb` expecting 320-byte `UFW::OsalRequestPacket`) and `0x00CA01A4` (handle `4110`, `UsbControl::funcInputGetCb`).
- **MWF `ObjMsg` & `SETCONFIG` (`E0323–E0337`)**: `ObjMsg` carries `{body_ptr, vtable}` with `ParamMap` and typed `ParamStd<int,7>` (`funcTable` in `libMWF.so`). Inbound `SETCONFIG` (`{0x6103, 0x0A4001, param 0x1006=0}`) dispatches through `UsbControl::MsgId2EventId` → FSM event `0x13` (19) and broadcasts `0x0A4002`.
- **Timeout Blocking (`E0308`)**: Under `kernel-e0301`/`kernel-e0303`, finite positive `RCV_MSG_TMO` blocks until message arrival instead of returning `-1022` immediately.

## 3. `stella HeapAllocator` Pool-Boundary Bug (`E0484+` / Round 4)

- Under `--thread-timeslice`, `Appframework` (TID 1087) aborts with glibc `malloc.c:4652: _int_malloc: Assertion (unsigned long)(size) >= (unsigned long)(nb) failed`.
- **Root cause (not an emulator bug)**: `libObj` `stella` `HeapAllocator` allocates a pool block via `malloc(0x4C)` (chunk `0x13E6B8`, raw size `0x50`, usable `0x4C`), then advances its internal block pointer by the **rounded chunk size `0x50`** instead of usable `0x4C`. The next block (`0x13E710`) overlaps 4 bytes into the neighbouring freed libc chunk `0x13E708` in `bin9`, corrupting its `fd`/`bk` pointers (`libObj+0x7AF45A`).
- Enlarging the request (`0x4C -> 0x50` via `--guest-patch-logalloc-0x50`) only shifts the overrun; a usable-size subtraction patch in helpers `0x79E8C2`/`0x79E902` is the candidate fix.
