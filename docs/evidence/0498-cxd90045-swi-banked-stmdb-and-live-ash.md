# E0498 — Pre-switch `SP_usr`/`LR_usr` capture + single-shot banked `stmdb`: after `brk`, user code now re-enters in `USR` and reaches `0x0403EB22`

Date: 2026-11-13. **Strictly offline.** No camera access, no USB, no writes. Inputs: E0414
dumps, E0416 contract, E0420–E0497 offline chain, the read-only dump set in
`artifacts/dumps/a6400-nflasha-readonly/` (full `/proc/kallsyms`).

## 0. Short answer

1. **The E0497 ordering bug is fixed [C].** In `_on_interrupt` (`intno == 2`) the user bank
   values are now captured **before** any `CPSR` write:
   `_pending_swi_usr_sp = SP_usr`, `_pending_swi_usr_lr = LR_usr`
   (only for a user PC `0x1000..0x60000000` with `(cpsr & 0x1F) == 0x10`), then
   `CPSR = (cpsr & ~0x3F) | 0x93` (`SVC|ARM`), `SPSR_svc = (cpsr & ~0x3F) | 0x30`
   (`USR|Thumb`), `LR_svc = _svc_return_address(...)`, and `PC = vector_swi`
   (`0x6010DFA0`; symbol resolved, fallback address).
2. **The banked `stmdb r8,{sp,lr}^` at `0x6010DFB0` is emulated once per syscall [C].**
   `_emulate_vector_stmdb()` writes the captured `SP_usr` to `pt_regs + 0x34`
   (`[r8-8]`) and `LR_usr` to `+0x38` (`[r8-4]`), clears the pending pair (so a second
   hit is a no-op) and the hook advances `PC = 0x6010DFB4` (`mrs r8, spsr`).
   Live trace: **exactly one** `vector_stmdb` entry per syscall —
   `r8 = 0x7DC0FF5C`, **`sp_usr = 0x5E864C04`**, **`lr_usr = 0x0403E98D`** (the previous
   kernel-stack `0x7DC0FF68` is gone).
3. **User execution resumes correctly after `brk` [C].** The fault classification after
   the syscall shows the user epilogue/next-function page (`0x0403E980`, `0x0403EB22`)
   being executed and a **decoded data abort at `0x0403EB22` with address
   `0x5E865030`** — a real user stack address (demand-pageable), no longer the bogus
   `VA 0x8`. The run ends at `instruction_limit` (`PC 0x6025ED38`).
4. **Still no shell [C]:** `svc_hits = 1` (`brk`, `r7 = 45`), `serial 0 B`,
   `gen = 15`, `rec = 1`, `restores = 8`, `entries = 20` — the loader is now past the
   syscall epilogue but has not yet reached the next syscalls.

## 1. Evidence

| item | value |
| --- | --- |
| pre-switch capture | `_pending_swi_usr_sp/_lr` set before `CPSR` write [C] |
| SVC entry | `CPSR = 0x93` (`SVC|ARM`), `SPSR_svc = 0x30`, `LR = 0x0403EB16`, `PC = 0x6010DFA0` [C] |
| banked stmdb | single-shot; `pt_regs +0x34 = 0x5E864C04`, `+0x38 = 0x0403E98D` [C] |
| trace | `e0497_trace`: one `vector_stmdb` with `r8 = 0x7DC0FF5C` [C] |
| post-syscall | user pages `0x0403E980` / `0x0403EB22` execute; decoded data abort at `0x0403EB22` address `0x5E865030` [C] |
| run | `instruction_limit` `PC 0x6025ED38`, `svc_hits 1`, `serial 0 B` [C] |
| tests | `test_swi_captures_user_bank_before_switch`, `test_vector_stmdb_is_single_shot_into_ptregs`; 43 in `test_virtual_tlb` [C] |

## 2. Implemented

* `_on_interrupt`: pre-switch user-bank capture, `SPSR_svc = USR|Thumb`, `LR_svc` via
  `_svc_return_address`, direct `vector_swi` entry (symbol resolved from the dumped
  kallsyms).
* `_emulate_vector_stmdb()`: one-shot banked `stmdb r8,{sp,lr}^` into the kernel-built
  `pt_regs` (`+0x34`/`+0x38`), plus `vector_stmdb` trace.
* Two unit tests for the capture order and the single-shot write.

## 3. Next step

1. Trace the next faults (`0x0403E980`, `0x0403EB22`) with the register set to see the
   next missing piece (demand-page path for the `0x5E865030` read, or the next
   recovery/pop form).
2. Confirm the loader proceeds to further syscalls (`uname`, `open`, `mmap2`,
   `set_tls`, `write`, `read`), BusyBox `_start 0x0000C439`, and the live `/bin/ash`
   prompt over `ttyAM0`.
