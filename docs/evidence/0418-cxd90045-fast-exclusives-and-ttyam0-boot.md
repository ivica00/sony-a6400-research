# E0418 — Fast ARMv7 exclusive handling, corrected stop diagnosis and `ttyAM0` status

Date: 2026-11-12. **Strictly offline.** No camera access, no USB command, no mode switch,
no firmware write. Inputs: E0414 dumps, E0416 contract, E0417 timer/GIC model. Labels:
**[C]** confirmed from artifacts/tests, **[I]** inference.

## 0. Short answer

1. **The E0417 "Unicorn lacks ARMv7 exclusives" diagnosis was wrong.** A standalone
   control run proves Unicorn 2.1.4 executes `LDREX`/`STREX` on mapped normal memory
   correctly (test `test_ldrex_strex_word_succeeds_on_mapped_ram`: returns the loaded
   value and `STREX` status 0). **[C]**
2. The run stops on a **guest data abort at virtual address `0x0`**, not on an
   unimplemented instruction. The fault snapshot decodes the instruction as
   `ldrex r2,[r5]` with `r5 = 0x00000000` and **effective address `0x00000000`** at
   `cmpxchg_futex_value_locked+0x50` (PC `0x6015BDCC`). VA 0 is not mapped by the kernel
   page tables in SVC mode; the kernel's data-abort handler would normally take it, but
   Unicorn cannot deliver guest exceptions, so it surfaces as `UC_ERR_EXCEPTION`. **[C]**
3. Because of that, an exception-per-instruction "exclusive fallback" is the wrong
   strategy: it emulated the faulting path repeatedly and made the follow-up run
   impractically slow (the earlier 10-minute stall). The fast strategy implemented here
   is **deterministic single-core translation**: pre-scan the loaded kernel image and
   patch `LDREX* → LDR*`, `STREX* → STR* + MOV Rd,#0` through per-site trampolines, and
   `DMB/DSB/ISB/CLREX → NOP` (counts in a full image: 1,990 LDREX, 1,990 STREX, 3,324
   barriers). **[C]**
4. The translation is available (opt-in, default off) and unit-tested; enabling it does
   **not** remove the actual stop (the NULL access still faults), so no boot-past claim
   is made from it. The correct next fix is to model **guest data-abort delivery** (or
   identify the code path that supplies `uaddr = 0` to the futex helper).
5. **First `ttyAM0` serial byte is still not captured: `nflasha1-ttyAM0.log` is 0
   bytes.** With the timer model the run reaches `PCI`, the initrd probe, `Freeing
   memory`, PMU registration and `hwtimer cpu0..3 OK` / `hwtimer jitter`, then stops at
   the VA-0 data abort — before the PL011 console driver initcall, the `cramfs` root mount
   and `/sbin/init`. No unmapped MMIO peripheral was newly hit on this path (`unmapped: []`,
   `unmapped_addresses: []`), so the driver-stub list for the next stage is still the
   E0417 boot set (timer/GIC/UART/PMU), not NAND/eMMC/USB/GPIO. **[C]**

## 1. Evidence table

| item | value |
| --- | --- |
| run | 400 M instructions, timer IRQ model on, `--no-exclusive-fallback` |
| timer IRQs | 368 injected, 736 IAR reads, 368 EOIR writes |
| stop | `UC_ERR_EXCEPTION`, PC `0x6015BDCC` (`cmpxchg_futex_value_locked+0x50`) |
| fault instruction | `ldrex r2,[r5]`, `r5=0x0`, effective address `0x0` |
| serial | 0 bytes (`artifacts/analysis/e0418-ttyam0-init/nflasha1-ttyAM0.log`) |
| printk tail | `PMU: registered …`, `hwtimer cpu%d OK` ×4, `hwtimer jitter %lu` |
| unmapped MMIO | none (no new driver probe reached) |

## 2. Fast exclusive implementation

* `UnicornMachine(exclusive_patch=True)`: after the raw kernel is loaded, the image is
  scanned word-by-word and rewritten in RAM:
  * `LDREX Rd,[Rn]` (`cond 00011001 … 1111 1001 1111`) → `LDR Rd,[Rn]`;
  * `STREX Rd,Rm,[Rn]` (`cond 00011000 … 1111 1001 Rm`) → conditional `B` to a
    generated 4-word trampoline (`STR Rm,[Rn]`, `MOV Rd,#0`, `B site+4`), so the store
    is performed once and the status word reports success, matching single-core
    semantics;
  * `DMB`/`DSB`/`ISB`/`CLREX` → `NOP`.
* Trampolines live in a scratch RAM window (`0x02000000` physical, `0x62000000` virtual)
  and every branch stays within the ARM ±32 MB range for this image.
* The exception fallback (LDREX/LDREX B/H/D, STREX variants, local exclusive monitor,
  IRQ monitor clearing) remains as a labelled safety net; it now covers word/byte/
  halfword/doubleword and barriers, and the report exposes `exclusive_patched`,
  `exclusive_emulated` and `exclusive_trace`.
* Why patching is not the default: the observed stop is a genuine guest fault at VA 0,
  which rewriting exclusives cannot fix; disabling the slow fallback makes the run
  deterministic and fast (seconds instead of minutes).

## 3. Tests

* `tests/emulator/test_arm_exclusives.py` (4 tests): Unicorn's own LDREX/STREX support,
  word/byte/halfword exclusive emulation pair, barrier/CLREX skip, IRQ-entry exclusive
  monitor clear.
* `tests/emulator/test_timer_gic_model.py` (5 tests) remains green.
* Full suite: **1462 tests OK** (23.8 s); status card and README snapshot regenerated and
  pinned to E0418 / 1462 tests.
* Artifacts: `artifacts/analysis/e0418-ttyam0-init/` (`nflasha1-boot-report.json`,
  `nflasha1-ttyAM0.log` = 0 bytes, `full-suite.log`).

## 4. Next step

1. **Model guest data-abort delivery** (or avoid the path that calls
   `cmpxchg_futex_value_locked` with `uaddr = 0`): identify the caller of the futex
   helper at the fault (`lr = 0x6012B630`) and whether the NULL originates from an
   emulation-corrupted context (e.g. an IRQ-return register mismatch) or a real kernel
   path.
2. Once past it, continue to the PL011 console initcall and capture the first `ttyAM0`
   bytes, then the `cramfs` root mount (`0x00700000`) and `/sbin/init`; keep the
   observe-zero MMIO log to list every new driver stub.
3. Dump the kernel `__log_buf` once the console path is stable for full-message
   diagnostics.
