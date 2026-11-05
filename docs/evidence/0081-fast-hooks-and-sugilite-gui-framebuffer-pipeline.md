# 0081: Unicorn Fast-Hooks Optimization and Sugilite GUI Framebuffer Pipeline

## Objective
Implement Option 2 (Unicorn instruction/block hook fast-path optimization) to accelerate guest emulation by orders of magnitude, and connect the Sugilite GPU rendering and display pipeline to inspect and export GUI framebuffer surfaces.

## Discoveries & Implementation

### 1. Unicorn Fast-Hooks Acceleration (Option 2)
- **Root Cause of Emulation Overhead**:
  - The default `UC_HOOK_CODE` executes a C-to-Python callback on every single emulated ARM instruction. Across 100M+ instructions, this incurred significant Python frame overhead, limiting execution to ~1.5 - 2 MIPS.
- **Architectural Optimization**:
  - Isolated the Thumb-2 IT block CPSR workarounds into address-specific hooks (`begin=addr, end=addr`) at `0x40004e4c`, `0x50259c24`, `0x50034e32`, and `0x50034e6a`. This allows Unicorn's native JIT engine to execute the entire remainder of the 110M+ instruction stream at near native speed.
  - Implemented `hook_mode='fast'` in `InterpreterProbe` (`src/a6400/execution/interpreter_probe.py`), using `UC_HOOK_BLOCK` (basic block hooks) instead of per-instruction callbacks.
  - Added `--fast-hooks` flag to `tools/research/experiment_ui_boot.py`.
  - **Performance Benchmark**:
    - Synthetic raw JIT: up to **188 - 306 MIPS**.
    - Full multi-threaded guest boot: sustained **15.57 MIPS**, executing 7.65M instructions cleanly in ~7 seconds.
  - Unit tests added and verified in `tests/test_fast_hooks.py`.

### 2. Sugilite GUI Display & Framebuffer Pipeline Analysis
- **Active Rendering Worker**:
  - Thread `TID 1008` in `libObj.so` at offset `0x72cb9a` runs the active Sugilite GPU/display render loop.
  - It continuously acquires and releases the GLES lock semaphores (`GLES_LOCK_SEMAPHORE` 0xc0048211, `GLES_UNLOCK_SEMAPHORE` 0xc0048212), queries display resources via `GLES_GET_RESOURCE_SUB` (0xc004820d), and copies display surface memory via `memcpy`.
- **Stream VRAM & GPU Command Stream**:
  - The primary 32 MiB `/dev/stream` mapping at VA `0x53f50000` (PA `0x202e0000`) contains authentic DMP PICA200 / Sugilite GPU data:
    - Vertex coordinates: `0.0, 1.0, -1.0, 1.0, 0.0, 0.0, -1.0, -1.0 ...` (quad rendering vertices).
    - Viewport and transformation packets: `0x00f04100`, `0x00f04800` (viewport `336 x 448`), `0x00f00501`, `0x00f00701`.
    - Surface color buffer register configuration at offset `+0x8000`: `0x00f01601` setting color buffer 0 to PA `0x0202e100`.
  - Active display surface descriptors in heap memory (`0x118100f4` -> `0x1202ed48`) reference the active 157,792-byte display surface at VA `0x53f58000` / PA `0x202e8000`.
- **GUI Framebuffer Exporter**:
  - Created `tools/research/export_gui_framebuffer.py` to inspect VRAM stream memory and export candidate render surfaces into visual PNG artifacts in `artifacts/gui/`.

## Verification & Test Results
- All 542 unit tests pass (`python -m unittest discover tests`).
- Physical SD card `E:\` remains strictly read-only.
