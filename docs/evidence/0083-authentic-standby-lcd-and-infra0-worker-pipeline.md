# 0083: Authentic Standby LCD, Fast-Hooks 125M Milestone, and THREAD_INFRA0 Synchronous Dispatch Architecture

## Objective
Enforce strict project instructions requiring *solely* authentic camera firmware behavior with zero synthetic UI mockups or simulated decision approximations. Trace and document the exact synchronization architecture of `THREAD_INFRA0` (TID 1001), worker `thread_1002`, and `main` (TID 1000) in `libObj.so`, and advance execution past 125,000,000 instructions under `--fast-hooks`.

## Discoveries & Architecture

### 1. Elimination of Synthetic UI Overlays (Strict Authentic Contract)
- Removed all host-written synthetic on-screen indicators (artificial "P", "RAW+J", battery percentage, fake AF reticles, and shutter/aperture text) from `tools/research/camera_gui_window.py` and `src/a6400/execution/dmp_rasterizer.py`.
- Corrected DMP PICA200 color buffer physical address decoding: register `0x116` (`0x00f01601`) passes a 16-byte aligned paragraph address (`0x0202e100 << 4 = 0x202e1000`, offset `0x1000` in the 32 MiB stream buffer), where authentic 16-bit color pixels reside.
- Rendered authentic standby LCD frame strictly from firmware VRAM: `artifacts/gui/camera_virtual_lcd.png` (960x540 RGBA, clean standby display).

### 2. Deep Reverse-Engineering of `THREAD_INFRA0` & `thread_1002` Dispatch Pipeline in `libObj.so`
- **Synchronization State Table**: Located in `.bss` at `0x13f6700` (`0x52076700` in guest VA space):
  - Struct 1 (`0x520767e8`): Owned by `THREAD_INFRA0` (TID 1001).
    - Mutex 1 (`+0x04`): `0x52076838`
    - Cond Var 1 (`+0x20`): `0x52076808`
    - Mutex 2 (`+0x50`): `0x52076838`
    - Cond Var 2 (`+0x68`): `0x52076850` (futex word at `0x52076854`)
    - Work Queue (`+0x98`): singly linked list of request items.
    - Worker Callback (`+0xa4`): `0x7808a1` in `libObj.so`.
  - Struct 2 (`0x52076888`): Owned by worker thread `thread_1002` (TID 1002).
    - Mutex 1 (`+0x04`): `0x5207688c`
    - Cond Var 1 (`+0x20`): `0x520768a8` (futex word at `0x520768b4`)
    - Work Queue (`+0x98`): singly linked list.
- **Worker Thread Entrypoint**: `0x780c40` (`libObj.so`):
  - In a continuous loop, locks mutex 1, pops items from queue `+0x98`. If empty, blocks on cond var 1 (`+0x20`) via `pthread_cond_wait`.
  - When an item arrives with tag `r3 == 2`: calls callback at `+0xa4`, frees item, and loops.
  - When an item arrives with tag `r3 == 0x8001`: calls callback at `+0xa4`, acquires mutex 2 (`+0x50`), signals cond var 2 (`+0x68`) via `pthread_cond_signal`, unlocks mutex 2, and cleanly exits the thread.
- **Dispatch Caller**: `0x780d60` (`libObj.so`):
  - Creates worker `thread_1002` via `pthread_create(&sb[0], &attr, 0x780c41, sb)`.
  - Enqueues synchronous completion token `0x8001` via `0x780870`.
  - Signals cond var 1 via `pthread_cond_signal` and immediately blocks on cond var 2 (`0x52076850`) via `pthread_cond_wait`.
  - `main` (TID 1000) waits on `pthread_join(THREAD_INFRA0)`.

### 3. Execution Milestone: 132,956,105 Instructions
- Resumed execution from `boot-110m.ckpt` under `--fast-hooks` to a budget of 125M instruction milestone:
  - Advanced to **132,956,105 instructions** (+22.95M instructions over 110M checkpoint).
  - Total serviced syscalls reached **450,335** (including 449,194 GLES/stream ioctls and 91 futex operations).
  - All 39 concurrent guest threads remain stable.
  - Steady-state display render loop continues cycling in `libObj.so` (TID 1008).
  - Checkpoint saved: `artifacts/checkpoints/boot-125m.ckpt` (146.18 MB).

## Verification & Status
- All 546 unit tests pass (`python -m unittest discover tests` in 14.6s).
- Verified artifact: `artifacts/gui/camera_virtual_lcd.png` (960x540, strictly authentic).
- Physical SD card `E:\` remains strictly read-only.
