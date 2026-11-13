# E0475 — `0x0403D6B2` VA-0 read root-caused: `SP_usr` is corrupted to a vector-page value

Date: 2026-11-13. **Strictly offline.** No camera access, no USB command, no mode switch,
no firmware write. Inputs: E0414 dumps, E0416 contract, E0417 IRQ model, E0420–E0474.
Labels: **[C]** confirmed from artifacts/tests, **[I]** inference.

## 0. Short answer

1. **The `0x0403D6B2` site decoded [C]** (`ld-2.11.2.so`, file offset `0xF6B2`):

   ```
   0x0403D6A8 mov  r2, r0
   0x0403D6AA ldr  r3, [pc, #0x1e8]
   0x0403D6AC push.w {r4-r11,lr}
   0x0403D6B0 sub  sp, #0x1c
   0x0403D6B2 ldr  r7, [r2], #4      ; <- the VA 0 read (r2 == 0)
   0x0403D6B6 add  r3, pc
   0x0403D6B8 ldr  r6, [pc, #0x1dc]
   ...
   0x0403D6CC ldr.w r0, [r2, lr, lsl #2]
   ```

   This is the `argc = *argv` pattern: `r2` must be the initial user-stack
   (`argv`/`argc`) pointer. The read faults because **`r0 == 0` at the call**.
2. **The caller's state at `0x0403D6A8` is already corrupted [C]** — the register/stack
   trace hook recorded (identical on all hits):

   | reg | value |
   | --- | --- |
   | `r0` | `0x00000000` |
   | `r1` | `0x0402F661` |
   | `r2` | `0x04041358` |
   | `r7` | **`0xFFFFFD64`** |
   | **`SP`** | **`0xFFFFFD64`** |
   | `LR` | `0x04031A6D` (inside `_dl_start`) |
   | `CPSR` | `0x600000F0` |

   `SP_usr = 0xFFFFFD64` is inside the **high exception-vector page**
   (`0xFFFF0000 + 0xFD64`), not the task stack (`0x5E864xxx`), and the 16-word stack dump
   at `SP` is all zeros. So the VA-0 read is a **downstream consequence of a corrupted
   user `SP`/`r0`**, not a mis-decoded `ldr` operand in the stepper.
3. **The corruption happens after the recovered `_dl_start` prologue and before the call
   into `0x0403D6A8` [C]/[I]:** the prologue was executed manually in the `USR|Thumb`
   bank with a valid stack (E0474), and the native run then proceeds through `_dl_start`
   to `0x0403D6A8` where `SP` is already the vector value. Prime suspects (next round):
   a `kuser` helper return/clobber (`kuser_hits = 4`), a `ret_to_user` banked-`SP`
   restoration using `mode_sp['usr']`, or an unmodelled `pop`/`ldmia …{…,sp}` in the
   native path.
4. **No shell [C]:** `svc_hits = 0`, `serial 0 B`, `user_mode_entries = 20`,
   `kuser_hits = 4`, stop `instruction_limit` (`PC 0x6025ED38`).

## 1. Evidence

| item | value |
| --- | --- |
| `0x0403D6B2` instruction | `ldr r7, [r2], #4` (post-index load of `argc`) [C] |
| `r0` at `0x0403D6A8` | `0x0` [C] |
| `SP` at `0x0403D6A8` | `0xFFFFFD64` (vector page), stack words all `0` [C] |
| `LR` | `0x04031A6D` (inside `_dl_start`) [C] |
| `CPSR` | `0x600000F0` (USR) [C] |
| run | `instruction_limit` `PC 0x6025ED38`, `svc_hits 0`, `serial 0 B` [C] |
| tests | unchanged `test_virtual_tlb` 36 OK (suite 1563) |

## 2. Implemented

* `e0475_trace` register/stack hooks at `0x0402E790`, `0x0403D6A8` and `0x0403D6B2`
  (report field) capturing `r0..r12`, `sp`, `lr`, `cpsr` and 16 stack words.
* `_dl_start` call-site disassembly recorded above.

## 3. Next step

1. **Bracket `SP`:** add trace points at `0x04031AA8` (post-recovery entry), `0x04031A6C`
   (the `bl` into `0x0403D6A8`) and every `kuser` helper (`0xFFFF0FA0/FC0/FE0`) to see the
   exact instruction that turns `SP_usr` into `0xFFFFFD64`; check `mode_sp['usr']` and
   `_restore_user_sp` at the last user exception delivery.
2. Fix that banked-SP/`kuser`-return defect so `SP_usr` stays at the task stack and
   `r0 = initial SP` reaches `_dl_start`; then the `0x0403D6B2` read resolves naturally.
3. Then verify `0x0402F666`/`0x04031AF0`, `svc_hits`, and capture the live `/bin/ash`
   prompt over `ttyAM0`.
