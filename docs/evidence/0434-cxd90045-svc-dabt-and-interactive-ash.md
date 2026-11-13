# E0434 — First oops after `ld-2.11.2.so`, SVC-mode abort delivery and kuser helpers

Date: 2026-11-12. **Strictly offline.** No camera access, no USB command, no mode switch,
no firmware write. Inputs: E0414 dumps, E0416 contract, E0417 IRQ model, E0420–E0433 boot.
Labels: **[C]** confirmed from artifacts/tests, **[I]** inference.

## 0. Short answer

1. **The first oops is isolated [C].** After the last recorded user PC
   (`0x04031AF0`, inside `ld-2.11.2.so`), the kernel log shows:
   `Unable to handle kernel paging request at virtual address 04031af0`,
   `pgd = 7f146dd8`, `[04031af0] *pgd=00000003(bad)`,
   `Internal error: Oops: 80000005 [#1] PREEMPT SMP`.
   That is a **kernel-mode access to a user VA whose page tables are not the current
   ones** (`*pgd = 0x3`, an invalid/foreign pgd — the kernel is walking `init_mm`, not
   PID-1's mm), so `do_page_fault` rejects it and enters `die()`. The subsequent nested
   fault at `do_page_fault+0x34` (`0x60116DC8`) is a secondary crash while `die()` prints.
2. **The likely cause is the SVC-mode Data Abort delivery path [C]/[I].** User-mode faults
   use the emulated `vector_stub` (scratch frame, SVC stack, direct `__dabt_usr`/
   `__pabt_usr` entry). **Kernel-mode** data aborts still go through the hardware ABT
   vector `0xFFFF0010`, whose `SP_abt` 12-byte scratch and `__dabt_svc` entry are not
   modelled faithfully by Unicorn; the resulting `pt_regs`/arguments can be wrong, so
   `do_DataAbort`/`do_page_fault` progresses with a bad mm/pgd and oopses instead of
   demand-paging the user page.
3. **Hardening added [C].**
   * `demand_page_helpers` now also includes `strncpy_from_user`, `strnlen_user`,
     `copy_from_user`, `copy_to_user`, `__get_user`, `__put_user` — user-pointer
     syscalls that hit demand-paged buffers are routed to `do_DataAbort` first.
   * **kuser helpers implemented**: `0xFFFF0FA0` (memory barrier), `0xFFFF0FC0`
     (cmpxchg), `0xFFFF0FE0` (get_tls), `0xFFFF0FFC` (helper version) are emulated,
     return to `LR`, and are counted (`kuser_hits`, `kuser_entries`). In this run
     `kuser_hits = 0`: ld.so had not reached a kuser call before the oops.
4. **No interactive shell yet.** User-mode execution and demand paging are proven
   (E0433), but the run still dies on the SVC-mode fault path. `serial = 0 B` in this run
   (the oops happens at kernel time 142.5, before any ttyAM0 output was replayed).

## 1. Evidence

| item | value |
| --- | --- |
| last user PCs | `0x04031AF0` region (ld-2.11.2.so), CPSR 0x70 |
| first oops | `Unable to handle kernel paging request at virtual address 04031af0` |
| pgd state | `pgd = 7f146dd8`, `[04031af0] *pgd=00000003(bad)` |
| oops code | `Internal error: Oops: 80000005 [#1] PREEMPT SMP` |
| secondary crash | `do_page_fault+0x34` (`0x60116DC8`) during `die()` |
| user copy helpers | whitelist extended with `strncpy_from_user`/`copy_to_user`/`__get_user`/`__put_user`/`__put_user` |
| kuser helpers | emulated at `0xFFFF0FA0/FC0/FE0/FFC`; `kuser_hits = 0` this run |
| run counters | `pabt_mrc_hits=212`, `dabt_mrc_hits=6`, 106 prefetch aborts, 3 data aborts |
| tests | user-copy whitelist test — suite **1493 OK** |

## 2. Implemented

* `demand_page_helpers` extension for user-pointer syscall copy helpers.
* `_install_kuser_hooks()` with cmpxchg/get_tls/barrier/helper-version emulation and
  `kuser_hits`/`kuser_entries` reporting; `tls_value` state placeholder for TPIDRURO.
* Test: `test_user_copy_helpers_are_demand_page_whitelisted`.

## 3. Next step

1. **Emulate the vector-stub entry for SVC-mode data aborts** (as already done for USR):
   on a kernel-mode fault with a user VA, write the 12-byte `{r0, lr, spsr}` scratch
   frame, keep the SVC SP, and jump directly to `__dabt_svc` (`0x6010D980`) with
   `r0 = scratch` (and `__pabt_svc` `0x6010DBA0` for prefetch), so `__dabt_svc` builds a
   correct `pt_regs` and `do_DataAbort` sees the right mm/pgd before `do_page_fault`.
2. Re-run and confirm the `*pgd=00000003(bad)` oops disappears and the user page is
   demand-paged; then check kuser/TLS only if ld.so calls them.
3. Capture the live `/bin/ash` prompt over the bidirectional `ttyAM0`.
