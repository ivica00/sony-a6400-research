# E0491 — Entry stack verified; `0x0403D6B2` VA-0 traced to a stale user-frame restore replay

Date: 2026-11-13. **Strictly offline.** No camera access, no USB, no writes. Inputs: E0414
dumps, E0416 contract, E0420–E0482 offline chain, the read-only dump set in
`artifacts/dumps/a6400-nflasha-readonly/` (including the full `/proc/kallsyms`).

Numbering note: the requested "E0483" label is already superseded by the parallel track
(E0484–E0490 exist), so this record uses **E0491** to keep the status card monotonic; the
content is exactly the requested E0483 scope.

## 0. Short answer

1. **The initial user stack is correct [C].** At the first user entry
   (`0x0402E791`, `CPSR 0x30`, `SP_usr = 0x5E864F10`) the 16 words are
   `argc=1`, `argv[0]=0x5E864FD8`, `argv[1]=0`, `envp[0]=0x5E864FE1`,
   `envp[1]=0x5E864FE8`, `envp[2]=0`, then `auxv = {0x10:0x8A0D7, 0x6:0x1000,
   0x11:0x64, 0x3:0x8034, 0x4:0x20, ...}` — the `create_elf_tables` layout is verified,
   so `_dl_start` receives a valid `argc/argv/envp/auxv` block.
2. **The `VA 0x0` read is a consequence of a stale user-frame restore replay [C].**
   `0x6010DF64` (`movs pc, lr`) is reached more than once. The first hit restores the real
   USR frame (`SP 0x5E864F10`, `PC 0x0402E790`). Subsequent hits re-use the **stale**
   `pending_user_spsr/pending_user_lr` captured at the previous `0x6010DF50`, read a frame
   from a mismatched base (`SP-0x48` gives all zeros) and therefore set
   `SP_usr = 0` and re-enter the consumer. The `_dl_start` prologue is then replayed with
   `SP = 0`: `push.w`/`sub.w sp,#0x27c` produce `SP = 0xFFFFFD84`, `r2 = SP+0x44 =
   0xFFFFFDC8`, and at `0x0403D6A8`-call time `r0 = r8 = 0`, so `0x0403D6B2
   ldr r7,[r2],#4` (the `argc = *argv` load) reads `VA 0x0`.
3. **Blocking the stale replay moves the failure earlier, not away [C].** With a frame
   guard (valid USR `frame_cpsr`, `frame_pc`/`SP_usr` in `0x1000..0x60000000`) plus clearing
   the pending values, `restores` drops to 1 and the run stops at `PC = 0x0` with
   `rec=0, entries=0` — i.e. the replay was masking a second defect: after the first
   delivered user fault the kernel's next `0x6010DF50` return does **not** present a fresh
   `USR` frame to the hook, so no second user resume is generated. The guard was
   experimented with and then reverted (live behaviour restored to the E0474/E0475 level).
4. **Runtime state after the revert [C]:** `insn_invalid_recoveries = 1`,
   `user_restores = 7`, `user_mode_entries = 20`, `kuser_hits = 4`, stop
   `instruction_limit` (`PC 0x6025ED38`), `svc_hits = 0`, `serial 0 B` — no shell.

## 1. Evidence

| item | value |
| --- | --- |
| first user entry | `PC 0x0402E791`, `CPSR 0x30`, `SP 0x5E864F10` [C] |
| stack | `argc=1`, `argv0=0x5E864FD8`, `envp0=0x5E864FE1`, auxv pairs valid [C] |
| restores before guard | 7; first real frame `SP 0x5E864F10` `PC 0x0402E790` [C] |
| stale hits | frame read all zeros → `SP_usr=0`, `PC` kept from stale `lr` [C] |
| replayed prologue | `SP 0xFFFFFD84` at `0x04031ABA`, `r2=0xFFFFFDC8`, `r0=r8=0` [C] |
| `0x0403D6B2` | `ldr r7,[r2],#4` with `r2=0` → `VA 0x0` [C] |
| guard experiment | `restores=1`, stop `PC 0x0`, `rec=0`, `entries=0` → reverted [C] |
| final run | `rec=1`, 7 restores, 20 entries, `kuser 4`, `instruction_limit` [C] |
| tests | suite unchanged (trace hooks only, no assertion change) |

## 2. Implemented (kept)

* `e0483_entry_stack` capture at the first user entry (16 stack words + `argc` +
  `argv0_is_ptr`) in the report.
* `e0483_trace` register snapshots at `0x04031ABA/ABC/AC4/AD0/AD8/AEA/B00/A00/A30/A42/A68`
  and `0x0403D6A8/6B2`, plus `restore` records with the restored `SP`/frame values.
* `_dl_start` call-site disassembly: `0x04031A42 mov r0,r8` → `0x04031A68 bl 0x0403D6A8`;
  the callee `0x0403D6A8 mov r2,r0; ldr r3,[pc,#0x1e8]; push.w …; sub sp,#0x1c;
  ldr r7,[r2],#4` is the `argc = *argv` pattern.

## 3. Next step

1. **Make the user frame capture explicit instead of re-derived:** capture `pt_regs` once at
   `0x6010DF34` (`ret_to_user` entry, where the base is `SP` per E0461) and have the
   `0x6010DF64` restore consume that single captured frame, with a matched
   `pending_user_*` generation counter that is cleared on use. That removes the all-zero
   `SP-0x48` reads without losing the real resume.
2. **Then trace why the second `0x6010DF50` does not carry a `USR` spsr** (likely the
   delivered abort returns through a kernel-mode path that our `ret_to_user` hook does not
   classify as a user return); fix the classification so every user resume has a fresh
   frame.
3. Re-run, then verify `0x0403D6B2`/`0x0402F666`/`0x04031AF0`, `svc_hits` with
   `enable_svc_dispatch=True`, BusyBox `_start 0x0000C439`, and the live `/bin/ash` prompt
   over `ttyAM0`.
