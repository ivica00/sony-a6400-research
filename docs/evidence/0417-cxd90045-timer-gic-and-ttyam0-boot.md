# E0417 — CXD90045 timer + GIC interrupt model and the path to first `ttyAM0` output

Date: 2026-11-12. **Strictly offline.** No camera access, no USB command, no mode switch,
no firmware write. Inputs: E0414 dumps, E0416 machine contract, updater kernel
(`nflasha1` zImage, decompressed 3,581,952 B, sha `7d61feae…`). Labels: **[C]** confirmed
from artifacts/traces, **[I]** inference.

## 0. Short answer

1. The **timer interrupt contract is decoded** and the board `sys_timer` callback chain is
   disassembled: `machine_desc +0x34 → sys_timer { init = cxd900x0_init_timer }`; the timer
   setup calls `setup_irq(irq = **153 / 0x99**)` (runtime trace `r0=0x99`) and
   `gic_init(0, **29**, dist=0xF8001000, cpu=0xF8000100)` (runtime trace
   `r0=0, r1=0x1D, r2=0xF8001000, r3=0xF8000100`). The CXD timer uses **IRQ 153**; the
   kernel IRQ entry additionally fast-paths PPI **29** (`cmp r0,#0x1d; str r2,[r6,#0x10]`
   EOIR) and SGI IDs `<0x10`. **[C]**
2. **GIC + timer MMIO model implemented** (`src/a6400/execution/unicorn_machine.py`):
   distributor/CPU-interface register file, `GICD_TYPER` = 1024 lines (required for the
   kernel to accept IRQ 153), one-shot `ICCIAR` (pending ID, then spurious 1023),
   `ICCEOIR` clearing, instruction-proportional free-running counter at `0xF240310C`,
   jiffy pending logic, and real ARM IRQ exception entry (vector `0xFFFF0018`, banked
   `SPSR_irq`/`LR_irq`, ARM state). **[C]**
