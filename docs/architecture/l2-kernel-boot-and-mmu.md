# L2 Full-System Kernel Boot & MMU (`UnicornMachine`)

Consolidated technical reference from `E0415–E0467` for booting original `CXD90045` Linux 3.0.27 kernels under `UnicornMachine`.

## 1. Boot Contract & Memory Layout

- **Raw ARM kernel**: physical load `0x00108000`, `PAGE_OFFSET = 0x60000000`, virtual base `0x60108000`.
- **Machine ID**: `0x00000DA9` (3497, `ARM-CXD900X0`), recovered from `.arch.info.init` (`struct machine_desc`).
- **Initrd & Boot Params**: `initrd_load = 0x00700000`, `boot_params = 0x00103000` (`boot/loadaddr.txt`).
- **RAM Banks**: `(0x00000000, 0x40000000)` (1 GiB) and `(0x80000000, 0x40000000)` (1016 MiB usable via `mem=1016M@0x80000000@1`).
- **Sony `kemco` Override (`E0425`)**: `setup_arch` validates `strncmp("kemco", (char*)0x60103000, 5)`, strips `*`, and parses from `ptr+5`. Standard ATAGS fail this check; `--sony-override` writes the raw `kemco` payload so `init=/bin/ash` or `init=/bin/busybox` is honored.
- **EXBL Bootloader (`E0415`)**: `nflashaB0` contains a `0x200`-byte `EXBL` container (`0x4C425845`) loading the DGU5 loader at `0xFE040000`, entry `0xFE047000`.

## 2. SoC Peripherals & Interrupts (`E0416–E0424`)

- **GICv1**: Distributor `0xF8001000`, CPU interface `0xF8000100` (`GICD_TYPER = 0x1F` for 1024 lines, `ICCIAR`/`ICCEOIR`, spurious `1023`).
- **Timer**: `0xF2403000` (`IRQ 153 / 0x99`, 1 MHz clock, `0x2710` ticks/jiffy = 100 Hz, free-running counter at `+0x10C`).
- **PL011 UART0 (`ttyAM0`)**: `0xF2000000`, PrimeCell IDs `+0xFE0..+0xFFC` (`0x00141011` / `0xB105F00D`), bidirectional RX/TX FIFO.
- **CRCDC Clock (`E0423`)**: `0xF2A31000`, status bit 0 at `+0x30` ready after control write.
- **VFP Check (`E0420`)**: Boot patch at `0x6041FFD8` (`FPSID` D16 check) required for Unicorn Cortex-A9/A15 models.

## 3. Virtual TLB & Exception Delivery (`E0428–E0467`)

- **Deferred `UC_TLB_VIRTUAL` (`E0448–E0457`)**: Kernel early boot runs in standard `UC_TLB_CPU` mode through `start_kernel`, `init_section_page_cgroup`, `do_initcalls`, and `cramfs` mount. On the first real user return at `ret_to_user`, the machine switches to `UC_TLB_VIRTUAL` with `UC_HOOK_TLB_FILL` walking `TTBR1` (`swapper_pg_dir` at `0x00104000`) for kernel/vmalloc and `TTBR0` (`current->mm->pgd`, e.g. `0x1DC1C000`) for user VAs.
- **ARMv7 Fault Delivery**:
  - `UC_HOOK_INTR` re-dispatches `intno == 2` (SWI to `0xFFFF0008`), `intno == 3` (Prefetch Abort), and `intno == 4` (Data Abort).
  - CP15 `DFAR`/`DFSR` and `IFAR`/`IFSR` MRC instructions in `v7_early_abort` / `v7_early_pabort` are hooked to inject saved fault registers.
  - `kuser` helpers mapped at `0xFFFF0FA0` (barrier), `0xFFFF0FC0` (cmpxchg), `0xFFFF0FE0` (get_tls), `0xFFFF0FFC` (version).
- **Current L2 Frontier (`E0463–E0467`)**: `ld-2.11.2.so` user entry (`0x0402E790`, `CPSR=0x30` USR+Thumb) is reached via `ret_to_user` (`0x6010DF64` `movs pc, lr`) with `pending_user_spsr`/`pending_user_lr` capture. At `0x0402E798`, Unicorn's TCG still decodes 4-byte ARM instructions instead of Thumb-2 despite `CPSR.T=1` and odd `PC`. Next step: warm up/emulate the first 2–3 Thumb instructions cleanly without re-entering `emu_start` mid-restore so TCG builds Thumb TBs, then verify BusyBox `_start` (`0x0000C439`) and live `/bin/ash`.
