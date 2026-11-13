# E0431 — Banked `^` (`SP_usr`/`LR_usr`) emulation, TLB refresh, userspace `/bin/ash`

Date: 2026-11-12. **Strictly offline.** No camera access, no USB command, no mode switch,
no firmware write. Inputs: E0414 dumps, E0416 contract, E0417 IRQ model, E0420–E0430 boot.
Labels: **[C]** confirmed from artifacts/tests, **[I]** inference.

## 0. Short answer

1. **Banked `^` transfer emulation added [C].** The kernel's user-fault handlers
   (`__pabt_usr` `0x6010DE20`, `__dabt_usr` `0x6010DC20`) build `pt_regs` with
   `stmdb r0, {sp, lr}^` (`usr_entry`, at handler+`0x1C`), which on real ARMv7 stores the
   **USR-bank** R13/R14. Unicorn shares R13/R14 across modes, so the machine now:
   * saves `mode_sp['usr']` and `mode_lr['usr']` when a user fault is delivered
     (before `LR` is overwritten with the corrected PC),
   * installs code hooks at `__pabt_usr+0x1C` / `__dabt_usr+0x1C` that write the saved
     **user SP/LR** into the `pt_regs` slots at `r0-8`/`r0-4` and skip the instruction.
2. **TLB refresh helper added [C].** `_flush_tlb()` calls Unicorn's TLB-flush API
   (`ctl_flush_tlb`, falling back to `UC_CTL_TLB_FLUSH`) and is invoked on every delivered
   user exception, so a page that `handle_mm_fault` newly maps is visible to the
   subsequent user retry.
3. **Live run: no user resumption yet [C].** With
   `init=/bin/ash console=ttyAM0,115200n8` the prefetch abort `0x0402e790`
   (IFSR `0x5`, user) is still delivered, 2 data aborts are executed, there is no Unicorn
   hard stop, and the run idles in the Sony exception monitor. The monitor dump now shows
   `CPSR 0x70` (USR/Thumb), `PC 0x0402e790`, but `SP = 0x00001fb0`, `LR = 0x7dc0ffb4` and
   `user_mode_entries = []` — i.e. the `pt_regs` SP/LR are still not the true user values,
   so either the banked-store hook did not fire on the executed path or a later
   `ret_to_user` restored from a different frame. No interactive shell claim.
4. **New tests [C]:** `test_banked_usr_store_uses_saved_user_registers` (writes
   `{SP_usr, LR_usr}` at the `pt_regs` slots and skips the instruction) and
   `test_flush_tlb_is_safe`.

## 1. Evidence

| item | value |
| --- | --- |
| banked store sites | `__pabt_usr+0x1C` (`0x6010DE3C`), `__dabt_usr+0x1C` (`0x6010DC3C`) |
| user-fault state captured | `mode_sp['usr'] = 0x5e864f10`, `mode_lr['usr'] = 0x0` |
| map-mode SPs | `mode_sp['svc'] = 0x7dc0ff68` (captured at `ret_to_user`) |
| live prefetch | `0x0402e790`, IFSR `0x5`, user `true` |
| live monitor dump | `PC 0x0402e790`, `CPSR 0x70`, `SP 0x1fb0`, `LR 0x7dc0ffb4` (user regs still wrong) |
| user-mode entries | `[]` |
| tests | banked `^` + TLB-flush tests — suite **1488 OK** |

## 2. Implemented

* `mode_lr` dict alongside `mode_sp`; user fault delivery stores `mode_sp['usr']` /
  `mode_lr['usr']`.
* `_emulate_banked_store(pc)` + code hooks at `__pabt_usr+0x1C` / `__dabt_usr+0x1C`:
  writes `{user SP, user LR}` to the `usr_entry` frame slots and advances PC by 4.
* `_flush_tlb()` (Unicorn `ctl_flush_tlb` / `UC_CTL_TLB_FLUSH` fallback), called on every
  delivered user fault.
* Tests: banked-store slot values + PC skip, TLB-flush safety.

## 3. Next step

1. **Verify the banked hook actually fires** on the executed handler path (add a hook-hit
   counter to the report); the monitor dump still shows SVC-derived SP/LR, so either the
   handler is entered through a different path than `__pabt_usr` or the hook PC is off by
   one instruction (Thumb/ARM state). This is the immediate blocker.
2. Trace `do_PrefetchAbort`/`ret_to_user` for `0x0402e790` and confirm the `pt_regs`
   slots (`ARM_sp 0x34`, `ARM_lr 0x38`, `ARM_pc 0x3C`) after `usr_entry`.
3. Then `user_mode_entries` should record `ld-2.11.2.so`/busybox execution, the
   `kuser_helpers`/`CPACR` checks apply only if touched, and the live `/bin/ash` prompt can
   be captured over the working bidirectional `ttyAM0`.
