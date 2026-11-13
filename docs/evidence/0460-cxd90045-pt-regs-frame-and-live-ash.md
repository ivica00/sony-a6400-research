# E0460 — Physical `pt_regs` frame capture at `ret_to_user`: base misalignment

Date: 2026-11-13. **Strictly offline.** No camera access, no USB command, no mode switch,
no firmware write. Inputs: E0414 dumps, E0416 contract, E0417 IRQ model, E0420–E0459.
Labels: **[C]** confirmed from artifacts/tests, **[I]** inference.

## 0. Short answer

1. **Frame capture is wired [C].** `_record_frame()` reads 18 words of the (assumed)
   `pt_regs` frame from physical RAM at each `ret_to_user` (`0x6010DF34`) entry
   (`[SP+0x00..0x44]` → `ARM_sp +0x34`, `ARM_lr +0x38`, `ARM_pc +0x3C`,
   `ARM_cpsr +0x40`) and stores up to 24 frames in the report (`pt_regs_frames`).
2. **The captured slots do not look like a user frame [C].** All 24 frames from the
   live run show `ARM_sp` slot `0x0`, `ARM_lr` slot `0x0`, `ARM_pc` slot
   `0x6010EB84` and `ARM_cpsr` slot `0x00000093` — a **kernel** PC and an **SVC** CPSR,
   so the assumed base (`SP`) is **misaligned** for the actual `pt_regs` frame at this
   point (the read lands in the kernel's own return frame, not the user `pt_regs`).
3. **No behavioural change [C]:** the run still stops on the VA-0 fetch at `PC = 0x0`
   (`unicorn_error`), `svc_hits = 0`, `kuser_hits = 1`, `serial 0 B`, no shell.
4. **Next step is precise:** find the real frame base (scan the SVC stack for the word
   pattern with `ARM_cpsr` mode bits `0x10` and `ARM_pc` in `0x04000000+`, or compute
   the handler's `SP` after `__pabt_usr`'s `sub sp,#0x48`), then dump the slots across
   delivery and `ret_to_user` to prove which write zeroes `ARM_pc`.

## 1. Evidence

| item | value |
| --- | --- |
| frames captured | 24 at `ret_to_user` [C] |
| slots (all frames) | `sp 0x0`, `lr 0x0`, `pc 0x6010EB84`, `cpsr 0x93` [C] |
| interpretation | assumed base `SP` is misaligned for the user `pt_regs` [C]/[I] |
| run | stops at `PC = 0x0`, `svc_hits 0`, `kuser_hits 1`, `serial 0 B` [C] |
| suite | unchanged **1543 OK** (diagnostic round) |

## 2. Implemented

* `_read_pt_regs_frame(sp, bias)` and `_record_frame(tag, sp, bias)`.
* Capture at `ret_to_user` entry; report field `pt_regs_frames`.
* (A first patch attempt partially failed; the final wiring is the one described here.)

## 3. Next step

1. **Determine the true `pt_regs` base:** at `ret_to_user` the frame is normally at `SP`,
   but the captured kernel PC/CPSR indicate shift; scan `SP-0x100..SP+0x100` for a word
   with `CPSR & 0x1F == 0x10` and a `PC` in `0x04000000..0x06000000`, and use that base
   for the slot dump.
2. Capture the same frame **after** `__pabt_usr` builds it (`SP_initial-0x48`) for both
   the `0x0402E790` prefetch and `0x0404E85C` data delivery, then compare the `ARM_pc`
   (`+0x3C`) and `ARM_lr` (`+0x38`) slots across `ret_to_user` to find the clobber.
3. Fix the slot/bias bug, then verify `0x0402F666`/`0x04031AF0`, `svc_hits` and capture
   the live `/bin/ash` prompt over `ttyAM0`.
