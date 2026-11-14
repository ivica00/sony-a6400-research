# E0503 — Enforced `USR|Thumb` return at `0x6010DEF8` (`ret_fast_syscall`): second syscall now executes; `0x0402F666` repeat persists

Date: 2026-11-13. **Strictly offline.** No camera access, no USB, no writes. Inputs: E0414
dumps, E0416 contract, E0420–E0502 offline chain, the read-only dump set in
`artifacts/dumps/a6400-nflasha-readonly/` (full `/proc/kallsyms`).

## 0. Short answer

1. **Enforced user return added for the fast syscall path [C].** `0x6010DEC0` now
   snapshots the kernel-built `pt_regs` (base = `SP + 8`, backed by the E0500 frame dump:
   `+0x34 = 0x5E864C04`, `+0x38 = 0x0403E98D`, `+0x3C = 0x0403EB16`,
   `+0x40 = 0x600000F0`), and `0x6010DEF8` (`movs pc, lr`) performs the same enforced
   restore used at `0x6010DF64`: `CPSR = USR | Thumb`, `r0..r12`/`SP_usr`/`LR_usr` from the
   frame, `PC = thumb_pc(frame.pc, CPSR)` — i.e. the Thumb LSB binding is applied instead
   of letting Unicorn decode the even return PC as ARM.
2. **Effect: the second syscall now executes [C].** `svc_trace` shows **two** `brk`
   entries (`{pc 0x0403EB16, r7 45}` twice; `svc_hits = 2`) instead of one, which proves
   the fast-syscall return now reaches user code and can issue another SVC.
3. **But the `0x0402F666` repeat persists [C]:** stop `instruction_limit`
   (`PC 0x6010DE20`), `pt_frame_gen = 30`, and the classification still ends with the
   repeating `0x0402F666` prefetch entries; `serial 0 B`, no shell.
4. **Therefore the even-PC/T-bit theory is now only partially supported [C]/[I]:** the
   enforced restore changes the syscall-return path (two SVCs prove it), yet the same
   fetch keeps faulting. The remaining candidate is that `0x0402F666` is **genuinely
   entered in ARM state** (a `blx` to an ARM-only routine inside `ld-2.11.2.so`) and our
   recovery path treats it as Thumb; the next trace must log `CPSR.T`/`CPSR.M` at that
   fetch.

## 1. Evidence

| item | value |
| --- | --- |
| frame snapshot | `0x6010DEC0`, base `SP+8`, words from E0500 dump [C] |
| enforced return | `0x6010DEF8`: `CPSR = USR|Thumb`, frame GPRs/SP/LR, `PC = thumb_pc(pc)` [C] |
| syscalls | **2× `brk`** in `svc_trace` (`svc_hits = 2`) [C] |
| stop | `instruction_limit` `PC 0x6010DE20`, `gen = 30` [C] |
| repeat | `0x0402F666` prefetch entries persist [C] |
| shell | `serial 0 B` [C] |
| tests | new `test_fast_syscall_return_enforces_usr_thumb_odd_pc`; 1728 OK |

## 2. Implemented

* `_capture_fast_syscall_frame()` at `0x6010DEC0` and
  `_restore_fast_syscall_user_return()` at `0x6010DEF8` (enforced USR|Thumb + odd-PC
  binding, frame GPR/SP/LR restore), plus `emu_stop()` so the outer loop resumes cleanly.
* Unit test: static frame → USR+Thumb `CPSR`, `PC & ~1 == 0x0403EB16`, `SP_usr`, `r0`.

## 3. Next step

1. **Log `CPSR` at the `0x0402F666` fetch:** add `cpsr` to the fault classification entry
   (the E0502 patch inserted it in the wrong dict) and print `CPSR.T`/`CPSR.M`; if
   `T = 0` (ARM) the page must be entered in ARM state — then the fix is to accept ARM
   code in `ld-2.11.2.so` (execute the page as ARM, which Unicorn already does) and fix
   the fault trigger instead (e.g. the recovery path forcing Thumb).
2. Re-run; if `0x0402F666` executes once, continue the syscall chain
   (`uname`, `open`, `mmap2`, `set_tls`, `write`, `read`), BusyBox `_start 0x0000C439`,
   and the live `/bin/ash` prompt over `ttyAM0`.
