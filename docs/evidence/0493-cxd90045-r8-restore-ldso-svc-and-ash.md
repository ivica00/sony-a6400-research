# E0493 — `r8` provenance: `mov r8,r0` at `0x04031A0C` gets 0 because the recovery replay writes `[sp,#0x20]` in the wrong bank

Date: 2026-11-13. **Strictly offline.** No camera access, no USB, no writes. Inputs: E0414
dumps, E0416 contract, E0420–E0492 offline chain, the read-only dump set in
`artifacts/dumps/a6400-nflasha-readonly/` (full `/proc/kallsyms` used for the address
cross-checks).

## 0. Short answer

1. **The `r8` consumer is identified [C].** `_dl_start` calls the `0x040319F0` helper via
   `bl 0x040319F0` at `0x04031BE8` with `r0` loaded at `0x04031BDE`
   (`ldr r0, [sp, #0x20]`). Inside that helper `0x04031A0C mov r8, r0` saves the argument,
   and after `bl 0x0403609C` / the memset call, `0x04031A42 mov r0, r8` passes it to
   `0x04031A68 bl 0x0403D6A8` — whose callee does `ldr r7, [r2], #4` (`argc = *argv`).
   So `r0 = r8` must be the initial user stack pointer (`0x5E864F10`).
2. **`r8` is 0 in every captured `pt_regs` frame [C]** — including the frames after the
   memset page faults at `0x0403FEA0` (`lr = 0x04031A23`, `r0 = 0x0404E568`,
   `r4 = 0x0404E048`, `r7 = 0x5E864C74`, **`r8 = 0`**). So the register file really
   contained 0; this is not a frame-layout/restoration bug (the `pt_regs` `+0x20` slot is
   correctly restored as `r8`; new unit test covers it).
3. **Root cause: the recovery replay writes `[sp,#0x20]` into the kernel stack [C].**
   The first native entry at `0x04031AA8` is correct (`r0 = 0x5E864F10`, `SP = 0x5E864F10`).
   The `INSN_INVALID` recovery then manually executes `0x04031AAC..0x04031ABA`, including
   `0x04031AB6 str r0, [sp, #0x20]`. The `e0493_trace` shows the trace hook at
   `0x04031AAC` firing with **`SP = 0x60472990` (kernel stack), `LR = 0x04031AAC`, `r0 = 0`**
   — i.e. that prologue instruction is executed with the **SVC bank**, not the user stack.
   Later `0x04031BDE ldr r0, [sp, #0x20]` therefore reads 0 (user stack slot never written),
   `0x04031A0C mov r8, r0` stores 0, and `0x04031A42 mov r0, r8` passes 0 to the
   `argc = *argv` callee → `VA 0x0`.
4. **No behaviour change yet [C]:** `pt_frame_gen = 13`, `consumed = 12`, 7 restores,
   `user_restores = 7`, stop `instruction_limit` (`PC 0x6025ED38`), `svc_hits = 0`,
   `serial 0 B` — no shell. This round is the root-cause trace plus two regression tests.

## 1. Evidence

| item | value |
| --- | --- |
| `r8` consumer | `0x04031A0C mov r8,r0` → `0x04031A42 mov r0,r8` → `0x04031A68 bl 0x0403D6A8` [C] |
| argument source | `0x04031BDE ldr r0,[sp,#0x20]` (slot written at `0x04031AB6 str r0,[sp,#0x20]`) [C] |
| first native entry | `0x04031AA8`: `r0 = 0x5E864F10`, `SP = 0x5E864F10` [C] |
| recovery trace | `0x04031AAC` hook: `SP = 0x60472990` (kernel bank), `LR = 0x04031AAC`, `r0 = 0`, `sp20 = 0` [C] |
| frames | memset faults `0x0403FEA0`, `lr 0x04031A23`, `r8 = 0` in `pt_regs +0x20` [C] |
| run | `instruction_limit` `PC 0x6025ED38`, `svc_hits 0`, `serial 0 B` [C] |
| tests | high-register `mov r8,r0` (0x4680) in the stepper + `pt_regs +0x20` r8 slot — 39 OK |

## 2. Implemented

* `e0493_trace` hooks at `0x04031AB6`, `0x04031BDE`, `0x04031BE8`, `0x04031A0C`,
  `0x04031A42`, `0x04031A68`, `0x04031AA8`, `0x0403FEA0`, `0x0403609C`, recording
  `r0/r4/r7/r8/SP/LR` and the `[SP+0x20]` slot.
* `_dl_start`/`_dl_start_final` disassembly of the `r8` producer and consumer.
* Two unit tests: stepper high-register `mov r8, r0` (encoding `0x4680`) and the
  `pt_regs +0x20 == r8` restoration slot.

## 3. Next step

1. **Force the user bank for the recovery replay:** before `_step_user_thumb_insns` in the
   recovery branch, set `CPSR` to `USR|Thumb` **and** write `SP_usr` from the current
   `pt_regs` frame (not the live kernel `SP`), then step. Verify the `0x04031AB6` store
   lands at `0x5E864F10 + 0x20` and that `0x04031BDE` reads `0x5E864F10`.
2. Re-run: expect `r8 = 0x5E864F10` at `0x04031A42`, the `0x0403D6A8`/`0x0403D6B2`
   `argc` read to succeed, and the loader to continue to `dl_main`/BusyBox `_start`.
3. Then check `svc_hits` (deferred dispatch is live) and capture the live `/bin/ash`
   prompt over `ttyAM0`.
