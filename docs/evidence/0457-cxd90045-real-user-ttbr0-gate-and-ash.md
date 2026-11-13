# E0457 — Real-user-return gate for deferred `UC_TLB_VIRTUAL`: user PGD captured

Date: 2026-11-13. **Strictly offline.** No camera access, no USB command, no mode switch,
no firmware write. Inputs: E0414 dumps, E0416 contract, E0417 IRQ model, E0420–E0456.
Labels: **[C]** confirmed from artifacts/tests, **[I]** inference.

## 0. Short answer

1. **The premature activation is fixed [C].** The deferred `ret_to_user` (`0x6010DF34`)
   switch now requires a **real user return**: it reads the stacked user `PC` at
   `[SP+0x3C]`, accepts only `0x1000 <= user_pc < 0x60000000`, and resolves a valid
   `current->mm->pgd` (`!= 0x00104000`). Kernel-thread/usermodehelper returns
   (`user_pc >= 0x60000000`, `mm == 0`) are skipped. The resolved pgd is stored as
   `_activation_pgd` and applied as `_cached_ttbr0` immediately after installing the
   virtual TLB.
2. **A real user PGD is captured [C].** The live run reports
   `virtual_tlb = True`, **`activation_pgd = 0x1F144000`**, and later TLB-fill samples for
   user addresses show **`ttbr0 = 0x1DC1C000`** — the real PID-1 user page directory from
   E0443 — proving the gate selects the correct transition and the fill hook now walks the
   **user** L1.
3. **Userspace was entered and ld.so started [C].** The classification trace shows the
   first user fetch fault at **`0x0402E790`** (ld.so entry), delivered to
   `__pabt_usr` (delivery trace `sp 0x7DC0FFF8`, `thread_info 0x7DC0E000`,
   task `0x7E36DBE0`), plus demand pages at `0x0402E400`; `tlb_fills = 96`,
   `prefetch_aborts_delivered = 1`, `aborts = 2`, `kuser_hits = 1`.
4. **New blocker: the user PC returns as `0x0` [C].** The run stops with
   `PC = 0x0` (instruction fetch at VA 0, `ttbr0 = 0x1DC1C000`), i.e. after the first
   userspace fault the return path resumes at address 0 instead of `0x0402E790`
   (or ld.so jumps to a null pointer). `svc_hits = 0`, `serial 0 B` — **no shell yet**.

## 1. Evidence

| item | value |
| --- | --- |
| gate | stacked user PC `[SP+0x3C]` in `0x1000..0x60000000` + valid `mm->pgd` [C] |
| activation | `activation_pgd = 0x1F144000`, `virtual_tlb = True` [C] |
| user TTBR0 | fill samples show **`0x1DC1C000`** for user VAs [C] |
| user entry | prefetch `0x0402E790` delivered, pages `0x0402E400` demand-faulted [C] |
| fills | `tlb_fills = 96`, `tlb_fill_misses = 3` [C] |
| new stop | **`PC = 0x0`** (VA-0 fetch), `svc_hits = 0`, serial 0 B [C] |
| tests | `_read32_phys` + `_activation_pgd` default (21 in `test_virtual_tlb.py`) — suite **1543 OK** |

## 2. Implemented

* `_read32_phys()` (kernel-VA → PA read).
* Deferred activation gate: stacked user PC check + `current->mm->pgd` resolution;
  `_activation_pgd` cached and applied as `_cached_ttbr0` at activation.
* Report field `activation_pgd`.

## 3. Next step

1. **Explain the `PC = 0x0` resume.** Compare the `pt_regs` frame written by
   `_deliver_user_exception` for the `0x0402E790` prefetch abort with the retry PC the
   kernel restores (`ARM_pc` slot), and check `do_PrefetchAbort`/`ret_to_user` restore
   path for a clobbered PC/LR (also inspect `mode_sp['usr']`/`tls_value` and the kuser
   helper return address).
2. Fix the return-PC restore (or the ld.so jump target) so execution continues at
   `0x0402E790`/next instruction, then verify `0x0402F666`/`0x04031AF0` translate and
   `svc_hits` records ld.so syscalls.
3. Capture the live `/bin/ash` prompt and command output over `ttyAM0`.
