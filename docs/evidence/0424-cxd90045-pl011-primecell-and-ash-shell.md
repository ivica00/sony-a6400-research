# E0424 — PL011 PrimeCell IDs, live `ttyAM0` console and the real cmdline-override format

Date: 2026-11-12. **Strictly offline.** No camera access, no USB command, no mode switch,
no firmware write. Inputs: E0414 dumps, E0416 contract, E0417 IRQ model, E0420–E0423 boot.
Labels: **[C]** confirmed from artifacts/tests, **[I]** inference.

## 0. Short answer

1. **PL011 PrimeCell IDs added [C].** The machine now returns the ARM identification
   registers at `UART0_BASE + 0xFE0..0xFFC` (`PeriphID = 0x00141011`,
   `PCellID = 0xB105F00D`). Result from the live console: the kernel resolved the AMBA
   device and registered the console:
   `uart0: ttyAM0 at MMIO 0xf2000000 (irq = 150) is a AMBA/PL011` followed by
   **`console [ttyAM0] enabled`**.
2. **Live `ttyAM0` serial capture works [C].** A 700 M-instruction run captured
   **52,976 bytes** in `artifacts/analysis/e0424-ash-shell/nflasha1-ttyAM0.log` — the whole
   kernel boot log plus the Sony exception-monitor console. Earlier boots produced no
   UART output because `amba_device_register()` failed without valid PrimeCell IDs.
3. **Bidirectional console verified [C].** Injecting scripted RX bytes is read by the
   guest: `help\n` produced the monitor's full help text; `shell\n` produced
   **`shell is disabled! please set EM_DEBUG to yes during compilation`**; other typed
   lines were parsed as monitor commands (`uname: Command not found`, …). The monitor then
   parks in `ambauart_console_read` waiting for input (this is a real interactive console,
   not a fabricated host shell).
4. **Root cause of the broken `init=` override found [C]:** the live console shows
   `setup_arch(): invalid cmdline override @ 0x60103000. Using default cmdline.` — Sony's
   patched `setup_arch` **rejects ATAGS and raw cmdline text** at the boot-params address
   (`0x00103000`) and falls back to the built-in kemco `CONFIG_CMDLINE`
   (`init=/sbin/init`). That is why every previous `init=/bin/ash` attempt was ignored and
   the kernel panics with `Failed to execute /sbin/init` → `No init found`. The Sony
   override object format still needs decoding (validation string at `0x603D98EE`,
   reference is PC-relative, no absolute literal).
5. **No `/bin/ash` yet [C]:** the updater's own monitor has its shell compiled out
   (`EM_DEBUG` not set), and the kernel init target remains `/sbin/init` (missing from the
   cramfs). Boot therefore still ends in `Kernel panic - not syncing: No init found` and
   the monitor prompt; `ttyAM0` output is now fully captured around it.

## 1. Evidence

| item | value |
| --- | --- |
| PL011 IDs | PeriphID `0x00141011`, PCellID `0xB105F00D` at `+0xFE0..0xFFC` |
| console | `uart0: ttyAM0 at MMIO 0xf2000000 (irq = 150) is a AMBA/PL011`; `console [ttyAM0] enabled` |
| serial | `nflasha1-ttyAM0.log` = **52,976 bytes** (full boot log + monitor) |
| RX injection | `help` → monitor help; `shell` → "shell is disabled!"; commands → parsed |
| cmdline | `setup_arch(): invalid cmdline override @ 0x60103000. Using default cmdline.` |
| init | default kemco `init=/sbin/init` → `Failed to execute /sbin/init` → panic |
| stop | `ambauart_console_read+0x40` (monitor waiting for input), 700 M limit |
| tests | PrimeCell ID test + previous UART/CRCDC/cmdline tests — suite **1476 OK** |

## 2. Implemented

* `unicorn_machine.py`: `PL011_ID_REGS` for offsets `0xFE0..0xFFC`, returned by the UART
  read model; `boot_params_payload` option to test alternative boot-params encodings.
* Runner: `--serial-input` (scripted RX bytes) for interactive console tests, and
  `--cmdline-bootparams` (labelled experiment).
* Tests: `tests/emulator/test_pl011_primecell.py` (PeriphID/PCellID read-back).

## 3. Next step

1. **Decode Sony's boot-params override object** at `0x00103000` (the validator printed
   `invalid cmdline override @ 0x60103000`): disassemble the `setup_arch` code around the
   string `0x603D98EE` (PC-relative reference) to learn the expected header/pointer format,
   then write a valid override carrying `init=/bin/ash` — with the console now live, the
   result is immediately visible.
2. With `/bin/ash` as init and `console=ttyAM0` registered, drive the BusyBox shell through
   the existing RX injection and capture its output live (the prerequisite chain of E0424
   is now complete apart from the override object).
3. Keep the exception-monitor path as a fallback diagnostic (help/dump/write commands work;
   `shell` is compiled out).
