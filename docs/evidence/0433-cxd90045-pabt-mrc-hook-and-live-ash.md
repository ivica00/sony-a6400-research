# E0433 — CP15 fault-register MRC hooks, real USER-mode execution, and the remaining fault path

Date: 2026-11-12. **Strictly offline.** No camera access, no USB command, no mode switch,
no firmware write. Inputs: E0414 dumps, E0416 contract, E0417 IRQ model, E0420–E0432 boot.
Labels: **[C]** confirmed from artifacts/tests, **[I]** inference.

## 0. Short answer

1. **The blocker is fixed: the kernel now sees the fault registers [C].**
   `unicorn_machine.py` saves `last_ifar/last_ifsr` on every delivered Prefetch Abort and
   `last_dfar/last_dfsr` on every delivered Data Abort, and installs code hooks on the
   verified CP15 read sites:
   * `v7_early_pabort`: `0x60119B60` (`mrc r0,c6,c0,2` → IFAR) and `0x60119B64`
     (`mrc r1,c5,c0,1` → IFSR),
   * `v7_early_abort`: `0x60119B44` (`mrc r1,c5,c0,0` → DFSR) and `0x60119B48`
     (`mrc r0,c6,c0,0` → DFAR).
   Each hook writes the saved value into `r0`/`r1`, counts a hit and skips the MRC.
2. **Userspace now really executes [C].** Live run
   (`init=/bin/ash console=ttyAM0,115200n8 --trace-user-mode`):
   * `pabt_mrc_hits = 212`, `dabt_mrc_hits = 6`, `prefetch_aborts_delivered = 106`
     (the `.text` pages of `ld-2.11.2.so` fault in iteratively);
   * **`user_mode_entries` is non-empty**: first entries are
     `pc = 0x0402E790`, CPSR `0x70` (**USR + Thumb**), continuing `0x0402E798`,
     `0x0402E79C`, … up to `0x04031AF0` — i.e. genuine user-mode instruction execution
     inside `/lib/ld-linux.2.so` (loaded at `0x0402e000+`), after the interpreter chain
     mapped by E0426/E0427.
3. **A new, later crash stops the run before the shell [C].** After the user-mode start the
   run hits `UC_ERR_EXCEPTION` at `PC = do_page_fault+0x34` (`0x60116DC8`) while the kernel
   was inside `die+0x78` (`0x601115C8`) handling an earlier oops; the secondary fault
   records `r0 = r4 = 0x30303736`, `r1 = 0x7dc0df38` (stack), `r2 = 0xd3` — corrupted
   `do_page_fault` arguments during the oops/die path. Serial is 0 B for this run (the
   console path is not exercised before the crash).
4. **No interactive `/bin/ash` yet**, but the fundamental entry into userspace is now
   proven: exec → interpreter → USR execution with demand paging. The next work is the
   kernel fault/die path for the remaining user faults, not the exec/ELF chain.

## 1. Evidence

| item | value |
| --- | --- |
| pabt hooks | `0x60119B60` IFAR→r0, `0x60119B64` IFSR→r1 (verified disassembly) |
| dabt hooks | `0x60119B44` DFSR→r1, `0x60119B48` DFAR→r0 (verified disassembly) |
| live counters | `pabt_mrc_hits=212`, `dabt_mrc_hits=6` |
| live prefetch | `106` delivered; last `0x04031AF0` (IFSR 5, user) |
| live data aborts | `3`: clear_user `0x48ac6` / `0x0404e85c`, then kernel `die+0x78` `0x30303736` |
| user-mode entries | first `0x0402E790` CPSR `0x70`; sequence through `0x0402E798..0x04031AF0` |
| stop | `unicorn_error` at `do_page_fault+0x34` (`0x60116DC8`), serial 0 |
| tests | IFAR/DFAR save-state tests — suite **1492 OK** |

## 2. Implemented

* `last_ifar/last_ifsr/last_dfar/last_dfsr` saved in `_deliver_prefetch_abort` /
  `_deliver_data_abort` (fix: save **before** the user-mode early-return branch).
* `_install_fault_mrc_hooks()` — four targeted code hooks that inject the saved fault
  registers into `r0`/`r1` and skip the MRC; `pabt_mrc_hits` / `dabt_mrc_hits` in the
  report; the native banked `ret_to_user` path is kept (restore hook stays disabled).
* Tests: `test_prefetch_delivery_saves_ifar_for_mrc_hooks`,
  `test_data_delivery_saves_dfar_for_mrc_hooks`.

## 3. Next step

1. **Trace the remaining fault path**: the run reaches USR execution and then an oops
   (`die+0x78`) with a secondary fault in `do_page_fault` at address `0x30303736`.
   Capture `do_page_fault` entry/return (`0x60116D94`) for the user fault that kills the
   process (which VMA/`VM_FAULT_*`, and whether it is a vmalloc/user-copy fault that must
   use the exception table instead of page-fault handling).
2. Fix the kernel-mode Data Abort delivery for that case (the current delivery injects
   `last_dfar/last_dfsr`, but the `die`/`do_page_fault` argument frame is corrupted), so
   the process gets a clean signal instead of a nested emulator fault.
3. Once the fault path is clean, the already-working world (`exec` → `ld.so` → USR code)
   should reach BusyBox `_start` (`0x8000+`), and the bidirectional `ttyAM0` captures the
   live `/bin/ash` prompt and command output.
