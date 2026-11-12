# E0430 — `SP_abt`/`SP_svc` isolation on exception entry and the remaining user-resume blocker

Date: 2026-11-12. **Strictly offline.** No camera access, no USB command, no mode switch,
no firmware write. Inputs: E0414 dumps, E0416 contract, E0417 IRQ model, E0420–E0429 boot.
Labels: **[C]** confirmed from artifacts/tests, **[I]** inference.

## 0. Short answer

1. **The abort-entry SP collision is fixed [C].** In E0429 a fault from USR switched the
   shared Unicorn `SP` to `mode_sp.svc` and jumped to the hardware vector, so the kernel's
   `vector_pabt` scratch (`stmia sp, {r0, lr}; str spsr, [sp,#8]`, 12 bytes on `SP_abt`)
   landed on top of PID 1's SVC kernel stack. The machine now **emulates the vector stub
   itself**:
   * writes the 12-byte frame `{r0, pc, spsr}` to a dedicated scratch page
     (`PA 0x02002000`, VA `0x62002000`) — never into `SP_svc`;
   * switches to SVC mode (`CPSR 0x13|0xC0`), sets `SP = mode_sp['svc']`
     (captured at `ret_to_user`), `r0 = scratch_va`, `LR = pc`, and jumps **directly** to
     the kernel handlers `__pabt_usr` (`0x6010DE20`) / `__dabt_usr` (`0x6010DC20`).
   `SP_abt` is therefore fully isolated from `SP_svc`; no abort frame overwrites the
   kernel stack top.
2. **Handler ABI verified against the kernel [C].** Disassembly of `__pabt_usr` /
   `__dabt_usr` shows the expected contract: `sub sp, sp, #0x48; stmib sp, {r1..ip};
   ldm r0, {r3, r4, r5}; str r3, [sp]; ...` — i.e. `r0` is exactly the 3-word frame
   `{saved r0, pc, spsr}` and the rest of `pt_regs` is built on the SVC stack. The
   emulated entry matches this layout, saving the faulting user SP and restoring it on the
   next user instruction (`_restore_user_sp`).
3. **Live run: prefetch abort still delivered, user-resume remains blocked [C].** With
   `init=/bin/ash console=ttyAM0,115200n8`, the run again delivers the
   `0x0402e790` prefetch abort (IFSR `0x5`, user): `prefetch_aborts_delivered = 1`,
   2 data aborts, no Unicorn hard stop. However the kernel still ends in the Sony
   exception monitor (serial 202 B) and `user_mode_entries` stays `[]`; the monitor dump
   now shows `PC = 0x0402e790`, `CPSR = 0x70` (USR/Thumb), `LR = 0`,
   `SP = 0x5e864f10` (a user-range value, no longer the SVC stack top). So the SVC-stack
   collision is gone, but `do_PrefetchAbort → handle_mm_fault` still does not resume
   `0x0402e790`; the remaining suspects are the handler's banked-user `stmdb ... ^`
   (user SP/LR access), TLS/PID/context writes and TLB maintenance executed by
   `__pabt_usr`, which Unicorn may not model faithfully.
4. **No interactive shell claim.** The console, cmdline override, ELF/interpreter chain,
   prefetch/data abort delivery and SP isolation are all in place; the last blocker is the
   kernel user-fault handler return path under Unicorn.

## 1. Evidence

| item | value |
| --- | --- |
| abort entry | emulated vector_stub: scratch VA `0x62002000`, SVC SP from `mode_sp['svc']` |
| handlers | `__pabt_usr` `0x6010DE20`, `__dabt_usr` `0x6010DC20` |
| SP isolation test | PC/CPSR/SP/r0/scratch-frame assertions pass |
| live prefetch | `0x0402e790`, IFSR `0x5`, user `true` (delivered) |
| live monitor dump | `PC 0x0402e790`, `CPSR 0x70`, `SP 0x5e864f10` (no SVC-stack overwrite) |
| user-mode entries | `[]` (still no resume) |
| stop | instruction_limit in `touch_softlockup_watchdog`/console loop, serial 202 B |
| tests | `test_user_prefetch_enters_pabt_usr_with_isolated_abt_frame` — suite **1486 OK** |

## 2. Implemented

* `_deliver_user_exception`: emulated `vector_stub` entry (scratch frame at
  `VECTOR_SCRATCH_PA`, SVC mode + `SP_svc`, `r0 = scratch`, `LR = pc`, direct handler
  jump); used by both `_deliver_data_abort` and `_deliver_prefetch_abort` for
  `CPSR.M == 0x10`.
* `_symbol_address` helper; `_pending_exception` kind; user SP saved/restored
  (`_restore_user_sp` + wide user code hook).
* Test: user prefetch delivery enters `__pabt_usr` with isolated scratch frame and SVC SP,
  asserting `SP_abt` scratch is separate from `SP_svc`.

## 3. Next step

1. Trace `__pabt_usr → do_PrefetchAbort → handle_mm_fault` for `0x0402e790`: check whether
   the handler's `stmdb r0, {sp, lr}^` (banked user SP/LR store), TLS/context writes and
   TLB invalidation are modelled by Unicorn; these are the likely reasons the handler
   cannot complete and falls back to the Sony monitor.
2. If the banked-store semantics are the issue, emulate `^` stores explicitly in the code
   hook (write user SP/LR into the frame) as was done for the vector stub.
3. Then `user_mode_entries` should record `ld-2.11.2.so`/busybox execution, the
   `kuser_helpers`/`CPACR` checks apply only if touched, and the live `/bin/ash` prompt
   can be captured over the working bidirectional `ttyAM0`.
