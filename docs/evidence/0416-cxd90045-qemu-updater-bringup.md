# E0416 — CXD90045 machine-ID / ATAGS recovery and nflasha1 Unicorn bring-up (offline)

Date: 2026-11-12. **Strictly offline.** No camera access, no USB command, no mode switch,
no firmware write. Inputs: E0414 read-only dumps, the preserved package extraction, and
the E0415 decoders. Labels: **[C]** = confirmed from artifacts, **[I]** = inference.

## 0. Short answer

1. **Machine ID is `0x00000DA9` (3497)** for the `ARM-CXD900X0` board, recovered from
   **both** kernels: the nflasha3 raw kernel (`struct machine_desc` at file `0x3A85F4`,
   name `ARM-CXD900X0` at `0x3424B9`) and the nflasha1 updater kernel (decompressed
   zImage; struct at `0x331FF8`, name at `0x2D4D11`). The words after the name resolve to
   `cxd900x0_fixup`, `cxd900x0_map_io`, `cxd900x0_init_irq`, a `sys_timer` object and
   `cxd900x0_init`. **[C]**
2. **Updater ATAGS contract**: kernel load `0x00108000` (raw/decompressed image),
   initrd `0x00700000`, boot-parameter block **`0x00103000`** (nflasha1
   `boot/loadaddr.txt`). The updater `boot/kemco.txt` cmdline supplies
   `console=ttyAM0,115200n8`, `initrd=0x00700000,0x00800000`, `init=/sbin/init`,
   `mem=1G@0`, `mem=1016M@0x80000000@1` and `memrsv=` reservations. The B0 loader payload
   contains **no** ATAG magic or `0x103000`/`0x108000`/`0x700000` literals, so the tag list
   is constructed at runtime (FAT files/registers). The reconstructed standard tag list
   (ATAG_CORE, MEM ×2, CMDLINE, NONE; 884 bytes) is validated by kernel boot progress, not
   by a captured ATAGS image **[C] for addresses/strings, [I] for the tag bytes**.
3. **QEMU is not installed** on this host (checked PATH, Program Files, MSYS and WSL; only
   `arm-linux-gnueabi-objdump` exists). L1→L2 therefore uses a new **minimal Unicorn
   machine**: RAM banks `0x0+1 GiB` and `0x80000000+1016 MiB`, raw updater kernel at
   `0x00108000` (zImage gzip payload decompressed offline to 3,581,952 B), cramfs initrd
   at `0x00700000`, ATAGS at `0x00103000`, boot registers `r0=0, r1=0x0DA9, r2=0x00103000`.
