# E0421 — `ttyAM0` UART recovery, kernel log capture and first userspace (`/bin/sh` init)

Date: 2026-11-12. **Strictly offline.** No camera access, no USB command, no mode switch,
no firmware write. Inputs: E0414 dumps, E0416 contract, E0417 IRQ model, E0420 boot.
Labels: **[C]** confirmed from artifacts, **[I]** inference.

## 0. Short answer

1. **The physical UART0 base is confirmed from live kernel data:** scanning post-run RAM
   for resource records found `uart0 = [0xF2000000, 0xF2000FFF]`,
   `uart1 = [0xF2001000, 0xF2001FFF]`, `uart2 = [0xF2002000, 0xF2002FFF]` (records at
   PA 0x00462FF8 / 0x00463158 / 0x004632B8). So `ttyAM0` is UART0 at `0xF2000000`, not an
   alternate instance. **[C]**
2. **But the console writes are not visible at `0xF2000000`:** runs up to 2.5 B
   instructions show zero MMIO accesses there, and diagnostic write-range probes over
   `0xC0000000-0xFFFFFFFF` and `0xA0000000-0xC0000000` produced no printable console
   stream (only a non-text periodic stream at `0xBF000840/0xBF000844`). The PL011 block is
   therefore accessed through a mapping the current hooks do not observe; the machine now
   registers explicit UART hooks for **any configured base** (tested) and has a
   per-address write-byte probe to find the alias. `nflasha1-ttyAM0.log` is still **0
   bytes** — no console capture claim, only the kernel log below. **[C]**
3. **A much bigger milestone than the instruction limit suggested:** the kernel's own
   **klog buffer** (cmdline `klog.addr=0x034A0000 size=0x20000`) was dumped from RAM after
   the run. It contains the real boot log, ending with **userspace**:
   `program: /bin/sh(init) (pid: 1, cpu: 0, tid: -1, stackpage: 0x7E36DBE0)`, a busybox
   module list, a **NULL-vector userspace exception** (`vector exception (0x000) at
   0x00000000`), and Sony's **exception monitor** prompt:
   `Entering exception monitor. Type 'help' ... Type 'exit' to exit. Exception>`.
   So the kernel completed the ramdisk initrd load, mounted the rootfs, executed
   `/sbin/init` → `/bin/sh` (PID 1), and is now parked in the Sony exception monitor
   waiting for console input. **[C]**
4. **The 2.5 B-instruction stop at PC `0x6012321C` (`set_led+0x18`) is that monitor loop**,
   not cramfs decompression: hotspots are `errind_delay`, `em_exception_monitor`,
   `console_read`, `cxd4115_read_cycles`, and the prompt is exactly a console read loop.
   No amount of extra instruction budget will move it; it waits for input/exit. **[C]**
5. Recovered early dmesg also confirms successful kernel work: `Linux version 3.0.27_nl-rt106
   (Sony CE …)`, `[32.5] Kernel command line: ip=off initrd=0x00700000,0x00800000
   root=/dev/ram0 …`, `[58.75] Memory: 1024MB 1016MB = 2040MB total … 0K highmem`,
   `[79.125] Calibrating delay loop... 24.78 BogoMIPS (lpj=123904)` — real jiffies from the
   E0417 timer model. **[C]**

## 1. What was measured

| item | value |
| --- | --- |
| UART resources | uart0 `0xF2000000-0xF2000FFF`, uart1 `0xF2001000-…`, uart2 `0xF2002000-…` |
| console MMIO at 0xF2000000 | none observed (0 accesses) |
| write-probe ranges | 0xC0000000-0xFFFFFFFF, 0xA0000000-0xC0000000 → no printable stream |
| klog buffer | PA 0x034A0000, 0x20000 bytes (dumped; `artifacts/analysis/e0421-ttyam0-init/dmesg-klog.txt`) |
| userspace | `/bin/sh(init)` PID 1, busybox, NULL-vector exception |
| current loop | Sony exception monitor (`Exception>`) waiting for console input |
| serial log | 0 bytes |

## 2. Machine changes

* UART capture hooks are now installed for **any** `uart_base` (physical or remapped),
  independent of the default MMIO ranges; PL011 FR pre-seed is guarded for unmapped bases.
* `mmio_write_bytes` records low bytes per MMIO address and the report exposes
  `mmio_write_candidates` (printable-ratio streams) so the console data register can be
  found empirically.
* Runner supports `--uart-base ADDRESS` and `--probe-write-range START-END`, and dumps the
  kernel `klog` buffer (`dmesg-klog.txt`, `report['klog_lines']`).
* Instruction-budget experiment (2.5 B) proved the stop is the monitor input wait, not the
  ramdisk inflate loop.

## 3. Tests

* `tests/emulator/test_uart_capture.py` (2 tests): PL011 capture at the physical base and
  at a remapped high virtual base (validates the explicit-hook path).
* Full suite: **1471 tests OK** (status card records count).

## 4. Next step

1. **Find the console alias** used by the PL011 driver (mapbase `0xF2000000`, membase
   static/vmalloc) — the new write-byte probe should be run with a range covering the
   driver's ioremap area, or the `uart_port` `membase` value should be read from the live
   `amba_ports` array; then `nflasha1-ttyAM0.log` will receive the full dmesg + monitor
   output.
2. **Analyse the PID-1 NULL-vector crash** (`/bin/sh` busybox): check argv/env, `/dev`
   population (console, null), and whether the crash is due to an unmodelled syscall/mmio
   from the initramfs; then make init run cleanly or drive the exception monitor (`exit`)
   to continue.
3. Continue through rcS/`/bin/ash` with console input/output hooked both ways.