3. **First real timer interrupts now reach the kernel**: in a 1 B-instruction run the
   model delivered **368 timer IRQs** with **736 IAR reads** and **368 EOIR writes**;
   `calibrate_delay` now completes from real jiffies (no `lpj` preset) and the kernel
   continues far past E0416's idle loop: PCI init, initramfs probe (`rootfs image is not
   initramfs … looks like an initrd`), `Freeing … memory`, PMU registration and
   `hwtimer` initialisation messages are in the printk trace. **[C]**
4. **First `ttyAM0` byte is still not reached**: the serial log is **0 bytes**. The run
   stops on an emulator limitation, not a kernel failure: **Unicorn 2.1.4's ARM target
   raises `UC_ERR_EXCEPTION` on ARMv7 exclusive instructions** — first hit at
   `ldrex r2,[r5]` in `cmpxchg_futex_value_locked+0x50` (PC `0x6015BDCC`). A local
   exclusive-monitor fallback (LDREX/STREX/DMB/CLREX) was added, but the follow-up run
   spent too long inside the atomic/futex path to be called a fix; the console initcall is
   therefore still after the stop point. **[C] for the boundary, no boot claim.**
5. Timer MMIO semantics decoded from `cxd900x0_init_timer`/`ext_timer_setup`/
   `ext_timer_set_mode`/`ext_timer_set_next_event`/`ext_timer_interrupt`: base
   `0xF2403000`, control `+0x00` (write `0x1000` enable, `0x1102` periodic start),
   divider `+0x04` (`0x11`; **write 1 acknowledges the interrupt**), period/compare
   `+0x08` (periodic `0x2710` = 100 Hz on the 1 MHz timer), free-running counter
   `+0x10C`. The clocksource path reads `[0xF2403000+0x10C]` and scales it
   (`cxd4115_read_cycles`/`cxd900x0_update_sched_clock`). **[C]**

## 1. Disassembly evidence

| item | address | finding |
| --- | --- | --- |
| updater `machine_desc` | file `0x331FF8` | `+0x30 cxd900x0_init_irq` (0x60424868), `+0x34 sys_timer` → 0x60471980, `+0x38 cxd900x0_init` (0x60424D44) |
| `sys_timer` object | 0x60471980 | `{ init = cxd900x0_init_timer (0x60424938), suspend = 0, resume = 0 }` |
| `cxd900x0_init_timer` | 0x60424938 | `init_sched_clock`; clocksource reads `[0xF2403000+0x10C]` (scale mult `0xFA000000`, shift `0x17`); calls `ext_timer_setup(base+0x20, index 0)` |
| `ext_timer_setup` | 0x6011F980 | context array `0x60460C40` (stride 0x60) `+0x08 = 0xF2403000`; stores handler `ext_timer_interrupt`; **`setup_irq([ctx+4]+0x99, …)`**; runtime trace confirms `r0 = 0x99` |
| `gic_init` call | 0x604243C4 (runtime trace) | `gic_init(gic_nr=0, irq_start=0x1D=29, dist=0xF8001000, cpu=0xF8000100)` |
| timer register programming | `ext_timer_set_mode` 0x6011F798, `ext_timer_set_next_event` 0x6011F850 | `+0x00`: stop (`0`), enable (`0x1000`), periodic (`0x1102`); `+0x04`: divider `0x11`; `+0x08`: period `0x2710` / next-event offset |
| timer interrupt ack | `ext_timer_interrupt` 0x6011F8B0 | `str 1, [base+4]` (ack), then `clock_event_device` handler callback |
| kernel IRQ entry | `__irq_svc` 0x6010D9E0 | reads `[gic_cpu+0x0C]` (IAR) once per IRQ; EOIR writes only for IDs `< 0x10` and for `0x1D` (PPI 29 fast path); generic SPI path dispatches and the GIC handler EOI arrives through the timer action's chip op |

## 2. GIC/timer model (implementation)

* MMIO windows (E0416 bases): GIC dist `0xF8001000`, GIC CPU `0xF8000100`, timer
  `0xF2403000+0x200`; PL011 UART0 `0xF2000000`.
* Distributor: `GICD_CTLR` enables; `GICD_TYPER` (offset 0x004) reads **0x1F** → 1024
  interrupt lines, which makes the kernel accept `setup_irq(153)` (before this the timer
  action was rejected and every injected IRQ took the "unhandled IRQ 153" dump path).
* CPU interface: `ICCICR`/`ICCPMR` tracked; `ICCIAR` (0x0C) returns the pending IRQ once
  per injection and spurious `1023` afterwards until the next jiffy; `ICCEOIR` (0x10)
  clears the active IRQ.
* Timer: counter at `0xF240310C` advances by
  `ticks_per_instruction * executed_instructions` (default 1:1); a jiffy is 10,000 ticks
  (100 Hz); one pending interrupt at a time; injection begins only after
  `timer_irq_start_instructions` (5 M) so the kernel's `setup_irq(153)` exists first.
* IRQ delivery: switch to IRQ mode (`CPSR 0x12|0xC0`), then write the **banked**
  `SPSR_irq` (the interrupted CPSR) and `LR_irq = PC+4`, and enter the high vector page at
  `0xFFFF0018` in ARM state. Writing SPSR before the CPSR switch had targeted `SPSR_svc`
  and sent the kernel into the wrong (`__irq_usr`) path — fixed.
* Instrumentation kept in the report: IAR/EOIR counts, injection PCs, timer-counter reads,
  `printk` format trace, GIC register file, unmapped-MMIO log.

## 3. Results (1 B instructions, report `e0417-ttyam0-boot/nflasha1-boot-report.json`)

| metric | value |
| --- | --- |
| timer IRQs injected | 368 |
| GIC IAR reads / EOIR writes | 736 / 368 |
| timer counter reads | 1,561 |
| jiffy source | instruction-proportional model (no `lpj` preset) |
| serial (`ttyAM0`) bytes | **0** |
| stop | `UC_ERR_EXCEPTION` at `ldrex r2,[r5]`, `cmpxchg_futex_value_locked+0x50` |
| printk trace | 158 formatted messages up to `hwtimer cpu%d … hwtimer jitter %lu` |

Boot progress visible in the printk trace: `Linux version 3.0.27_nl-rt106` →
`Machine: ARM-CXD900X0` → `arm_add_memory` (2 banks) → `bootmem_init`/`high_memory` →
zones → `Calibrating delay loop` **passes via real jiffies** → PCI (`PCI: CLS …`) →
`Trying to unpack rootfs image as initramfs…` / `rootfs image is not initramfs (%s);
looks like an initrd` → `Freeing %s memory …` → `PMU: registered new PMU device` →
`hwtimer cpu0/1/2/3 OK` / `hwtimer jitter`.

Boundary: the stop instruction is an ARMv7 exclusive (`LDREX`) that Unicorn 2.1.4 does
not implement; the kernel's atomic/futex code takes this path (PC
`0x6015BDCC`). Because the console driver is registered by a later initcall, no `ttyAM0`
character has been written yet; this is **not** an evidence-backed "boot to userspace"
claim.

## 4. Next step

1. Make the exclusive-instruction fallback fast and reliable (cache capstone decode,
   handle `ldrexb/strexb/ldrexh/strexh`, verify the futex loop terminates) or avoid the
   Unicorn limitation, so the boot reaches the PL011 console initcall.
2. Capture the first `ttyAM0` bytes (serial capture already records UART0 DR writes) and
   the console registration message, then continue to `cramfs` rootfs mount and
   `/sbin/init`.
3. Keep the unmapped-MMIO `observe-zero` log for every newly probed driver register.

## 5. Tests and checks

* New model tests: `tests/emulator/test_timer_gic_model.py` (5 tests: GIC IAR/TYPER
  read-back, instruction-proportional counter, jiffy pending logic, banked IRQ injection
  state, masked/disabled non-injection).
* Full suite: **1458 tests OK** (22.7 s, `python -m unittest discover -s tests -q`);
  the status card and README snapshot were regenerated and pinned to E0417 / 1458 tests.
* Artifacts: `artifacts/analysis/e0417-ttyam0-boot/` (`nflasha1-boot-report.json`,
  `nflasha1-ttyAM0.log` = 0 bytes, `full-suite.log`).
