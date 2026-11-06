# E0096: authentic /proc/modules, FBResourceManager and MediaDetect polling boundary

## Verified facts

1. `libObj.so` `grm::FBResourceManager::initialize()` (0x65e320) calls 0x71f318, which `fopen("/proc/modules")`
   and `fgets`-scans for the substring `"grm_ma "` (literals at libObj 0xfdbafc / 0xfdbb0a). A missing file returns
   an error and the caller asserts `MA_ErrNone == err` (FBResourceManager.cpp:69), then aborts.
2. `/proc/modules` was read from the physical ILCE-6400 (`tools/camera_debugger.py exec "cat /proc/modules"`,
   42 lines, saved in `artifacts/camera_proc_modules.txt`). `grm_ma 19680 0 - Live 0x5f3f7000 (P)` is present.
3. `GuestFilesystem` now serves that exact content (`AUTHENTIC_PROC_MODULES`) under
   `proc_overlay='experimental-empty'` for open/access/stat/fstat/lseek/read/close.
   Test: `tests/test_guest_filesystem.py::test_proc_overlay_modules`.
   The 42 lines are static camera data. The module load addresses are from one boot and are not claimed stable.
4. Resumed from `boot-140m.ckpt` the emulator reaches 201,325,952 instructions
   (checkpoint `artifacts/checkpoints/boot-172m-touch-input.ckpt`). Touch and input threads exist and block cleanly:
   `I-TpMain`/`I-TpRecv` on UIPC queues 0x007b0026/0x007b002b, `I-InputMain` on a futex,
   `I-InputRepeat` on semaphore 0x7a80c0 (`u_osal_wai_sem_tmo`).
5. `THREAD_INFRA0` (TID 1001) terminates cleanly (verified, 224.6M instructions).
   `main` (TID 1000) does NOT wake because it is joined on a different thread: its futex address
   0x53f4f4c8 is `child_tidptr` of `THREAD_INFRA1` (TID 1004), not of 1001 (0x50c7f4c8).
6. `THREAD_INFRA1` (1004) is in `libInfraMediaDetect.so` and issues only `nanosleep(100 ms)` through a libMWF
   sleep helper (libMWF 0x23800: ms to nanosleep with EINTR retry). It performs no other syscalls, so it is
   polling a memory flag that has not been set. The syscall dispatcher and scheduler behave correctly.

## Not verified / next step

- Which memory flag 1004 polls and which writer should set it (likely the media-detect state fed by the
  `authentic-sd` media service). Next: trace loads in the 1004 polling loop to find the polled address, then find
  its authentic writer in `libInfraMediaDetect.so` / `libMWF.so`. Do not set it from the host.
- Touch/menu behaviour in the emulator is not yet demonstrated.
- A scratch harness manually switched the scheduler to TID 1001 to diagnose the stall; that is diagnostic only,
  not a fix.

SD E:\ remains read-only for the emulator. No camera RAM patches or SD writes were made.
