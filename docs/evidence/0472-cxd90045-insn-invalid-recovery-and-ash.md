# E0472 — User-mode Thumb `UC_ERR_INSN_INVALID` recovery hook: implemented, not yet firing

Date: 2026-11-13. **Strictly offline.** No camera access, no USB command, no mode switch,
no firmware write. Inputs: E0414 dumps, E0416 contract, E0417 IRQ model, E0420–E0471.
Labels: **[C]** confirmed from artifacts/tests, **[I]** inference.

## 0. Short answer

1. **The recovery is implemented [C].** Inside the run-loop fault classifier, after
   `user_mode = (cpsr & 0x1F) == 0x10`, a branch now recognises
   `'INSN' in message` decode failures on a **resident** user page
   (`_user_pa(pc & ~1) is not None`) and calls
   `_step_user_thumb_insns(pc, cpsr | 0x20, max_steps=4)`; on success it records
   `insn_invalid_recoveries`, logs the manual steps into `user_entry_trace`
   (tag `rec:`), evicts the target page (`ctl_remove_cache(page, page+0x1000)`),
   calls `ctl_flush_tb()`, re-applies `_set_pc_and_cpsr(next_pc, next_cpsr)` and
   **continues** the loop instead of delivering a prefetch abort. On failure it records
   `insn_invalid_unsupported` with the exact `pc`, raw bytes and Capstone mnemonic.
2. **It has not fired in the live run yet [C].** The run still stops at
   `PC = 0x04031AB0` with `insn_invalid_recoveries = 0` and an empty
   `insn_invalid_unsupported`, while `fault_classification_trace` still shows
   `0x04031AAC` `Invalid instruction (UC_ERR_INSN_INVALID` → the inserted branch sits on a
   path that is **not taken** for that fault (the fetch/decode-failure path reaches the
   prefetch delivery before it), so the wiring point must be moved/duplicated.
3. **The stepper itself is ready for the callee block [C].** A new unit test executes
   `push.w {r4-r11,lr}` / `sub.w sp,sp,#0x1f4` / `ldr.w r3,[pc,#0x7c]` from `0x04031AA8`
   and asserts the trace `push, alu, ldr` and `PC = 0x04031AB4`, so the first three
   instructions of the callee would be handled once the hook is reached.
4. **The prologue-only live path is unchanged [C]:** manual `ldr/ldr/mov/bl` at
   `0x0402E790..0x0402E79A`, `user_restores = 3`, `user_mode_entries = 1`,
   `kuser_hits = 4`, execution reaches `0x04031AA8`, then the stop above.
   `svc_hits = 0`, `serial 0 B` — no shell.

## 1. Evidence

| item | value |
| --- | --- |
| recovery branch | implemented in run-loop classifier with page-resident gate [C] |
| live recoveries | `insn_invalid_recoveries = 0`, `insn_invalid_unsupported = []` [C] |
| classification | `0x04031AAC` `Invalid instruction (UC_ERR_INSN_INVALID` → prefetch delivery [C] |
| stepper callee test | `0x04031AA8`: `push, alu, ldr`, `PC 0x04031AB4` [C] |
| live stop | `PC = 0x04031AB0`, `serial 0 B`, `svc_hits 0` [C] |
| suite | `test_virtual_tlb` 34 OK |

## 2. Implemented

* `insn_invalid_recoveries` / `insn_invalid_unsupported` state and report fields.
* Recovery branch (decode-failure → `_step_user_thumb_insns` → page evict + flush →
  `_set_pc_and_cpsr` → continue).
* Unit test for the callee block (`push/sub/ldr`).

## 3. Next step

1. **Find the actual site that handles `0x04031AAC`:** add a temporary log at the
   `_deliver_prefetch_abort` call and at the top of the classifier to confirm which branch
   consumes the `UC_ERR_INSN_INVALID` message, then duplicate the recovery at that exact
   site (likely immediately before `if prefetch:`), keeping the resident-page gate.
2. Verify `insn_invalid_recoveries > 0` and that execution passes `0x04031AAC` into the
   callee, then extend the stepper if `insn_invalid_unsupported` reports an unhandled
   mnemonic (e.g. `it`/`uxt`/`orr` forms).
3. Then verify `0x0402F666`/`0x04031AF0`, `svc_hits`, and capture the live `/bin/ash`
   prompt over `ttyAM0`.
