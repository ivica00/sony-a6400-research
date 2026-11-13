# E0463 — SPSR-tail capture + manual user restore: first true Thumb `USR` entry at `0x0402E790`

Date: 2026-11-13. **Strictly offline.** No camera access, no USB command, no mode switch,
no firmware write. Inputs: E0414 dumps, E0416 contract, E0417 IRQ model, E0420–E0462.
Labels: **[C]** confirmed from artifacts/tests, **[I]** inference.

## 0. Short answer

1. **The user return is captured [C].** At `0x6010DF50` (`msr spsr_fsxc, r1`) the hook
   records `pending_user_spsr = r1` and `pending_user_lr = lr` when `(r1 & 0x1F) == 0x10`.
   Live: **`spsr = 0x00000030`** (USR+Thumb), **`lr = 0x0402E790`** (ld.so entry) — so the
   kernel's own frame is correct and the even-PC-with-`T` case is real.
2. **The manual restore works [C].** At `0x6010DF64` (`movs pc, lr`) the hook restores
   `r0..r12` from the frame, writes `CPSR = pending_user_spsr`, `SP/LR` from the frame
   (`+0x34`/`+0x38`) and `PC = thumb_pc(pending_user_lr, spsr)`. Keeping the pending values
   across returns (`user_restores = 2`) yields the **first genuine user-mode execution via
   the deferred virtual-TLB path**:
   `user_mode_entries = 1` at **`pc = 0x0402E790`, `cpsr = 0x30`** (Thumb, USR), and
   **`kuser_hits = 3`**.
3. **New blocker: Thumb decode at `0x0402E798` [C].** The run then reports
   `pc 0x0402E798`, `kind=prefetch`, `UC_ERR_INSN_INVALID`, followed by a data fault at
   `0x0402E79C` and stop `PC = 0x0402E79C` (`serial 0 B`, `svc_hits = 0`). File bytes at the
   entry are `dff868a0 dff86840 6846 03f0 85f9…`, which capstone decodes as
   `ldr.w sl,[pc,#0x68]` / `ldr.w r4,[pc,#0x68]` / `mov r0,sp` / `bl …` — all valid Thumb,
   so the invalid-instruction result points at **Unicorn's Thumb/PC-LSB state after the
   emulated exception return** (likely the CPU executed at `0x0402E798` in a state where the
   halfword is not decoded as Thumb), not at the file contents.
4. **No shell yet [C]:** `svc_hits = 0`, `serial 0 B`.

## 1. Evidence

| item | value |
| --- | --- |
| `0x6010DF50` capture | `spsr 0x30`, `lr 0x0402E790` [C] |
| restore hook | `r0-r12` + `SP_usr`/`LR_usr` from frame, `CPSR = spsr`, `PC = thumb_pc(lr)` [C] |
| `user_restores` | 2 (pending values kept across returns) [C] |
| `user_mode_entries` | **1**, `pc 0x0402E790`, `cpsr 0x30` [C] |
| `kuser_hits` | 3 [C] |
| next faults | `0x0402E798` INSN_INVALID, `0x0402E79C` data, stop `PC 0x0402E79C` [C] |
| ld.so entry bytes | `dff868a0 dff86840 6846 03f0 85f9…` = valid Thumb [C] |
| tests | pending defaults + `thumb_pc` (26 in `test_virtual_tlb.py`) — suite **1548 OK** |

## 2. Implemented

* `pending_user_spsr` / `pending_user_lr` capture hook at `0x6010DF50`
  (recorded in `ret_tail_trace` as `tag='msr50'`, not drowned by kernel returns).
* Restore hook at `0x6010DF64`: for `SPSR` mode `USR`, writes `r0..r12`, `CPSR = spsr`,
  `SP_usr`/`LR_usr` from the frame and `PC = thumb_pc(pending_user_lr, spsr)`;
  counter `user_restores` (report field).
* Unit test for the pending defaults and Thumb PC selection.

## 3. Next step

1. **Instrument the first user instructions** (`0x0402E790`, `0x0402E794`, `0x0402E798`)
   with a register/CPSR trace to see the exact mode/`T` state at `0x0402E798` and why
   Unicorn reports `UC_ERR_INSN_INVALID` for a valid Thumb halfword (decoder state after the
   manual exception return, IT-block state, or an odd/even PC mismatch).
2. If Unicorn's Thumb decode is wrong after the manual restore, set `PC = target` and
   `CPSR.T` in the order Unicorn expects (write `CPSR` last, or use an odd PC and let
   Unicorn derive `T`), or single-step the first two instructions.
3. Then verify `0x0402F666`/`0x04031AF0`, enable `svc_hits` (ld.so/BusyBox syscalls) and
   capture the live `/bin/ash` prompt over `ttyAM0`.
