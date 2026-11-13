# E0437 — `do_page_fault` `pt_regs` frame, kernel-VA translation fix and the repeated `0x04031AF0` prefetch

Date: 2026-11-12. **Strictly offline.** No camera access, no USB command, no mode switch,
no firmware write. Inputs: E0414 dumps, E0416 contract, E0417 IRQ model, E0420–E0436.
Labels: **[C]** confirmed from artifacts/tests, **[I]** inference.

## 0. Short answer

1. **`do_page_fault` frame capture implemented [C].** A code hook at `do_page_fault`
   (`0x60116D94`) records `r0` (addr), `r1` (fsr), `r2` (`pt_regs *`), `SP`, `CPSR` and
   the 18-word `pt_regs` image; report field `do_page_fault_frames`.
2. **Found and fixed a real emulator bug: kernel VAs were not translated for
   `mem_read`/`mem_write` [C].** Kernel stacks/`pt_regs` live at `0x60000000+`
   (`PAGE_OFFSET`), but Unicorn's `mem_read`/`mem_write` use the physical address space.
   `_emulate_banked_store` wrote the saved USR SP/LR to the *untranslated* VA, so
   `pt_regs->ARM_sp` was garbage (previously `0x04031AF0`). After translating
   (`_kernel_phys`), the captured frame is correct:
   `ARM_pc = 0x04031AF0`, `ARM_cpsr = 0x00000070` (**USER**),
   `ARM_sp = 0x5e864c70` (valid user stack), `ARM_lr = 0x0402E79F`.
3. **The `0x04031AF0` fault is a user instruction-prefetch fault on a new page [C].**
   Frames show `r0 = addr = 0x04031AF0`, `r1 = 0x80000005` (FSR translation + Linux
   prefetch flag), `ARM_cpsr = 0x70` → `do_page_fault` correctly sees `user_mode(regs)`.
   The page (`0x04031000`, second page of ld.so's first PT_LOAD) is not made present:
   `do_page_fault` is entered **16 times** for the same address and the run then dies in
   the secondary fault at `do_page_fault+0x34` (`0x60116DC8`). So the "kernel paging
   request" oops is a *nested* fault during repeated handling, not a misclassified user
   fault.
4. **SWI gating: strict `intno == 2` filter is implemented [C] but the hook remains
   gated off.** New unit test proves `_on_interrupt` ignores `intno` 3/4/5. The earlier
   boot regression is now explained: registering `UC_HOOK_INTR` makes Unicorn route
   exceptions to the hook **instead of** raising `UC_ERR_EXCEPTION`, so data/prefetch
   aborts (`intno` 3/4) never reach the machine's fault-delivery path. Strict filtering
   alone cannot fix that; the hook must also re-dispatch abort intnos. `enable_svc_dispatch`
   stays `False` by default.

## 1. Evidence

| item | value |
| --- | --- |
| frame hook | `do_page_fault` `0x60116D94`; 16 frames captured |
| fault #3 history | addr `0x04031AF0`, fsr `0x80000005`, `ARM_pc 0x04031AF0`, **`ARM_cpsr 0x70` (USR)**, `ARM_sp 0x5E864C70`, `ARM_lr 0x0402E79F` |
| earlier frames | exec-BSS writes `0x48AC6`/`0x0404E85C` (fsr `0x805`, SVC, correct kernel frames) |
| root cause of bogus frames | missing VA→PA translation in `_emulate_banked_store` (+ `_emulate_banked_restore`) |
| repeated handling | same `0x04031AF0` prefetch handled 16×, then `do_page_fault+0x34` secondary fault |
| run counters | user entries 20 (`0x0402E790..0x04031AF0`), prefetch 106, aborts 3, kuser 0, svc 0, serial 0 B |
| SWI filter test | `intno` 3/4/5 leave PC/CPSR untouched, `svc_hits == 0` |
| tests | frame capture + intno filter tests — suite **1499 OK** |

## 2. Implemented

* `_capture_fault_frame` + `do_page_fault_frames` report field (VA→PA translated).
* `_kernel_phys(va)` and its use in `_emulate_banked_store` / `_emulate_banked_restore`.
* `_on_interrupt` strict `intno == 2` dispatch retained (gated by `enable_svc_dispatch`).

## 3. Next step

1. **Why is the `0x04031000` page never made present?** Trace `handle_mm_fault` /
   `__do_page_fault` (`0x60116D94`) return value for the user prefetch fault, and the
   VMA lookup for `0x04031AF0` (ld.so first PT_LOAD, file-backed). Repeated faults with a
   correct user `pt_regs` point to a failed file/PTE path or a stale Unicorn TLB entry;
   check the PTE store (`set_pte_ext`) and TLB maintenance (`flush_tlb_*`, CP15 c8).
2. Once the page is demand-paged, continue to BusyBox `_start` (`0x0000C439`).
3. Re-enable SWI only after `_on_interrupt` also re-dispatches `intno` 3/4 aborts (the
   hook suppresses Unicorn's `UC_ERR_EXCEPTION` for them), then capture live `/bin/ash`.
