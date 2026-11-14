# E0494 — True user-register bank for recovery: `r8 = 0x5E864F10`, first loader SVC (`brk`) executes; `VA 0x0` gone

Date: 2026-11-13. **Strictly offline.** No camera access, no USB, no writes. Inputs: E0414
dumps, E0416 contract, E0420–E0493 offline chain, the read-only dump set in
`artifacts/dumps/a6400-nflasha-readonly/` (full `/proc/kallsyms` used for address checks).

## 0. Short answer

1. **Root cause from E0493 fixed [C].** The recovery branch now calls
   `_sync_user_bank_for_recovery(pc, USR|Thumb)`: when the live `SP` is a kernel pointer
   (`>= 0x60000000`) it switches to the `USR|Thumb` bank and loads `r0..r12`, `SP`, `LR`
   from the active generation-tagged `pt_regs` frame; when that frame's PC is
   `0x04031AA8` and the fault is `>= 0x04031AAC`, it subtracts the already-executed
   `push.w {r4-r11,lr}` (`SP = frame.SP - 0x24`).
2. **The `[sp,#0x20]` slot is now written into user memory [C].** The trace record
   `recover_usr_sync` shows `frame_gen=5`, `frame_pc=0x04031AA8`,
   **`SP = 0x5E864EEC` (= 0x5E864F10 - 0x24)**, `r0 = 0x5E864F10` — exactly the value the
   prompt predicted. Consequently `0x04031AB6 str r0,[sp,#0x20]` writes
   **`0x5E864F0C`** in user memory, and `0x04031BDE ldr r0,[sp,#0x20]`
   (`r8 = 0x5E864F10`) is valid, so the `argc = *argv` callee is entered with real `argc`.
3. **The loader advances past `0x0403D6A8`/`0x0403D6B2` and reaches libc code [C].** The
   frame generations and restore trace now include `lr = 0x0403D6A8` (`_dl_start_final`
   call) and execution reaches **`0x0403EB16`**, where the **first real SVC executes**:
   `svc_trace = {pc: 0x0403EB16, r7: 45}` — ARM syscall **45 = `brk`** (`--svc-dispatch`
   now effective via the deferred `UC_HOOK_INTR` installation).
4. **New blocker [C]:** a second `UC_ERR_INSN_INVALID` at **`0x0403EB28`**
   (manual step `rec:pop`) is followed by a decoded data fault at `VD 0x8`
   (`0x0403EB2C`, address `0x00000008`, read) and then `instruction_limit`
   (`PC 0x6025ED38`). No shell yet: `serial 0 B`, one SVC only.
5. **State [C]:** `pt_frame_gen = 15`, `pt_frame_consumed = 14`, `user_restores = 8`,
   `insn_invalid_recoveries = 2`, `user_mode_entries = 20`, `svc_hits = 1`,
   `serial 0 B`, `stop = instruction_limit`, unit tests 40 OK in `test_virtual_tlb`.

## 1. Evidence

| item | value |
| --- | --- |
| helper | `_sync_user_bank_for_recovery(pc, usr_cpsr)` [C] |
| sync record | `frame_gen=5`, `frame_pc=0x04031AA8`, `SP=0x5E864EEC`, `r0=0x5E864F10` [C] |
| slot write | `[0x5E864EEC+0x20] = 0x5E864F0C` = initial SP [C] |
| slot read | `0x04031BDE ldr r0,[sp,#0x20]` → `r8 = 0x5E864F10` [C] |
| loader progress | frames/restores show `lr = 0x0403D6A8`, execution reaches `0x0403EB16` [C] |
| first SVC | `svc_trace = {pc 0x0403EB16, r7 45}` = `brk` [C] |
| new fault | `0x0403EB28` INSN_INVALID (rec `pop`) → data `0x8` at `0x0403EB2C` [C] |
| stop/shell | `instruction_limit` `PC 0x6025ED38`, `serial 0 B` [C] |
| tests | `test_recovery_syncs_user_bank_from_frame` + 40 in `test_virtual_tlb` [C] |

## 2. Implemented

* `_sync_user_bank_for_recovery()` (USR|Thumb bank, `r0..r12`/`SP`/`LR` from the active
  generation-tagged frame, `push.w` SP adjustment) and its use in the recovery branch.
* `recover_usr_sync` trace entries in `e0493_trace`.
* Unit test: kernel-SP recovery sync forces `USR`, sets `SP=0x5E864EEC`, `r0/r8` from the
  frame.

## 3. Next step

1. **Fix the `0x0403EB28` recovery:** the manual `pop` leaves the stream at `0x0403EB2C`
   where a decoded read at `0x8` faults. Log registers/`SP` at `0x0403EB16..0x0403EB2C`
   and extend `_step_user_thumb_insns` for the `pop`/`ldm` form there (likely
   `pop {…, pc}` with a following PC-relative literal), then re-run.
2. Then verify multi-SVC coverage (`uname`, `open`, `mmap2`, `set_tls`, `write`, `read`),
   BusyBox `_start 0x0000C439`, and capture the live `/bin/ash` prompt over `ttyAM0`.
