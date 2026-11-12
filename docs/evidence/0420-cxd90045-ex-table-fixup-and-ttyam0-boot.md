# E0420 — `__ex_table` fixup delivery, `futex_init` recovery and `cramfs` ramdisk boot

Date: 2026-11-12. **Strictly offline.** No camera access, no USB command, no mode switch,
no firmware write. Inputs: E0414 dumps, E0416 contract, E0417 IRQ model, E0419 data-abort
work. Labels: **[C]** confirmed from artifacts/tests, **[I]** inference.

## 0. Short answer

1. **The boundary is crossed:** kernel faults whose PC has an `__ex_table` entry are now
   delivered **directly to the fixup** by the Unicorn machine (no CP15/vector dependency).
   The machine parses the exception table from the image (46,277 candidate `(insn,fixup)`
   pairs; `0x6015BDCC → 0x60364BD4` verified) and, on a fault at a listed PC, jumps to the
   fixup with registers unchanged. A run recorded **5 fixups**, so `futex_init()`'s
   intentional `cmpxchg_futex_value_locked(NULL, 0, 0)` probe recovered cleanly. **[C]**
2. Why the E0419 abort delivery missed: the kernel's fatal fault report consumed
   **fsr = 0** (printk trace `Unhandled fault: ... (0x000)`), i.e. the DFAR/DFSR values
   written through emulated `mcr` were not visible to the kernel's abort entry in this
   configuration; the abort therefore landed in `do_bad_area` instead of the translation
   fault → `fixup_exception` path. Direct fixup application sidesteps that and is exactly
   the fixup semantics the kernel itself would apply. **[C]**
3. Boot now passes `futex_init()` and reaches much later stages: `console [ttyAM0]
   enabled`, driver probes (`brd`, `loop`, `smsc911x`), VFP init, then **`RAMDISK: cramfs
   filesystem found at block %d` (magic `0x28cd3d45`)** and `RAMDISK: Loading %dKiB …
   into ram disk…` with a `%c` spinner. The 800 M-instruction run stopped in that load
   loop (PC `0x6012323C`), i.e. still unpacking the cramfs initrd to the ramdisk. **[C]**
4. The Sony kernel BUGs in `__boottime_vfp_init` (`BUG:%s:VFP is not D16 type.` at
   0x6041FFD8) because the emulated VFP reports a non-D16 FPSID (Cortex-A15 FPSID
   `0x…`, Cortex-A9 `0x41033090` both tripped it). A **labelled bring-up patch**
   `bne → b` at PA `0x41FFD8` skips exactly that BUG branch (patch hit recorded);
   VFP context code is otherwise untouched. **[C]**
5. **`ttyAM0` output is still 0 bytes.** After console registration the kernel never
   touches `0xF2000000` (no MMIO reads/writes in that window), so the PL011 port's
   physical base / console mapping in this kernel differs from the loader's UART0 base;
   that is the next thing to identify. No console/userspace claim. **[C]**

## 1. Evidence summary

| item | value |
| --- | --- |
| exception table | parsed from image, 46,277 candidate pairs |
| futex fixup | PC 0x6015BDCC → fixup 0x60364BD4; **5 fixups** in the run |
| serial | 0 bytes (`artifacts/analysis/e0420-ttyam0-init/nflasha1-ttyAM0.log`) |
| boot progress | console enabled → brd/loop/smsc911x → VFP init → **cramfs ramdisk loading** |
| ramdisk magic | `0x28cd3d45` at the initrd (cramfs) |
| stop | instruction limit, PC 0x6012323C, during ramdisk load |
| timer | 454 timer IRQs (E0417 model still active) |

## 2. What changed in the machine

* `_build_ex_table()` scans the raw kernel for `(insn, fixup)` word pairs whose both
  addresses lie in the kernel image and stores the mapping; `_try_ex_table_fixup(pc)`
  redirects execution to the fixup (report: `ex_table_entries`, `ex_table_fixups`,
  `ex_table_trace`).
* `RAMDISK`/driver progress is visible through the printk format tracer; the serial log
  remains the authoritative console record and is empty.
* Labelled bring-up patch for the VFP D16 BUG is applied by the runner
  (`__boottime_vfp_init` + 0x10C, `bne → b`, PA `0x41FFD8`).
* CPU model switched to Cortex-A9 (VFPv3-D16) to better match the board; the VFP BUG
  branch is still present, hence the patch.

## 3. Tests

* `tests/emulator/test_data_abort.py` now has **7 tests**, including:
  * `fixup jump for a faulting PC` (direct `_try_ex_table_fixup` semantics),
  * `real-kernel exception table contains the futex ldrex` (0x6015BDCC → 0x60364BD4),
  * the earlier CP15/ABT-state, WnR, double-fault and delivery-disable tests.
* Full suite: **1469 tests OK** (see status card for the recorded count).

## 4. Next step

1. **Identify the PL011 UART base/mapping used by the kernel console** — dump the
   runtime `amba_device`/`uart_port` structures (the driver's `membase` and the physical
   resource start), then set the machine's `uart_base`/serial capture accordingly and
   re-run; the `console [ttyAM0] enabled` message already proves the console registered.
2. Continue the cramfs initrd load past the instruction budget, mount the rootfs, and
   capture `/sbin/init` execution; keep the observe-zero MMIO log for newly probed
   peripherals.
3. Dump `__log_buf` for the full console text until the UART capture works.
