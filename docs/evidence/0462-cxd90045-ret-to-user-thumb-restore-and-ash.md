# E0462 — `ret_to_user` tail disassembled; Thumb-aware restore helper added

Date: 2026-11-13. **Strictly offline.** No camera access, no USB command, no mode switch,
no firmware write. Inputs: E0414 dumps, E0416 contract, E0417 IRQ model, E0420–E0461.
Labels: **[C]** confirmed from artifacts/tests, **[I]** inference.

## 0. Short answer

1. **The real `ret_to_user` tail is decoded [C]** (`0x6010DF20..0x6010DFD0`,
   `nflasha1-vmlinux-decompressed.bin`, VA base `0x60108000` — ARM mode):

   ```
   0x6010DF34  bl   0x60117708
   0x6010DF38  cpsid i
   0x6010DF48  ldr  r1, [sp, #0x40]      ; user CPSR
   0x6010DF4C  ldr  lr, [sp, #0x3C]!     ; user PC -> LR, SP += 0x3C
   0x6010DF50  msr  spsr_fsxc, r1
   0x6010DF58  ldmdb sp, {r0-r12, sp, lr}^
   0x6010DF60  add  sp, sp, #0xC
   0x6010DF64  movs pc, lr               ; exception return (SPSR -> CPSR)
   ```

   So the final user return is **`movs pc, lr` at `0x6010DF64`** (not `ldmia ^`), and the
   earlier hook address `0x6010DF34` is a `bl` to a helper — which explains the kuser
   observation `lr = 0x6010DF38` (the return address of that `bl`, not a user LR).
2. **A Thumb-aware restore helper is implemented and unit-tested [C].**
   `thumb_pc(pc, cpsr)` returns `pc | 1` when `CPSR.T` (0x20) is set and `pc & ~1`
   otherwise, encoding the verified Unicorn rule that CPSR.T is coupled to the PC LSB
   (an even PC clears Thumb). The `0x6010DF64` hook now uses it when returning to `USR`.
3. **The hook has not yet seen a genuine user return [C].** The live run records
   `ret_tail_hits = 84`, but every traced tail hit is a **kernel** frame
   (`frame_cpsr 0x93` / `0x0`, `lr 0x6010EB84` / `0x60153D98`); no `frame_cpsr` with
   `& 0x1F == 0x10` (`USR`) was observed before the run stopped on the VA-0 fetch
   (`PC = 0x0`, `unicorn_error`). A follow-up `msr spsr_fsxc` diagnostic hook was written
   but introduced a syntax error and was removed again, so it produced no data.
4. **No behavioural change [C]:** `PC = 0x0`, `svc_hits = 0`, `kuser_hits = 1`, serial 0 B,
   no shell.

## 1. Evidence

| item | value |
| --- | --- |
| final return instruction | `movs pc, lr` @ `0x6010DF64` [C] |
| user PC load | `ldr lr, [sp, #0x3C]!` @ `0x6010DF4C` [C] |
| user CPSR load | `ldr r1, [sp, #0x40]` @ `0x6010DF48` [C] |
| helper | `thumb_pc(pc, cpsr)` -> `pc | 1` for Thumb [C] |
| tail hits | 84, all kernel frames (`cpsr 0x93`/`0x0`) [C] |
| stop | VA-0 fetch `PC = 0x0`, `svc_hits 0`, serial 0 B [C] |
| tests | Thumb `pc|1` and ARM LSB clear (25 in `test_virtual_tlb.py`) — suite **1547 OK** |

## 2. Implemented

* `thumb_pc(pc, cpsr)` static helper (Thumb LSB semantics).
* `UC_HOOK_CODE` at `0x6010DF64` that, for a `USR`-mode frame (`frame_cpsr & 0x1F == 0x10`),
  writes `CPSR = frame_cpsr` and `PC = thumb_pc(frame_pc or lr, frame_cpsr)`;
  counters `ret_tail_hits` / `ret_tail_trace` in the report.
* Two unit tests for the Thumb/ARM PC selection.

## 3. Next step

1. **Re-add the `msr spsr_fsxc` diagnostic hook** correctly (at `0x6010DF50`, record
   `r1` (user CPSR) and `lr` (user PC) for `(r1 & 0x1F) == 0x10`), and log the frame at
   `0x6010DF48`/`0x4C`/`0x58` to see the **user** return path — the current trace only
   shows kernel returns, so the user return either happens before the traced window or
   never reaches `0x6010DF64` in this run.
2. Confirm the frame `+0x3C` (user PC) is `0x0402E790` at `0x6010DF4C`; if it is `0`, the
   source is the earlier `ldmdb`/`stmdb ^` banked operations (E0431/E0432 hooks) rather
   than the final `movs pc, lr`.
3. Then apply the `thumb_pc` restore and verify `0x0402F666`/`0x04031AF0`, `svc_hits`
   and capture the live `/bin/ash` prompt over `ttyAM0`.
