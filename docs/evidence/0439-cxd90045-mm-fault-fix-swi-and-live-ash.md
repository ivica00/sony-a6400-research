# E0439 — `do_page_fault` prologue, the two kernel stacks, and why the 16th fault dies at `0x60116DC8`

Date: 2026-11-12. **Strictly offline.** No camera access, no USB command, no mode switch,
no firmware write. Inputs: E0414 dumps, E0416 contract, E0417 IRQ model, E0420–E0438.
Labels: **[C]** confirmed from artifacts/tests, **[I]** inference.

## 0. Short answer

1. **`do_page_fault` prologue decoded from the image [C].**
   `0x60116D94 mov ip,sp; push {r4..lr,pc}; sub fp,ip,#4; sub sp,#0xc;`
   `0x60116DA8 mov r1,sp; 0x60116DAC bic r3,r1,#0x1fc0; bic r3,r3,#0x3f;`
   `0x60116DB8 ldr r2,[r2,#0x40]` (`pt_regs->ARM_cpsr`); `0x60116DC0 ldr r6,[r3,#0xc]`
   (**`thread_info->task` from `SP & ~0x1FFF`**); `0x60116DC4 tst r2,#0x80`
   (`user_mode`/`IRQ`-mask bit test); `0x60116DC8 ldr r7,[r6,#0xcc]` (**`task->mm`**,
   the instruction where the final run dies).
2. **Root cause of the `0x60116DC8` crash is a foreign kernel stack [C].**
   The crash registers from the live run are
   `SP = 0x7dc0DF38`, `r3 = 0x7DC0C000` (thread_info base computed from that SP),
   `r6 = 0` → `ldr r7,[r6,#0xcc]` faults at `0x000000CC`.
   The user-fault delivery used `mode_sp['svc'] = 0x7DC0FFB0`, whose thread_info base is
   `0x7DC0E000`. So two different 8 KB kernel stacks are in play:
   * `0x7DC0E000` — the stack captured at `ret_to_user` (used by our emulated
     `vector_stub` delivery);
   * `0x7DC0C000` — the stack on which the final fault actually ran (thread_info zero).
   `thread_info->task` at `0x7DC0C000+0xC` is 0, so `current` becomes NULL and
   `do_page_fault` dereferences `NULL+0xCC` — that is the "secondary fault", not a
   demand-page failure.
3. **The "16 repeats at `0x04031AF0`" are retries across these mismatched stacks [I].**
   The page itself may well be installed; the loop is the kernel re-entering
   `do_page_fault` with a stack whose `thread_info` does not belong to the faulting task,
   so the VMA/`mm` lookup is wrong and the fault is retried until the NULL deref.
   The fix is therefore **SVC-stack freshness**, not the cramfs/PTE path
   (consistent with E0438 ruling out TLB staleness).
4. **Actionable fix [I]:** refresh `mode_sp['svc']` at **every** kernel→user return
   (`ret_to_user` hook already installed for TLB flush) and, in
   `_deliver_user_exception`, prefer the *current live* `SP_svc` (the SVC bank the kernel
   is actually using) rather than a value captured once; additionally validate that
   `thread_info` at `SP & ~0x1FFF` has a non-zero `task` before delivering. When the
   correct stack is used, `do_page_fault` reads the real `task->mm` and the
   `0x04031000` page can be demand-paged.

## 1. Evidence

| item | value |
| --- | --- |
| `do_page_fault` prologue | `SP & ~0x1FFF` → thread_info; `+0xC` → task; `task+0xCC` → mm [C] |
| last-fault crash | `PC 0x60116DC8`, `SP 0x7DC0DF38`, `r3 0x7DC0C000`, `r6 0`, fault `0xCC` [C] |
| delivery stack | `mode_sp['svc'] = 0x7DC0FFB0` (thread_info base `0x7DC0E000`) [C] |
| stack mismatch | `0x7DC0C000` vs `0x7DC0E000` → two 8 KB stacks [C] |
| user fault frame | `ARM_pc 0x04031AF0`, `ARM_cpsr 0x70` (USR), `ARM_sp 0x5E864C70`, `ARM_lr 0x0402E79F` [C] |
| TLB | Case A excluded in E0438 (`tlb_flushes=253`, loop persists) [C] |
| SWI | Thumb-aware `LR=pc+2`/`+4`, SVC `0x13|0x80`, INTR abort re-dispatch implemented (E0438), gate still off [C] |

## 2. Answers to the E0439 questions

* **`handle_mm_fault` return:** not yet measured — the run never reaches it on the final
  entry because `do_page_fault` faults earlier (NULL `task->mm`). The measured failure is
  *before* any VMA/PTE decision, which is why E0438's TLB flush and the file/`cramfs`
  hypotheses showed no change.
* **L1/L2 PTE walk for `0x04031000`:** deferred; with `task->mm = NULL` there is no valid
  `mm->pgd` to walk for that entry. The earlier 16 frames show `r2` (`pt_regs`) valid, so
  the mismatch is purely the kernel-stack/thread_info derivation.
* **Sequence of 16 entries:** they are **re-entries of `do_page_fault`** on inconsistent
  kernel stacks (the stack base alternates between `0x7DC0C000` and `0x7DC0E000`), not a
  simple USR retry loop.
* **SWI:** `_on_interrupt` is fully implemented (E0438) and unit-tested; enabling it is
  pending the stack fix because without a valid `current` the `vector_swi` path would
  also crash on `sys_*` (`current_thread_info`).

## 3. Next step

1. **Stack freshness fix:** update `mode_sp['svc']` in the `ret_to_user` hook (every
   return), validate `thread_info->task != 0` in `_deliver_user_exception`, and if
   invalid fall back to the live SVC bank / skip delivery with a logged error.
2. Re-run 320M: expect either `do_page_fault` to read a valid `task->mm` and the
   `0x04031000` page to be installed (then BusyBox `_start`), or a new, honest blocker.
3. Then capture `handle_mm_fault` return + L1/L2 PTE for `0x04031000` if needed, enable
   `enable_svc_dispatch` (SWI + INTR abort re-dispatch), record `svc_hits` for ld.so
   syscalls, and continue to live `/bin/ash` over `ttyAM0`.
