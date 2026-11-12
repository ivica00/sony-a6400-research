# E0429 — ARMv7 Prefetch Abort delivery, user-mode fault routing, SP banking

Date: 2026-11-12. **Strictly offline.** No camera access, no USB command, no mode switch,
no firmware write. Inputs: E0414 dumps, E0416 contract, E0417 IRQ model, E0420–E0428 boot.
Labels: **[C]** confirmed from artifacts/tests, **[I]** inference.

## 0. Short answer

1. **Prefetch Abort delivery implemented [C].** `unicorn_machine.py` now detects
   instruction-fetch faults (Unicorn `FETCH` errors, `faulting_va == PC`, or a fault in
   user mode where no data instruction can be decoded) and delivers them to the ARMv7
   high vector **`0xFFFF000C`** with:
   * `IFAR` populated through `mcr p15,0,r0,c6,c0,2` (`0xEE060F50`),
   * `IFSR` = `0x5` (translation fault) through `mcr p15,0,r1,c5,c0,1` (`0xEE051F30`),
   * ABT mode (`0x17|0xC0`), `SPSR_abt = CPSR`, `LR_abt = PC + 4`.
   The CP15 helpers now switch to SVC mode before executing (MCR is privileged; the
   prefetch fault happens in USR mode).
2. **User-mode faults are routed to the kernel [C].** Data/prefetch aborts with
   `CPSR.M == 0x10` are always delivered to `do_DataAbort`/`do_PrefetchAbort`
   (`handle_mm_fault`), independent of the demand-page helper whitelist; kernel-mode
   helper faults keep the whitelist and the E0420 `__ex_table` fallback.
3. **First prefetch-abort delivery captured [C].** With
   `init=/bin/ash`, the run records
   `prefetch_aborts_delivered = 1`:
   `pc = address = 0x0402e790`, `ifsr = 0x5`, `user = true` — exactly the
   `/lib/ld-linux.so.3` `.text` demand page that previously stopped the run with
   `UC_ERR_EXCEPTION`. The run **no longer stops there**; it proceeds to the Sony
   exception monitor (serial 202 bytes) instead of a hard Unicorn stop.
4. **Per-mode SP banking added [C].** The kernel SVC stack pointer is captured at
   `ret_to_user` (`0x6010DF34`); when a fault from USR is delivered, the user SP is saved
   and the shared Unicorn SP is switched to the SVC value; the next user-mode instruction
   restores the saved user SP. Report field: `mode_sp`
   (`svc = 0x7dc0ffb0`, others `None`).
5. **Still no interactive shell [C].** After the prefetch delivery the kernel enters the
   Sony exception monitor and dumps `PC = 0x0402e790, CPSR = 0x70 (USR), SP = 0x7dc0ffb0,
   LR = 0` — so the kernel could not complete `do_PrefetchAbort -> handle_mm_fault` for
   this page under the current emulation, and `user_mode_entries` remains empty (the user
   never resumes at the faulting instruction). The next fix is in the abort return/vector
   state (see below), not in the UART/cmdline/ELF chain.

## 1. Evidence

| item | value |
| --- | --- |
| prefetch delivery | 1 (`pc 0x0402e790`, `address 0x0402e790`, `ifsr 0x5`, `user true`) |
| data aborts | 2 (`__clear_user_std` BSS/stack faults, VA `0x48ac6`, `0x0404e85c`) |
| ex_table fixups | 1 (futex probe `0x6015bdcc -> 0x60364bd4`) |
| SVC SP capture | `ret_to_user` `0x6010DF34` -> `svc = 0x7dc0ffb0` |
| user-mode entries | `[]` (kernel monitor path, user never resumed) |
| stop | `instruction_limit` at `cxd4115_read_cycles` (console/monitor loop), serial 202 B |
| tests | prefetch abort IFAR/IFSR/vector test — suite **1485 OK** |

## 2. Implemented

* `_deliver_prefetch_abort` + `_set_cp15_prefetch_fault` (IFAR/IFSR via emulated MCR in
  SVC mode), vector `0xFFFF000C`, `LR = PC + 4`.
* Run-loop fault dispatch: prefetch detection (FETCH/PC==VA/user-mode undefined fetch),
  user-mode data-abort always delivered to the kernel.
* `mode_sp` SP banking: capture SVC SP at `ret_to_user`; on USR fault save user SP, switch
  to SVC SP; restore user SP on the next user-mode instruction.
* `--trace-user-mode` window now `0x1000..0x60000000` (all user VAs; the request's
  `0xBF000000` would also cover kernel lowmem `0x60000000+` and slow the kernel path).
* Tests: `test_prefetch_abort_ifar_ifsr_and_vector` (CPSR/SPSR/LR/PC, IFAR/IFSR read-back,
  trace entry `user=true`).

## 3. Next step

1. **Debug the prefetch-abort return path:** after delivery the kernel does not resume
   user execution but falls into the Sony monitor with `PC 0x0402e790`, `SP 0x7dc0ffb0`
   (our captured SVC SP), all registers zero. Verify (a) the content of the high vector at
   `0xFFFF000C` and the expected `__pabt_usr` entry state, (b) that `handle_mm_fault`
   succeeds for `0x0402e790` (IFSR/IFAR semantics, fault status), and (c) that the
   `_restore_user_sp`/`mode_sp` logic does not corrupt the kernel frame.
2. Once user resumes at `0x0402e790`, expect further demand page faults for
   `ld-2.11.2.so`/busybox `.text`; the same delivery path should fault them in.
3. Then verify `kuser_helpers` (`0xFFFF0FC0`) and `CPACR` only if the first user
   instructions touch them, and capture the interactive `/bin/ash` prompt over the
   already-working bidirectional `ttyAM0`.
