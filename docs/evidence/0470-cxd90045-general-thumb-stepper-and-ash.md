# E0470 — General Thumb/Thumb-2 user stepper: implemented and unit-tested; all-resume trigger regressed and reverted

Date: 2026-11-13. **Strictly offline.** No camera access, no USB command, no mode switch,
no firmware write. Inputs: E0414 dumps, E0416 contract, E0417 IRQ model, E0420–E0469.
Labels: **[C]** confirmed from artifacts/tests, **[I]** inference.

## 0. Short answer

1. **The general stepper is implemented [C].** `_step_user_thumb_insns(pc, cpsr,
   max_steps=6)` is a bounded Capstone-driven Thumb/Thumb-2 interpreter covering
   `push`/`stmdb`, `pop`/`ldm` (including `pop {…,pc}` return), `mov`/`movs`,
   `add`/`sub` (including `sp`), `ldr`/`ldrb`/`ldrh` (PC-relative and register+offset),
   `str`, `cmp` (N/Z/C update), `b`/`b.w`, conditional `b<cond>` (via `insn.cc`),
   `cbz`/`cbnz`, `bl`/`blx` (`LR = next|1`), `bx`, and `nop`; it also has user-VA
   read/write helpers (`_read_user8/16/32`, `_write_user32`, `_user_pa` normalising the
   hex-string `pa` from `_walk_user_va`).
2. **Unit tests pass [C]:** `push.w {r4-r11,lr}` stores the register list and moves
   `SP -= 36` (task `0xAA` and `LR 0xBB` stored), and the ld.so prologue
   `ldr.w/ldr.w/mov/bl` steps to `PC 0x04031AA8` with `LR 0x0402E79F`
   (`test_virtual_tlb` now 33 tests OK).
3. **The all-resume trigger regressed the live path and was reverted [C].** Wiring the
   stepper on **every** user `ret_to_user` resume stopped the run at
   **`0x0402E794`** (data fault) with an **empty** `user_entry_trace` and
   `user_restores = 1` — i.e. the stepper's first-attempt failure path interfered with the
   normal demand-page delivery. The trigger was therefore returned to the E0469
   **prologue-only** form; a clean run reproduces the E0469 milestone:
   `user_entry_trace` = manual `ldr/ldr/mov/bl` at `0x0402E790..0x0402E79A`,
   `user_restores = 3`, `user_mode_entries = 1`, `kuser_hits = 4`, execution reaches
   `0x04031AA8`, then `UC_ERR_INSN_INVALID` at `0x04031AAC` and stop `PC = 0x04031AB0`.
4. **The automatic `UC_ERR_INSN_INVALID` recovery is not yet wired [C]:** the run loop's
   fault-dispatch path was not located with certainty inside the remaining budget, so the
   recovery hook is the next concrete step (see below). No shell: `svc_hits = 0`,
   `serial 0 B`.

## 1. Evidence

| item | value |
| --- | --- |
| stepper coverage | push/pop, mov(s), add/sub(sp), ldr/ldrb/ldrh, str, cmp, b/bcond, cbz/cbnz, bl/blx, bx, nop [C] |
| push test | `SP 0x2000 -> 0x1FDC`, r4/lr stored [C] |
| prologue test | `PC 0x04031AA8`, `LR 0x0402E79F`, trace `ldr,ldr,mov,bl` [C] |
| all-resume trigger | stop `0x0402E794`, trace empty, restores 1 — reverted [C] |
| live (prologue-only, kept) | manual prologue, `kuser_hits 4`, callee `0x04031AA8`, `INSN_INVALID` `0x04031AAC`, stop `0x04031AB0` [C] |
| shell | none (`serial 0 B`, `svc_hits 0`) |
| suite | **1560 tests OK** [C] |

## 2. Implemented

* `_step_user_thumb_insns()` general Thumb/Thumb-2 stepper (+ `_read_user8/16`,
  `_write_user32`, `_cond_true`, `_nz`, register-name map).
* Trigger kept prologue-only (E0469); the all-resume variant was measured and reverted.
* Two unit tests (push; prologue `ldr/mov/bl`).

## 3. Next step

1. **Locate the run-loop `UC_ERR_INSN_INVALID` delivery site and add recovery there:** when
   `pc < 0x60000000` and `(cpsr & 0x20)`, call `_step_user_thumb_insns(pc, cpsr)` with
   `max_steps=2..4`, `ctl_remove_cache(pc & ~0xFFF, +0x1000)`, `ctl_flush_tb()`, write the
   resulting `PC/CPSR` and continue the loop instead of delivering a prefetch abort.
   That covers `0x04031AAC` and every later demand-paged page (`0x0402F666`,
   `0x04031AF0`).
2. **Differential diagnosis of the all-resume regression:** log why the first
   `_step_user_thumb_insns` call fails (unmapped page before the demand fault) and only
   apply the stepper **after** the page is resident, so pages are not skipped.
3. Then verify `svc_hits` (ld.so/BusyBox syscalls) and capture the live `/bin/ash` prompt
   over `ttyAM0`.
