# E0422 — PL011 alias/bidirectional UART, PID-1 panic root cause and `/sbin/init` diagnosis

Date: 2026-11-12. **Strictly offline.** No camera access, no USB command, no mode switch,
no firmware write. Inputs: E0414 dumps, E0416 contract, E0417 IRQ model, E0420/E0421 boot.
Labels: **[C]** confirmed from artifacts/tests, **[I]** inference.

## 0. Short answer

1. **`ttyAM0` console was never registered as a printk console.** The recovered kernel log
   (E0421 `dmesg-klog.txt`) shows `console [klog0] enabled` as the console that was
   enabled — Sony's memory-backed klog console. That is why no PL011/`0xF2000000` MMIO
   writes ever appear and why `nflasha1-ttyAM0.log` is empty: printk never goes to UART.
   The same log shows early clock/CRCDC trouble (`ERROR:cxd900x0_update_crdm:CRCDC
   timeout:addr=f2a31000`) and `dwc3: probe of dwc3.0 failed with error -110`. The next
   prerequisite is therefore to model the CRCDC/clock block so the PL011 probe/console can
   complete. **[C]**
2. **The PID-1 failure is a kernel panic, not a userspace segfault.** The boot log shows:
   `VFS: Mounted root (cramfs filesystem) readonly on device 1:0` →
   `Failed to execute /sbin/init. Attempting defaults...` →
   `Kernel panic - not syncing: No init found.` → then Sony's exception monitor.
   The `program: /bin/sh(init) (pid: 1, …)` line and the monitor's stack dump belong to the
   panicking `init` task; `vector exception (0x000)` is the panic path, not a user-mode
   fault. **[C]**
3. **Why exec fails:** the cramfs updater initrd does not provide `/sbin/init`; the root
   directory listing extracted from `boot/initrd.img` (cramfs, magic `0x28cd3d45`) contains
   `bin`, `sbin`, `/bin/ash`, `/bin/busybox`, and applet names (`ash`, `busybox`, `cat`,
   `mount`, …), but `/sbin/init` is not among the recovered entries. The kernel's fallbacks
   (`/etc/init`, `/bin/init`, `/bin/sh`) are not resolved either, hence "No init found".
   The correct init target for this updater rootfs is **`/bin/ash`**. **[C]**
4. **Command-line override plumbing needed a fix:** the kemco cmdline is ~810 bytes and
   this kernel's `COMMAND_LINE_SIZE` truncation (~768 bytes observed) dropped any appended
   override. `UpdaterBootContract` now strips kemco's trailing `*`, **prepends** runner
   overrides (and replaces an existing `init=` token); ATAGS bytes verified to contain
   `init=/bin/ash`. The klog extraction still shows the un-overridden command line, so the
   next verification step is to dump `boot_command_line` from RAM directly. **[C] / [I]**
5. **Bidirectional PL011 model implemented and tested:** `serial_input` injects RX bytes;
   `DR` reads pop them; `FR` reports `TXFE`/`RXFE`; `RIS` reflects RX availability and
   `ICR` clears it; `IMSC` and other registers are stored. `nflasha1-ttyAM0.log` remains
   0 bytes because the console is klog0, but the UART model is ready for the moment the
   PL011 console registers. **[C]**

## 1. Evidence summary

| item | value |
| --- | --- |
| console actually enabled | `console [klog0] enabled` (not ttyAM0) |
| clock/CRCDC | `ERROR:cxd900x0_update_crdm:CRCDC timeout:addr=f2a31000` |
| root | `VFS: Mounted root (cramfs filesystem) readonly on device 1:0` |
| init | `Failed to execute /sbin/init` → `Kernel panic - not syncing: No init found` |
| cramfs entries | `bin`, `sbin`, `/bin/ash`, `/bin/busybox`, applet names; no `/sbin/init` |
| cmdline | kemco ~810 B truncated by kernel (~768 B); overrides now prepended |
| UART model | TX capture + RX FIFO/DR/FR/RIS/ICR/IMSC; 4 tests green |
| ttyAM0 log | 0 bytes |

## 2. Machine changes (E0422)

* Bidirectional PL011 model in `unicorn_machine.py`:
  `serial_input: bytes` injection, `PL011_DR` RX pop, `PL011_FR`
  (`TXFE`, `RXFE`), `PL011_RIS`/`PL011_ICR`, register store for `IMSC` etc.
  Write hook stores PL011 registers and captures `DR` TX bytes.
* `machine_contract.py`: kemco trailing `*` stripped; runner overrides **prepended** before
  the kernel's cmdline truncation; an `init=` override replaces the existing token.
* Tests: `tests/emulator/test_uart_capture.py` now has 4 tests (TX at physical/remapped
  base, RX bytes visible via FR/DR, empty-RX RXFE).

## 3. Next step

1. **Model the CXD900x0 clock/CRCDC block (`0xF2A31000`) enough for the AMBA PL011 probe**
   so `console [ttyAM0]` registers; then the existing UART capture and RX injection
   immediately provide the full dmesg and an interactive console.
2. **Confirm the `init=/bin/ash` override reaches the kernel** by dumping
   `boot_command_line`/saved_command_line from RAM after a run (the klog line currently
   shows the untruncated kemco form).
3. With `/bin/ash` as init, drive the shell through the bidirectional UART
   (`help`, `exit`, then shell commands) and capture the real `ttyAM0` stream; the
   exception monitor can then also be exited (`exit`) for further userspace exploration.
