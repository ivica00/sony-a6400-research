# E0464 — Thumb `T=1` lock attempt at the user restore: `CPSR`/`PC` order, slice restart, and the persisting ARM decode

Date: 2026-11-13. **Strictly offline.** No camera access, no USB command, no mode switch,
no firmware write. Inputs: E0414 dumps, E0416 contract, E0417 IRQ model, E0420–E0463.
Labels: **[C]** confirmed from artifacts/tests, **[I]** inference.

## 0. Short answer

1. **The restore now has an explicit Thumb/PC helper and a user-entry trace [C].**
   `_set_pc_and_cpsr(pc, cpsr)` writes `CPSR` and `PC` (with `| 1` when `T` is set) and
   re-asserts `CPSR` if the read-back `T` bit disagrees; a `0x0402E790..0x0402E7A8`
   `UC_HOOK_CODE` records the first user instructions.
2. **`T=1` is confirmed at the user entry [C].** Live: `user_entry_trace` contains
   `pc 0x0402E790`, **`cpsr 0x00000030`**, `thumb True`; `user_restores = 2`,
   `user_mode_entries = 1`, `kuser_hits = 3`.
3. **Unicorn still decodes the first instructions as ARM [C].** The run goes
   `0x0402E790` (traced, Thumb) → `0x0402E798` **`UC_ERR_INSN_INVALID`** → data fault at
   `0x0402E79C`, stop `PC = 0x0402E79C` (`serial 0 B`, `svc_hits = 0`). Bytes at
   `0x0402E790..0x0402E798` (`df f8 68 a0`, `df f8 68 40`, `68 46`, `03 f0 85 f9`) are
   valid Thumb-2 (`ldr.w sl,[pc,#0x68]`, `ldr.w r4,[pc,#0x68]`, `mov r0,sp`, `bl …`), and
   the observed PC progression `0x790 → 0x794 → 0x798 (INSN_INVALID)` is exactly
   **4-byte ARM decoding** of two instructions before hitting `0xf0034668`, which is
   invalid as ARM — i.e. Unicorn's TCG translation state is still ARM despite
   `CPSR.T = 1` [C]/[I].
4. **A `uc.emu_stop()`-inside-the-restore experiment was tried and reverted [C].**
   Restarting the slice so that `emu_start(begin = pc | 1)` would initialise
   `env->thumb` instead produced a worse state: stop at `0x0402E794` with no traced
   user entry and no demand-page fault, so the experiment was **reverted**; the code kept
   the helper and the trace, and the E0463-level behaviour (user entry reached) is intact.

## 1. Evidence

| item | value |
| --- | --- |
| helper | `_set_pc_and_cpsr(pc, cpsr)`: `CPSR`, then `PC` with LSB from `T`, re-assert `CPSR` [C] |
| user entry trace | `0x0402E790`, `cpsr 0x30`, `thumb True` [C] |
| restores / entries | `user_restores = 2`, `user_mode_entries = 1`, `kuser_hits = 3` [C] |
| next fault | `0x0402E798` `UC_ERR_INSN_INVALID`, data fault `0x0402E79C`, stop `0x0402E79C` [C] |
| entry bytes | `df f8 68 a0`, `df f8 68 40`, `68 46`, `03 f0 85 f9` = valid Thumb-2 [C] |
| slice-restart variant | stop `0x0402E794`, trace empty, no demand fault — reverted [C] |
| tests | `_set_pc_and_cpsr` + odd-PC Thumb execution (Thumb-2 `ldr.w`/`mov r0,sp`) — suite **1550 OK** |

## 2. Implemented

* `_set_pc_and_cpsr(pc, cpsr)` static-restore helper (writes `CPSR`, then `PC` with the
  `T`-derived LSB, verifies the read-back `T` bit).
* First-user-instruction `UC_HOOK_CODE` trace (`0x0402E790..0x0402E7A8`, USR only),
  report field `user_entry_trace`.
* Two unit tests: helper sets `T`/LSB consistently and a tiny Thumb-2
  `ldr.w`/`mov r0,sp` pair executes under `emu_start(begin=pc|1)`.

## 3. Next step

1. **Prove the TCG state**: single-step the first two instructions with
   `emu_start(begin=0x0402E790 | 1, count=1)` from a controlled CPU state and log `PC`
   after each step; if `PC` advances by 4, the CPU really is decoding ARM — then the
   restore must leave the CPU in a state where Unicorn's `CPSR.T` is authoritative
   (e.g. write `CPSR` with `T` via `uc.reg_write` while `PC` is still in the kernel, then
   move `PC` with an odd value last, and verify with `uc.ctl_flush_tb()` before resume).
2. Alternatively **emulate the entry**: after the manual restore, treat `0x0402E790` as a
   labeled bring-up aid (single-step each instruction with `count=1` from explicit
   `CPSR`/`PC`), which keeps Unicorn from caching a wrong TB.
3. Once `0x0402E798`/`0x0402E79A` execute cleanly, verify `0x0402F666`/`0x04031AF0`,
   enable `svc_hits`, and capture the live `/bin/ash` prompt over `ttyAM0`.
