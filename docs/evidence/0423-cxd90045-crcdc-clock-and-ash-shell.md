# E0423 — CRCDC clock model, `init=/bin/ash` resolution and `/bin/ash` boot status

Date: 2026-11-12. **Strictly offline.** No camera access, no USB command, no mode switch,
no firmware write. Inputs: E0414 dumps, E0416 contract, E0417 IRQ model, E0420–E0422 boot.
Labels: **[C]** confirmed from artifacts/tests, **[I]** inference.

## 0. Short answer

1. **CRCDC clock block modelled [C].** Disassembly of the updater kernel's clock code
   (`cxd900x0_clock_init+0x9c`, function near `0x6011F5B8`) shows the CRCDC update path:
   it writes **1 to `[0xF2A31000 + 0x30]`**, executes `dsb`, then polls
   `[0xF2A31000 + 0x30]` **bit 0** up to 1000 times; if the bit never clears it prints
   `...CRCDC timeout:addr=f2a31000`. The machine now models the block (writes stored,
   status reads report bit0 clear), and a 400 M-instruction run's recovered dmesg
   **no longer contains the CRCDC timeout** (previously at `[85.375]`). **[C]**
2. **`init=/bin/ash` still does not take effect [C].** The recovered kernel log shows the
   effective command line as the kernel's built-in `CONFIG_CMDLINE` (the kemco text with
   `init=/sbin/init`); the ATAGS override and the `cxd900x0_fixup` skip (patch applied and
   recorded) do not change it. A labelled attempt to rewrite the built-in cmdline string in
   RAM at `start_kernel` was tried behind `--patch-config-cmdline` but faulted early in
   `paging_init` (writing `0x60104000`), so it is **gated off and not claimed**; the update
   happens too late / at the wrong object for a safe in-place edit. **[C]**
3. **Boot state unchanged:** cramfs root mounts read-only, `Failed to execute /sbin/init` →
   `Kernel panic - not syncing: No init found`; the run parks in the Sony exception/errind
   poll loop (`errind_delay`, PC `0x60123348`, serial `ttyAM0` 0 bytes). The only enabled
   console remains `klog0`. **No interactive `/bin/ash` claim.** **[C]**
4. **Bidirectional PL011 and CRCDC models are tested:** new unit test proves the CRCDC
   status read is ready after a control write; cmdline contract test proves the
   `init=/bin/ash` override is prepended and the default `init=` token replaced in the
   ATAGS/contract. **[C]**

## 1. Evidence

| item | value |
| --- | --- |
| CRCDC registers | base `0xF2A31000`; control/poll at `+0x30`; poll exit = bit0 clear |
| CRCDC timeout in dmesg | **absent after model** (was `[85.375] ERROR:cxd900x0_update_crdm:CRCDC timeout:addr=f2a31000`) |
| `cxd900x0_fixup` | patched `bx lr` at `0x60424C9C` (patch hit recorded) — no effect on effective cmdline |
| effective cmdline | built-in kemco text with `init=/sbin/init` (klog) |
| panic | `Failed to execute /sbin/init … Kernel panic - not syncing: No init found` |
| monitor stop | `errind_delay+0x64` PC `0x60123348`, 400 M instruction limit |
| serial | `nflasha1-ttyAM0.log` 0 bytes (console is klog0) |
| tests | CRCDC model + cmdline contract + UART (TX/RX) — suite **1475 tests OK** |

## 2. Implemented

* `unicorn_machine.py`: `CRCDC_BASE = 0xF2A31000` block — writes stored in
  `_crcdc_regs`, reads return 0 (ready), so `cxd900x0_update_crdm` exits its poll loop.
* Runner: `--patch-config-cmdline` (labelled, default off) rewrites the built-in
  `init=/sbin/init` string; kept off because it faults in `paging_init`.
* Tests: `tests/emulator/test_crcdc_model.py` (status ready after control write);
  `tests/test_machine_contract.py` cmdline override test (prepended token, single `init=`).

## 3. Next step

1. **Locate the true cmdline object**: dump the kernel's `boot_command_line`/
   `saved_command_line` memory after `setup_arch` (no kallsyms symbol; find by content in
   RAM) and identify exactly where the built-in kemco default is copied. Then patch at the
   right stage (e.g., hook `setup_arch`/`parse_early_param`) rather than `start_kernel`.
2. With `/bin/ash` active, provide the console: model the remaining CXD900x0 clock/PLL
   gates that keep PL011 from registering `console [ttyAM0]` (CRCDC was one; check the
   other clock registers written by `cxd900x0_clock_init`), then use the bidirectional
   UART (RX injection) to drive `ash` (`uname -a`, `ls /`, `cat /proc/cmdline`).
3. Keep no-fake-userspace rule: only configure kernel/clock prerequisites, no host-side
   shell emulation.
