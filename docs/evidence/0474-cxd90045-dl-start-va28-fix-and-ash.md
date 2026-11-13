# E0474 — `_dl_start` entry traced: VA `0x28` store fixed (SVC-bank SP + partial stepping), execution reaches `0x0403D6B2`

Date: 2026-11-13. **Strictly offline.** No camera access, no USB command, no mode switch,
no firmware write. Inputs: E0414 dumps, E0416 contract, E0417 IRQ model, E0420–E0473.
Labels: **[C]** confirmed from artifacts/tests, **[I]** inference.

## 0. Short answer

1. **`_dl_start` entry decoded [C]** (`ld-2.11.2.so`, VA base `0x0402E000`, file offset
   `0x3AA8`):

   ```
   0x04031AA8 push.w {r4-r11,lr}
   0x04031AAC sub.w  sp, sp, #0x27c
   0x04031AB0 ldr.w  r3, [pc, #0x47c]
   0x04031AB4 add    r2, sp, #0x44
   0x04031AB6 str    r0, [sp, #0x20]     ; r0 = sp-at-entry (arg from 0x0402E798)
   0x04031AB8 add    r4, sp, #0x174
   0x04031ABA movs   r0, #0
   0x04031ABC add    r3, pc
   ...
   0x04031ACE add    r4, sp, #0x28       ; auxv/arg frame pointer
   0x04031AEA str    r1, [r4]            ; the faulting store
   ```

2. **The `VA 0x28` store was caused by stepping in the wrong register bank, not by a
   missing operand [C].** The recovery hook emulated `0x04031AAC..0x04031ABA` while the
   CPU was still in the supervisor bank, so `push.w`/`sub.w sp` adjusted **SP_svc** and
   the later `add r4,sp,#0x28` used a zeroed user `SP` → `r4 = 0x28` → `str r1,[r4]`
   wrote VA `0x28`. Two further defects made the manual stepping abort early: the
   user-page walk used a live CP15 MRC (invalid after switching to `USR`) and the stepper
   returned `None` on a not-yet-resident literal/stack page.
3. **Fixes applied and the run advanced much deeper [C]:**
   * `_set_pc_and_cpsr(pc, USR|Thumb)` **before** stepping, so `SP` reads/writes hit the
     user bank;
   * `_walk_user_va` now prefers `_cached_ttbr0` (no MRC needed in user mode);
   * `_step_user_thumb_insns` keeps **partial progress** (`(cur, cpsr, trace)`) when an
     `ldr` literal, a `str` store, a `push` store or the next fetch hits an unmapped page.
   Live: `insn_invalid_recoveries = 1` at `0x04031AAC`, `insn_invalid_unsupported = []`,
   `user_mode_entries = 20`, `kuser_hits = 4`, and the classification trace now reaches
   **`0x0403D6A8` / `0x0403D6B2`** (far beyond the previous `0x04031AEA`).
4. **New blocker [C]:** a decoded data read at `0x0403D6B2` with effective address
   `0x0` (`kind data-decoded`, `write False`) and the loop ends at the instruction limit
   (`PC 0x6025ED38`). `svc_hits = 0`, `serial 0 B` — no shell.

## 1. Evidence

| item | value |
| --- | --- |
| `_dl_start` prologue | `push.w`/`sub.w sp,#0x27c`/`ldr.w`/`add`/`str [sp,#0x20]` [C] |
| VA `0x28` cause | stepping with SVC-bank SP → `add r4,sp,#0x28` with `SP=0` [C] |
| fix 1 | USR-bank switch before manual stepping [C] |
| fix 2 | `_walk_user_va` uses `_cached_ttbr0` [C] |
| fix 3 | stepper returns partial progress on unmapped literal/store/fetch [C] |
| live progress | `rec=1`, `unsupported=[]`, trace reaches `0x0403D6A8`/`0x0403D6B2` [C] |
| stop | `instruction_limit` `PC 0x6025ED38`, `svc_hits 0`, `serial 0 B` [C] |
| tests | partial-progress unit test — `test_virtual_tlb` 36 OK |

## 2. Implemented

* `_dl_start` entry disassembly recorded above (file offset `0x3AA8`).
* USR-bank switch before recovery stepping; `_walk_user_va` cached-TTBR0 preference.
* Partial-progress return semantics in `_step_user_thumb_insns`
  (`ldr` literal, `str`, `push`, fetch).
* Unit test: `sub.w sp,sp,#0x27c ; ldr.w r3,[pc,#0x47c]` with a non-resident literal
  yields trace `['alu']` and `PC = 0x04031AB0`.

## 3. Next step

1. **Trace `0x0403D6A0..0x0403D6C0`** with register dumps to see which base register is
   zero at the `0x0403D6B2` decoded read (`address 0x0`); extend the stepper for any
   mnemonic there that is currently unsupported (`insn_invalid_unsupported` is empty, so it
   is probably a store/load with register offset or a PC-relative `adr`).
2. Re-run and, once the `0x0` read is fixed, verify `0x0402F666`/`0x04031AF0`,
   enable `svc_hits` (ld.so/BusyBox syscalls) and capture the live `/bin/ash` prompt over
   `ttyAM0`.
