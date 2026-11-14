# E0492 — Generation-tagged `pt_regs`: stale replay eliminated; `ld-2.11.2.so` now executes deep into relocation code

Date: 2026-11-13. **Strictly offline.** No camera access, no USB, no writes. Inputs: E0414
dumps, E0416 contract, E0420–E0491 offline chain, the read-only dump set in
`artifacts/dumps/a6400-nflasha-readonly/` (including the full `/proc/kallsyms`).

## 0. Short answer

1. **Implemented generation-tagged `pt_regs` capture [C]:** at `0x6010DF34`
   (`ret_to_user` entry, base = `SP`) the full 18-word frame is snapshotted whenever
   `(ARM_cpsr & 0x1F) == 0x10` **or** `ARM_pc` is a user address, tagged with a
   monotonically increasing `pt_frame_gen`. At `0x6010DF64` (`movs pc, lr`) the exact
   generation is consumed **at most once** through a new `_take_user_frame()` helper —
   an already-consumed frame can never be replayed with zeroed `SP_usr`.
2. **The stale-replay defect is gone [C]:** the run reports `pt_frame_gen = 13`,
   `pt_frame_consumed = 12`, `user_restores = 7`; restored `SP` values are the real user
   stack (`0x5E864F10`, `0x5E864C94`, `0x5E864C74`) instead of `0x00000000`. The E0491
   "missing USR `SPSR`" hypothesis is **refuted**: every traced `0x6010DF50` carries a
   `USR` `SPSR` (`0x30`, `0xF0`, `0xD0`, …) tied to a fresh frame generation
   (`frame_gen` 3, 6, 8, 10, 12). The defect was replay, not capture.
3. **Execution now advances much deeper into `ld-2.11.2.so` [C]** (frame PCs):
   `0x0402E790` (entry) → `0x04031AA8` (`_dl_start`) → `0x04031AF0` (data page) →
   `0x0403FEA0` → `0x0403609C` → back to `0x0403D6A8`. Compared with E0474 (which only
   reached `0x0403D6B2` and stopped), the emulator now runs the loader's relocation/startup
   code.
4. **Remaining blocker [C]:** the call at `0x04031A68` (`bl 0x0403D6A8`, argument
   `0x04031A42 mov r0, r8`) still arrives with `r0 = r8 = 0`, so the callee's
   `0x0403D6B2 ldr r7, [r2], #4` (`argc = *argv`) reads `VA 0x0` and the run ends at
   `instruction_limit` (`PC 0x6025ED38`). No SVC is ever executed before that, so
   `svc_hits = 0`, `serial 0 B` — **no shell yet**. The `SPSR`/ABT-injection bug proposed
   in E0492 step 2 was therefore not the active cause; the callee argument (`r8`) is.
5. **SVC dispatch is now deferred-installed and boot-safe [C]:** `--svc-dispatch` no
   longer stalls early init (that was the E0436 regression). The `UC_HOOK_INTR` hook is
   installed only when the virtual TLB activates at the first user return
   (`_svc_hook_installed`); early boot and the user path are unchanged.

## 1. Evidence

| item | value |
| --- | --- |
| frame capture | `0x6010DF34`, base `SP`, 18 words, gen tag [C] |
| consume-once | `_take_user_frame()`; second hit without new frame returns `None` [C] |
| generations | `pt_frame_gen = 13`, `pt_frame_consumed = 12` [C] |
| restores | 7; `SP` = `0x5E864F10` / `0x5E864C94` / `0x5E864C74` (valid user stack) [C] |
| MSR trace | every `0x6010DF50`: `SPSR` `USR` (`0x30`/`0xF0`/`0xD0`), fresh `frame_gen` [C] |
| frame PCs | `0x0402E790`, `0x04031AA8`, `0x04031AF0`, `0x0403FEA0`, `0x0403609C`, `0x0403D6A8` [C] |
| remaining fault | `0x0403D6A8` → `0x0403D6B2` `ldr r7,[r2],#4` with `r0=r8=0` → `VA 0x0` [C] |
| SVC | deferred hook installed; `svc_hits = 0` (no SVC reached) [C] |
| stop | `instruction_limit`, `PC 0x6025ED38`, `serial 0 B` [C] |
| tests | `test_take_user_frame_consumes_generation_once` + 37 in `test_virtual_tlb` [C] |

## 2. Implemented

* `pt_frame_gen` / `pt_frame_last` / `pt_frame_consumed` state, `e0492_frames` and
  `e0492_msr` report traces, and the `_take_user_frame()` consume-once helper.
* `0x6010DF34` snapshotting (base = `SP`, E0461 layout: `sp +0x34`, `lr +0x38`,
  `pc +0x3C`, `cpsr +0x40`) and `0x6010DF64` restoration from that exact frame.
* `--svc-dispatch` runner flag + `enable_svc_dispatch` constructor option; the
  `UC_HOOK_INTR` hook is installed at virtual-TLB activation instead of at construction.
* Unit test: consume-once semantics (first take OK, replay `None`, new generation OK).

## 3. Next step

1. **Find who should set `r8` for the `0x0403D6A8` call** (the loader calls it as
   `mov r0, r8`): trace `r8` from `0x0402E790` through the frame generations
   (`0x04031AA8`, `0x0403FEA0`, `0x0403609C`) and compare with the same code path in the
   statically decoded `ld-2.11.2.so`; likely an unmodelled `pop {…}`/`ldmia`/`mov` in the
   native Thumb block that our recovery manual-stepped around.
2. Once `r0` is correct at `0x0403D6A8`, re-check `0x0403D6B2`; then verify
   `0x0402F666`/`0x04031AF0`, `svc_hits` (deferred dispatch is now live), BusyBox
   `_start 0x0000C439`, and capture the live `/bin/ash` prompt over `ttyAM0`.
