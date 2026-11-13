# E0455 — Kernel `.text` scan for `mcr p15,0,Rt,c2,c0,0` (`TTBR0` writes)

Date: 2026-11-13. **Strictly offline.** No camera access, no USB command, no mode switch,
no firmware write. Inputs: E0414 dumps, E0416 contract, E0417 IRQ model, E0420–E0454.
Labels: **[C]** confirmed from artifacts/tests, **[I]** inference.

## 0. Short answer

1. **Opcode scanner implemented and validated [C].** `scan_ttbr0_write_sites()` scans the
   loaded kernel image word-aligned for `(insn & 0xFFFF0FFF) == 0xEE020F10`
   (`mcr p15,0,Rt,c2,c0,0` — the ARMv7 `TTBR0` write), extracts
   `Rt = (insn >> 12) & 0xF`, and hooks each site (`addr .. addr+4`) **before
   `emu_start()`**, caching `rt_val & ~0x3FFF` as `_cached_ttbr0` whenever it is a valid
   `pgd_pa != 0x00104000`.
2. **A real bug in the first scan was found and fixed [C]:** the image is loaded at the
   **physical** address `0x108000`, so the scan produced physical-address sites
   (`0x0011A280`, `0x0011A34C`, `0x00124154`, `0x0035D280`). Rebasing by
   `PAGE_OFFSET` yields the correct kernel-VA sites **`0x6011A280`, `0x6011A34C`,
   `0x60124154`, `0x6035D280`**; `0x6011A280` is exactly the `mcr` inside
   `cpu_v7_switch_mm` (`0x6011A26C+0x14`), matching the disassembly.
3. **But the live run records `ttbr0_write_hits = 0` [C].** Even with the correctly
   rebased hooks, none of the four scanned `TTBR0`-write instructions execute in this
   boot path. Combined with the E0454 `switch_mm` 0 hits, this means the kernel image's
   active `TTBR0`-update path is **not** one of the scanned ARM `mcr …,c2,c0,0` sites
   (candidate causes: Thumb-2 encoding of the write, a different MCR/opcode form, or the
   switch happens through a code path not executed before the run stops).
4. **Live state unchanged [C]:** `_cached_ttbr0` never receives the user `pgd`
   (`0x1DC1C000`); TTBR0 read remains `0x00104000`; fill hook walks the kernel L1 for
   user VAs; stop `__migrate_disable+0x30` with 2 VA-0 misses; `kuser_hits = 1`,
   `svc_hits = 0`, `serial 0 B`, no shell.

## 1. Evidence

| item | value |
| --- | --- |
| scanner | `(word & 0xFFFF0FFF) == 0xEE020F10`, `Rt=(word>>12)&0xF` [C] |
| physical sites (bug) | `0x0011A280`, `0x0011A34C`, `0x00124154`, `0x0035D280` [C] |
| kernel-VA sites (fixed) | **`0x6011A280`, `0x6011A34C`, `0x60124154`, `0x6035D280`** [C] |
| cross-check | `0x6011A280` = `mcr` inside `cpu_v7_switch_mm` (`0x6011A26C+0x14`) [C] |
| live hits | **`ttbr0_write_hits = 0`** [C] |
| effect | TTBR0 stays `0x00104000`, 2 VA-0 misses, no shell [C] |
| tests | scanner finds a crafted `mcr p15,0,R3,c2,c0,0`, ignores other MCR forms — suite **1537 OK** |

## 2. Implemented

* `scan_ttbr0_write_sites(code, base)` (static, unit-tested).
* `_install_ttbr0_write_hooks()`: rebase physical→kernel VA, hook up to 16 sites
  before `emu_start`, decode `Rt`, record `ttbr0_write_sites`/`ttbr0_write_hits` and
  cache the user pgd.
* Report fields `ttbr0_write_sites`, `ttbr0_write_hits`.
* Two unit tests.

## 3. Next step

1. **Find the actual TTBR0 write encoding:** disassemble/scan for Thumb-2 `MCR`
   (`0xEE…` halfword pairs) and alternate `c2,c0` opcodes
   (`c2,c0,1`/`c2,c0,2`), and hook them the same way. Alternatively hook
   `kernel_execve` return and read TTBR0 directly there (the user pgd is installed during
   `execve`), which avoids relying on instruction encodings entirely.
2. **Fix the `ret_to_user` stack mismatch** (live SVC SP still resolves `mm = NULL`):
   capture `SP`/`thread_info`/`task` from the actual `ret_to_user` frame and use
   `active_mm`/`pgd` there.
3. Once `_cached_ttbr0` holds `0x1DC1C000`, verify `0x0402F666`/`0x04031AF0` translate via
   the fill hook, `svc_hits` records ld.so/BusyBox syscalls, and capture the live
   `/bin/ash` prompt over `ttyAM0`.
