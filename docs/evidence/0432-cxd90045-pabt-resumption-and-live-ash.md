# E0432 — `do_PrefetchAbort` trace, banked `^` hook verification and the CP15 IFSR/IFAR blocker

Date: 2026-11-12. **Strictly offline.** No camera access, no USB command, no mode switch,
no firmware write. Inputs: E0414 dumps, E0416 contract, E0417 IRQ model, E0420–E0431 boot.
Labels: **[C]** confirmed from artifacts/tests, **[I]** inference.

## 0. Short answer

1. **Unicorn does model banked SP [C].** A direct test shows `SP_svc = 0x1111` and a
   separate `SP_usr` bank (`0x2222`) survive mode switches. This corrects the E0429–E0431
   assumption that SP was fully shared; the machine now also has a unit test for it.
2. **The `usr_entry` banked-store hook fires [C].** `banked_store_hits = 1` on the
   `0x0402e790` prefetch path: the hook at `__pabt_usr+0x1C` (`0x6010DE3C`,
   `stmdb r0, {sp, lr}^`) is hit and writes the saved USR SP/LR into `pt_regs`.
3. **The remaining blocker is CP15 `IFAR`/`IFSR` visibility [C].** Traced the real call
   chain `__pabt_usr` → `0x60119B60` (`mrc p15,0,r0,c6,c0,2`; `mrc p15,0,r1,c5,c0,1`;
   `b do_PrefetchAbort`) → `do_PrefetchAbort` (`0x601085EC`). In the live kernel both
   MRCs return **0**: `0x60119B68` sees `r0 = 0, r1 = 0`, and `do_PrefetchAbort` entry is
   `r0 = 0, r1 = 0, r2 = pt_regs (0x7dc0ff68)`. So the kernel calls
   `do_page_fault(addr=0, fsr=0)` and cannot map `0x0402e790`; it falls into Sony's
   `SIGSEGV`/exception monitor. Our `_set_cp15_prefetch_fault` writes are not visible to
   the kernel's MRC in this run (IFAR/IFSR reads come back 0).
4. **The `ret_to_user` banked-restore hook is unsafe and is gated off [C].** Installing a
   hook at `ret_to_user+0x24` (`0x6010DF58`, `ldmdb sp, {r0..ip, sp, lr}^`) produced a
   deterministic early boot crash (`UC_ERR_EXCEPTION` at PC `0x0`, instruction
   `161,250,000`, serial 0). With the hook gated off the boot returns to the previous
   behaviour (no hard stop, monitor loop). Native Unicorn banking may make the custom
   restore unnecessary; this needs a safer approach (e.g. patch only during user return).
5. **No interactive `/bin/ash` yet [C].** `user_mode_entries = []` and the monitor loop
   continues; serial is 60 B of monitor output. The console, cmdline override, ELF,
   prefetch delivery and `usr_entry` banking are in place; the CP15 fault-register read is
   the last identified blocker.

## 1. Evidence

| item | value |
| --- | --- |
| Unicorn banking test | `SP_svc 0x1111`, `SP_usr 0x2222` preserved across switches |
| banked store hook | `banked_store_hits = 1` (`__pabt_usr+0x1C` = `0x6010DE3C`) |
| prefetch abort | 1 delivered (`0x0402e790`, user) |
| v7 pabort helper | `0x60119B60 mrc IFAR / 0x60119B64 mrc IFSR / 0x60119B68 b do_PrefetchAbort` |
| live MRC result | `0x60119B68: r0=0, r1=0`; `do_PrefetchAbort: r0=0, r1=0, r2=0x7dc0ff68` |
| restore hook | gated off; with it enabled: crash PC `0x0` at 161,250,000 instructions |
| user-mode entries | `[]` |
| tests | Unicorn banked-SP test + banked-restore unit test — suite **1490 OK** |

## 2. Implemented

* `banked_store_hits` / `banked_restore_hits` report counters.
* `_emulate_banked_restore(pc)` (reads the ret_to_user frame, restores r0–r12, stores
  USR SP/LR into `mode_sp`/`mode_lr`, skips the instruction) and its unit test.
* The restore hook installation is **gated off** (`if False and ...`) because it crashed
  early boot; the store hook remains active and verified.
* New tests: `test_unicorn_models_banked_sp`,
  `test_banked_restore_reads_user_bank_from_frame`.

## 3. Next step

1. **Make the kernel see the fault registers**: patch the two MRCs in the v7 prefetch
   helper (`0x60119B60`, `0x60119B64`) with code hooks that load our saved
   `IFAR/IFSR` values into `r0/r1` and skip the MRC — then `do_PrefetchAbort` receives
   `addr = 0x0402e790`, `ifsr = 0x5` and can demand-page the page.
2. Re-check whether `ret_to_user`'s native `ldmdb ...,{...sp,lr}^` restores the USR bank
   correctly under Unicorn (it does for SP in the standalone test); only if not, re-enable
   the restore hook with a strictly user-return-scoped trigger.
3. Then `user_mode_entries` should become non-empty; verify `kuser_helpers` (`0xFFFF0FC0`)
   and `CPACR` only if touched, and capture the live `/bin/ash` prompt over the working
   bidirectional `ttyAM0`.
