# E0473 — Top-of-classifier Thumb recovery fires: execution passes `0x04031AAC` for the first time

Date: 2026-11-13. **Strictly offline.** No camera access, no USB command, no mode switch,
no firmware write. Inputs: E0414 dumps, E0416 contract, E0417 IRQ model, E0420–E0472.
Labels: **[C]** confirmed from artifacts/tests, **[I]** inference.

## 0. Short answer

1. **The recovery branch now fires [C].** Moving the gate off the reported CPSR mode and
   only requiring a userspace VA, an `INSN` message and a resident page
   (`_should_recover_insn_invalid`) makes the `0x04031AAC`
   `UC_ERR_INSN_INVALID` fault go through
   `_step_user_thumb_insns(pc, (cpsr & ~0x3F) | 0x30, max_steps=6)`:
   `insn_invalid_recoveries = 1`, and `user_entry_trace` shows the manual steps
   `rec:alu` `0x04031AAC`, `rec:ldr` `0x04031AB0`, `rec:alu` `0x04031AB4`,
   `rec:str` `0x04031AB6`, `rec:alu` `0x04031AB8`, `rec:mov` `0x04031ABA`.
2. **Execution advances far past the old stop [C].** Instead of stopping at
   `PC = 0x04031AB0`, the run proceeds: `user_mode_entries = 20`,
   `user_restores = 3`, `kuser_hits = 4`, and the loop ends only at the instruction limit
   (`stop_reason = instruction_limit`, `PC = 0x6025ED34`, 3.0 B instructions) instead of a
   user decode fault.
3. **New blocker [C]:** after the recovered block the user stream reaches `0x04031AEA`
   (prefetch fault) and then a decoded data fault with a **write to VA `0x28`**
   (`fault_classification_trace`: `pc 0x04031aea`, `address 0x00000028`, `kind data-decoded`,
   `write True`) — a small bogus pointer produced by the emulated register/flag state, not
   a page-mapping problem. No syscalls yet: `svc_hits = 0`, `serial 0 B`, no shell.
4. **Live recovery behaviour is stable across a longer budget [C].** The 3.0 B-instruction
   run has the same `insn_invalid_recoveries = 1`, `unsupported = []`, `entries = 20`,
   `kuser_hits = 4`, i.e. the recovery itself is deterministic; the remaining defect is the
   post-recovery register/flag state (or an instruction not yet modelled) around
   `0x04031AEA`.

## 1. Evidence

| item | value |
| --- | --- |
| recovery gate | `_should_recover_insn_invalid(pc, message)` — user VA + `INSN` + resident page, mode-independent [C] |
| recoveries | `insn_invalid_recoveries = 1`, `insn_invalid_unsupported = []` [C] |
| manual steps | `rec:alu/ldr/alu/str/alu/mov` at `0x04031AAC..0x04031ABA` [C] |
| user progress | `user_mode_entries = 20`, `user_restores = 3`, `kuser_hits = 4` [C] |
| old stop | was `PC 0x04031AB0` — now passed [C] |
| new blocker | `0x04031AEA` prefetch, then decoded data fault write VA `0x28` [C] |
| stop | `instruction_limit` (`PC 0x6025ED34`), `serial 0 B`, `svc_hits 0` [C] |
| tests | predicate test (mode-independent) — `test_virtual_tlb` 35 OK |

## 2. Implemented

* `_should_recover_insn_invalid(pc, message)` predicate and its use at the top of the
  fault classifier (before the prefetch/data delivery branches).
* Recovery path: forced `CPSR` USR+Thumb, `_step_user_thumb_insns(max_steps=6)`, page
  eviction (`ctl_remove_cache`) + `ctl_flush_tb()`, `_set_pc_and_cpsr(next_pc, next_cpsr)`,
  `insn_invalid_recoveries += 1`, `continue` (unsupported instructions recorded with
  pc/bytes/mnemonic).
* Unit test for the mode-independent gate.

## 3. Next step

1. **Trace the recovered block end-to-end:** log registers/`CPSR` after the manual steps and
   at `0x04031AEA`; the bogus pointer `0x28` suggests a wrong base register (likely from
   `push.w`/`sub.w sp` interaction or a flag-dependent conditional path). Verify `SP`
   after `push.w {r4-r11,lr}` + `sub.w sp,sp,#0x1f4` against the real ABI
   (`SP = entry - 36 - 0x1f4`), and that `rec:str` at `0x04031AB6` targets the intended
   frame slot.
2. Extend `_step_user_thumb_insns` with any mnemonic reported in
   `insn_invalid_unsupported` (none so far) and re-check `0x04031AEA`.
3. Then reach `0x0402F666`/`0x04031AF0`, enable `svc_hits` (ld.so/BusyBox syscalls), and
   capture the live `/bin/ash` prompt over `ttyAM0`.
