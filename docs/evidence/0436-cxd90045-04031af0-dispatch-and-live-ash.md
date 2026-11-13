# E0436 — `0x04031AF0` instruction, abort accounting, SWI dispatch and the persist

Date: 2026-11-12. **Strictly offline.** No camera access, no USB command, no mode switch,
no firmware write. Inputs: E0414 dumps, E0416 contract, E0417 IRQ model, E0420–E0435.
Labels: **[C]** confirmed from artifacts/tests, **[I]** inference.

## 0. Short answer

1. **`0x04031AF0` is a plain data load, not a syscall/kuser/VFP opcode [C].**
   `ld-2.11.2.so` is loaded at `0x0402E000` (entry `0x791` → first user PC `0x0402E790`,
   PT_LOAD vaddr `0x0`), so VA `0x04031AF0` = **file offset `0x3AF0`**. Thumb disassembly:
   `0x04031AF0  ldr r3, [r1, r0]` — a GOT/rodata-style load inside ld.so's relocation /
   dynamic-linker path. No `svc`, no `blx 0xffff0fe0`, no VFP/NEON instruction.
   The fault is therefore a **memory fault on a data address that happens to equal
   `0x04031AF0`** (r1 + r0 resolving to the same address), not an exception-instruction
   dispatch issue.
2. **Abort accounting fixed [C].** SVC-mode `__dabt_svc` deliveries now increment
   `data_aborts_delivered` and append a trace entry with `'svc': True` (previously the
   run reported `aborts = 0`). Baseline run now reports `aborts = 3`, `prefetch = 106`.
3. **SWI dispatch implemented but gated off [C].** `_on_interrupt` emits real ARM SWI
   semantics (switch to SVC, `LR_svc = pc+4`, `SPSR_svc = old CPSR`,
   `PC = 0xFFFF0008` = `vector_swi`) and is unit-tested. However, **enabling the
   `UC_HOOK_INTR` hook regressed the boot**: a 2.5B-instruction run stalled in
   `cmpxchg_futex_value_locked+0x50` (`0x6015BDCC`) with `svc_hits = 0`,
   `user_entries = 0`, `prefetch = 0`, `aborts = 0` — the hook never fired, so the
   regression is an interaction with the existing ABT/futex fault path, not a syscall
   classification problem. The hook is installed only when
   `enable_svc_dispatch = True` (default off).
4. **With the hook gated off the E0435 baseline is reproduced [C]:** 320M-instruction
   run: `user_entries = 20` (starting `0x0402E790`, CPSR 0x70, through `0x04031AF0`),
   `prefetch = 106`, `aborts = 3`, stop `do_page_fault+0x34` (`0x60116DC8`); no shell,
   serial 0 B.

## 1. Evidence

| item | value |
| --- | --- |
| ld.so base | `0x0402E000`, entry `0x791` [C] |
| VA `0x04031AF0` | file offset `0x3AF0`; Thumb `ldr r3, [r1, r0]` [C] |
| accounting fix | SVC-mode data aborts counted + traced (`svc: True`); run now `aborts=3` [C] |
| SWI dispatch | `_on_interrupt`: CBC → SVC, `LR=pc+4`, `SPSR=old CPSR`, `PC=0xFFFF0008`; unit-tested [C] |
| SWI hook effect | enabled: 2.5B run stuck in `cmpxchg_futex_value_locked+0x50`, `svc_hits=0` → gated off [C] |
| regression check (320M) | user 20, prefetch 106, aborts 3, stop `do_page_fault+0x34` [C] |
| tests | 3 new tests — suite **1497 OK** |

## 2. Answer to the E0435 clues

* The `Oops: 80000005` bit 31 (`0x80000000`) and the unaligned `pgd = 7f146dd8` show the
  kernel's `do_page_fault` was entered with a **pt_regs/SP context that does not belong to
  the faulting task** — `current_thread_info()` derived from a mismatched kernel stack.
  With `0x04031AF0` proven to be a load (`ldr r3, [r1, r0]`), the fault is a normal
  demand-page fault on the ld.so data/VMA, and the kernel misclassifies it as a
  kernel-mode fault because the delivered SVC-mode `pt_regs`/stack context is wrong.
* The SWI/GOT/kuser/VFP hypotheses are excluded by the disassembly; the remaining
  suspect is the **SVC-mode `__dabt_svc` context construction** (r2 saved-SP slot /
  frame layout) or the user→SVC stack switch on the user fault delivery.

## 3. Next step

1. Trace `do_page_fault` (`0x60116D94`) entry (`r0/r1/r2`) and the `r2` saved-SP slot of
   `__dabt_svc` for the fault at `0x04031AF0`; verify the kernel stack (`SP & ~0x1FFF`)
   belongs to the ld.so task and not to a stale/foreign stack.
2. Correct the SVC-mode delivery frame (`r2` value and LR semantics) or the user→SVC
   stack switch so `current_thread_info()` resolves the real task; then re-run.
3. Debug why installing the `UC_HOOK_INTR` hook perturbs the futex/ABT path before
   re-enabling SWI dispatch; then continue through `ld-2.11.2.so` → BusyBox `_start`
   (`0x0000C439`) → live `/bin/ash` over `ttyAM0`.
