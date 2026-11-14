# Work Plan: Kernel Boot to GUI Display (`ILCE-6400` / `CXD90045`, offline)

This document tracks progress through all 5 emulation phases from bare kernel boot to the first real GUI frame (executed exclusively by original firmware code in `UnicornMachine`, without host-written UI).

## Phase Overview

| Phase | Name | Status | Key Evidence / Boundary |
| --- | --- | --- | --- |
| **Phase 1** | Updater kernel (`nflasha1`) + interactive `/bin/ash` shell | **DONE** | [E0510](evidence/0510-nflasha1-busybox-ash-ttyam0-shell.md) (`BusyBox v1.13.4` `/ # ` on `ttyAM0`, `uname -a`, `ls -la /`, `cpu_v7_do_idle+0x8`, CI `PASS`) |
| **Phase 2** | Main kernel (`nflasha3` `vmlinux.bin` + `initrd.img`) and early `init` | **IN PROGRESS** | Loading the main kernel, hook/`kallsyms` addresses, `ATAGS`/cmdline, and reaching the main `initrd` userspace (`/linuxrc` / `ash`) |
| **Phase 3** | Main RootFS (`nflasha7` / `nflasha15`), `rcS`, `.ko` modules, and `/dev/*` | **PENDING** | Mounting main rootfs (`/`, `/usr`, `/setting`, `/var`), `mcmn_drv` / `grm_gles` / `dmpgles2` contracts, and `/dev/*` nodes |
| **Phase 4** | `Appframework` / `im.elf` (`libObj.so`, `gui.so`) inside the OS | **PENDING** | Starting original userspace processes/threads (`THREAD_APP`, `gui.so`, `viewUnified2`), IPC, and `ioctl` without host spoofing |
| **Phase 5** | `Sugilite` / `DMP P3D` (`dmpgles2`) and first verified OSD GUI frame | **PENDING** | Rendering the original `640×480` OSD/GUI frame via `BAR 0xF1000000` (IRQ `76`) and button input |

---

## Detailed Phase Descriptions

### Phase 1 — Updater Kernel (`nflasha1`) + Interactive Shell (`/bin/ash`) [DONE]
- **Goal:** Verify the complete ARMv7 Linux 3.0.27 boot path (`start_kernel` → MMU/TLB `UC_TLB_VIRTUAL` → `ret_to_user` → `ld-2.11.2.so` → `BusyBox` `/bin/ash` on PL011 `ttyAM0`, IRQ `150`).
- **Resolved (`E0415`–`E0510`):** `amba2.console=1` override, PL011 IRQ `150` (`_sync_uart_irq`), `kuser` (`0xFFFF0000..0xFFFF1000`) hooks and `0xFFFF0FCC` COW Data Abort decoding, `switch_mm` cputlb flush, and per-process `SP_usr` preservation across `sys_clone`.

### Phase 2 — Main Firmware Kernel (`nflasha3` `vmlinux.bin` + `initrd.img`) [IN PROGRESS]
- **Goal:** Switch `UnicornMachine` from the updater kernel (`nflasha1`) to the **main** camera kernel (`nflasha3` `vmlinux.bin` + `initrd.img`) using the already-extracted `nflasha3` and `a6400-nflasha-readonly` (`/proc/kallsyms`, `nflasha3-50331648.bin`).
- **Tasks:**
  1. Verify the format and load addresses of the main kernel (`vmlinux.bin` vs `nflasha3`) and resolve its symbols (`ret_to_user`, `ret_fast_syscall`, `vector_swi`, `cpu_v7_switch_mm`, `__delay`, `em_exception_monitor`, `uaccess` helpers) so `UnicornMachine` does not rely on hardcoded `nflasha1` addresses.
  2. Boot the main kernel through `start_kernel` to `ttyAM0` output and entry into the main `initrd` (`/linuxrc` / `/bin/ash`).
- **Completion Criteria:** Main kernel boots offline, prints boot log on `ttyAM0`, and enters the main `initrd` userspace without unsupported MMIO/syscall stalls.

### Phase 3 — Main RootFS (`nflasha7` / `nflasha15`), `rcS`, Kernel Modules, and `/dev/*` [PENDING]
- **Goal:** Provide the main `init` with access to the real partitions/images (`nflasha7` `/`, `nflasha15` `/usr`, `/setting`, `/var`), `rcS` script execution, and open/contract servicing for key drivers (`mcmn_drv`, `grm_gles`, `mem_drv`, `mmc_drv`).
- **Completion Criteria:** The system completes init scripts and starts main background processes up to launching `im.elf` / `Appframework`.

### Phase 4 — `Appframework` / `im.elf` (`libObj.so`, `gui.so`) inside the Full OS [PENDING]
- **Goal:** Execute original `im.elf` / `Appframework` (`THREAD_APP`, `gui.so`, fonts) inside the emulated Linux kernel with real `sys_clone`/`futex`/`ioctl` calls.
- **Completion Criteria:** `Appframework` and `gui.so` complete initialization, allocate OSD surfaces, and enter the main event/render loop.

### Phase 5 — `Sugilite` / `DMP P3D` (`dmpgles2`) and First Verified GUI Frame [PENDING]
- **Goal:** Connect `dmpgles2` / `Sugilite` MMIO (`BAR 0xF1000000`, IRQ `76`, `0xF3400080`) to the OSD framebuffer (`640×480` RGBA4444) and produce the first verified menu/OSD frame generated exclusively by original firmware, with simulated button input support.
- **Completion Criteria:** Captured PNG/RGBA4444 frame showing recognizable Sony OSD/menu from offline emulation + regression test.