4. The real kernel **boots inside Unicorn through head.S + MMU enable + `setup_arch` +
   `mm_init` + timer/clocksource init** (kernel virtual PCs are observed, so Unicorn's
   MMU translation works). The first contract gap is **`calibrate_delay`**: it waits for
   `jiffies` to advance, which needs a timer interrupt; there is no GIC/timer IRQ model.
   With a labelled one-shot runner preset of the observed `lpj` value
   (`0x1AD000`, written to the kernel's `lpj` variable at `0x6047288C`) the kernel passes
   calibration and reaches `cpu_v7_do_idle+0x8`; **no serial output yet** because console
   driver registration happens in initcalls that need the same timer/IRQ model.
5. Newly recovered MMIO bases for the next step: **GIC distributor `0xF8001000`, CPU
   interface `0xF8000100`** (`cxd900x0_init_irq` → `gic_init(0, 29, 0xF8001000,
   0xF8000100)`) and the free-running timer at **`0xF2403000`** (`+0x10C` counter used by
   `cxd4115_read_cycles`; loader writes `0x1031`/`0x10` control values). **[C]**
6. The B0 loader trace past `0xFE04733C` was extended with **labelled MMIO stubs**
   (PL011 FR = `0x90`, PMU/clock poll `0xF800277C` = `0x100`, timer counter
   `0xF240300C` += 1000): it programs UART0/clock/timer and then runs long timer-driven
   delay loops (3.6 M timer-control writes, 1.8 M counter reads in 50 M instructions);
   **no access to `0x00103000` was observed**, so whether B0 writes the ATAGS block or
   hands off to an intermediate stage (`ldr_drv.bin`/`dfe_app.bin`) remains open. **[C]**
   for the trace, nothing claimed for the handoff.

## 1. Machine-ID recovery

| kernel | file | machine ID | struct offset | name offset | board pointers |
| --- | --- | --- | --- | --- | --- |
| nflasha3 live raw kernel | `d7a9ae09…` (E0414) | `0x00000DA9` | `0x3A85F4` | `0x3424B9` | +0x20 `cxd900x0_fixup`, +0x28 `cxd900x0_map_io`, +0x30 `cxd900x0_init_irq`, +0x34 timer object, +0x38 `cxd900x0_init` |
| nflasha1 updater kernel (decompressed) | zImage `7d61feae…` | `0x00000DA9` | `0x331FF8` | `0x2D4D11` | same structure family |

Observed descriptor layout: word `+0x00` = machine ID, `+0x04` = pointer to
`ARM-CXD900X0`, followed by zeroed boot/video words and the board function pointers
listed above; the next section starts immediately after the 0x3C-byte descriptor
(the kernel ATAGS parser table). `machine_contract.recover_machine_descriptor` validates
the ID word and collects the in-image pointer words as evidence.

## 2. Updater ATAGS / `0x00103000` boot contract

| field | value | source |
| --- | --- | --- |
| kernel load | `0x00108000` | `boot/loadaddr.txt` #1 |
| initrd load | `0x00700000` | `boot/loadaddr.txt` #2, `initrd=0x00700000,0x00800000` |
| boot parameters | **`0x00103000`** | `boot/loadaddr.txt` #3 |
| cmdline | `boot/kemco.txt` (815 bytes joined) | `console=ttyAM0,115200n8 … mem=1G@0 mem=1016M@0x80000000@1` |
| memory banks (ATAG_MEM) | `(0x00000000, 0x40000000)`, `(0x80000000, 0x3F800000)` | observed `mem=` options |

Reconstructed tag list: ATAG_CORE (5 words), two ATAG_MEM (4 words each), ATAG_CMDLINE
(padded to words), ATAG_NONE — 884 bytes at `0x00103000`. The reservations
(`memrsv=1M@0`, `0x75e000@0x02E68000`, `0x500000@0x09b00000`,
`0x20000000@0x20000000:uc`) remain cmdline text; they are not emitted as ATAG_MEM.

Why this is a reconstruction: a word search of the B0 payload found no ATAG tag
constants, no `0x00103000`, `0x00108000` or `0x00700000` literals, and no `atag` strings;
the loader carries FAT/file-path code and therefore derives these from the boot media at
runtime. The layout is validated by boot progress (§4): the kernel parses the machine ID,
cmdline, memory banks and ramdisk from these bytes.

## 3. B0 loader trace past `0xFE04733C` (labelled stubs)

| stub | address | value | hits (50 M instr) |
| --- | --- | --- | --- |
| PL011 FR | `0xF2000018` | `0x90` (TXFE|RXFE) | 106,612 |
| PMU/clock poll | `0xF800277C` | `0x100` | 1 |
| free-run counter | `0xF240300C` | +1000 per read | 1,816,385 |

Progress: after the first MMIO write (`0xFE04733C → 0xF800000C = 0xFFFF`) the loader
programs UART0 (`0xF2000024/0x28/0x2C/0x30`, same values as E0415), clock/reset
(`0xF8000000/0xC/0x2100…`), PHY/PLL (`0xF2403100`, `0xF29102xx`) and the timer
(`0xF2403000` 3.6 M writes, `0xF2403004` 1.8 M writes). Hot PCs concentrate around
`0xFE04D89x` (a timer-driven delay helper). The run stopped at the instruction limit;
**0 reads and 0 writes to the `0x00103000` boot-parameter window**, so the kernel handoff
was not reached in this prefix and the intermediate-stage question is unresolved.

## 4. Unicorn L1→L2 bring-up (`nflasha1` updater set)

Machine model (`src/a6400/execution/unicorn_machine.py`): RAM `0x0+1 GiB` and
`0x80000000+1016 MiB`; MMIO windows `0xF0000000..0xFDFFFFFF` and
`0xFE100000..0xFFFFFFFF` mapped as RAM with access hooks; PL011 UART0 DR writes captured
as the `ttyAM0` log and FR seeded to `0x90`; `mmio_read_stubs` labelled and counted;
unmapped accesses stop the run with PC/registers. QEMU was checked and is absent.

Boot-progress evidence (kernel PCs are virtual, i.e. the kernel's own page tables are
active): `_stext`/head.S execution, MMU enable, `setup_arch`, `memblock`/`early_alloc`,
`mem_init`, `timer_early_init`, `clocksource`, `vfs_caches_init_early`, then
`calibrate_delay` spinning on `jiffies` (`0x6035D388` loop). That loop is the first
**timer-interrupt dependency**; with the labelled one-shot `lpj` preset
(`0x6035D320` hook writes `0x1AD000` to `0x6047288C` and flag 0 to `0x60472890`) the
kernel takes the preset path and reaches **`cpu_v7_do_idle+0x8`** (idle loop).
Serial log: **0 bytes** — the PL011 console driver is registered by an initcall, which
cannot run because the kernel never receives a timer interrupt and does not schedule the
init thread in this model. The stalls are therefore: (a) timer IRQ delivery, (b) GIC
acknowledge path. No boot beyond `start_kernel` is claimed.

Recovered for the IRQ model: GIC distributor `0xF8001000`, CPU interface `0xF8000100`
(`gic_init(0, 29, …)`), free-running timer `0xF2403000` (`+0x10C` counter, `+0x100`
control; loader writes `0x1031`), UART0 `0xF2000000`, PMU/clock `0xF8000000`/`0xF800277C`.
Next implementation: timer counter model + GIC IAR/EOIR + manual IRQ injection through the
kernel vector page (CPSR banked registers) until `jiffies` advances and initcalls run.

## 5. QEMU plan update

No QEMU ARM binary exists locally, so a QEMU run is not possible in this increment. The
bring-up inputs recovered here are exactly what a custom machine needs: machine ID `0xDA9`,
ATAGS at `0x00103000` with the two memory banks and the updater cmdline, PL011 UART0 at
`0xF2000000`, GIC at `0xF8001000/0xF8000100`, timer at `0xF2403000`, ramp `0x0/0x80000000`.
A future QEMU machine (or the Unicorn IRQ model) must deliver the timer interrupt and the
GIC acknowledge values; until then the kernel reaches the idle loop only.

## 6. Artifacts and checks

* Code: `src/a6400/execution/{arm_atags,machine_contract,unicorn_machine}.py`;
  runners `tools/research/run_nflasha1_boot.py`,
  `tools/research/run_exbl_boot_trace.py --stub/--counter-stub`.
* Tests: `tests/test_arm_atags.py`, `tests/test_machine_contract.py`,
  `tests/emulator/test_unicorn_machine.py` (17 tests; dump-dependent cases skip when the
  E0414 dumps are absent).
* Artifacts: `artifacts/analysis/e0416-qemu-bringup/` (`recon.py` output,
  `nflasha1-vmlinux-decompressed.bin`, `nflasha1-boot-report.json`,
  `nflasha1-ttyAM0.log` (0 bytes), `exbl-boot-stubbed.json`, prototype receipts,
  `full-suite.log`).
* Full suite: **1453 tests OK** (23.2 s, `python -m unittest discover -s tests -q`);
  the status card and README snapshot were regenerated and pinned to E0416 / 1453 tests.

## 7. Next

1. Model the timer counter + GIC and inject the timer IRQ so `jiffies` advances and the
   PL011 console driver registers (first ttyAM0 output).
2. Extend the loader run with DDR/PHY time models or a bounded register model to reach the
   `0x00103000` handoff and settle the intermediate-stage question.
3. Re-attempt the QEMU custom machine only when a QEMU ARM binary is available locally.
