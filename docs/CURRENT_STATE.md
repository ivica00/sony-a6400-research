# Current State

For the full documentation index see [docs/INDEX.md](INDEX.md). For the verified test count and latest evidence snapshot, see [README.md](../README.md) and [UVC/PTP Status](UVC_PTP_STATUS.md).

## Active Track Summary (as of 2026-11-13 / E0489)

| Track | Current Frontier | Latest Evidence | Next Step |
| --- | --- | --- | --- |
| **L2 Full-System Kernel Boot** (`UnicornMachine`) | Kernel boots through `start_kernel`, `UC_TLB_VIRTUAL` activates at `ret_to_user` (`0x6010DF34`), `ld-2.11.2.so` enters `USR` Thumb (`0x0402E790`, `CPSR=0x30`); TCG ARM-vs-Thumb TB decode at `0x0402E798` blocks continuation | [E0467](evidence/0467-cxd90045-tb-evict-thumb-entry-and-ash.md), [l2-kernel-boot-and-mmu.md](architecture/l2-kernel-boot-and-mmu.md) | Warm up initial Thumb TBs without re-entering `emu_start` mid-restore, then verify BusyBox `_start` (`0x0000C439`) and `/bin/ash` |
| **L3 User-Space (`im.elf`)** (`InterpreterProbe`) | `--thread-timeslice` unlocks 88+ threads (`THREAD_APP`, `Appframework`, `gui.so`, fonts); `Appframework` hits guest `stella HeapAllocator` `0x4C`/`0x50` pool-boundary overrun (`malloc.c:4652`) | [E0340](evidence/0340-uvc-fixedbuffer-and-mode-switch-reboot.md), [l3-userspace-and-ipc.md](architecture/l3-userspace-and-ipc.md) | Decode/patch usable-size arithmetic in `libObj` helpers `0x79E8C2`/`0x79E902` and continue to `viewUnified2`/OSD |
| **Track B Physical UVC/PTP** (`054C:0322`) | Run B25 (`E0468`) proved `S1` (camera arms EP0 OUT status in ≤16.4 ms; host's single Status OUT was NAK'd in `NRDY→arm` window). `E0476` status pre-arm fix built (`dcc2f64f…`), audited (`117/8/0`), Unicorn-verified (`8/8 PASS`) | [E0476](evidence/0476-status-prearm-fix-build-audit-unicorn.md), [UVC_PTP_STATUS.md](UVC_PTP_STATUS.md) | Awaiting explicit user GO for single supervised Run B26 |
| **Multi-Device Platform** (`CXD90045`) | 13 bodies / 9 kernels mapped (`E0477–E0489`); `TargetProfile` registry has `ilce_6400`, `zv_e10`, `ilce_6100`, `ilce_6600`, `ilce_7m3` | [PLATFORM_MODEL.md](PLATFORM_MODEL.md), [ADDING_A_BIONZX_CAMERA.md](ADDING_A_BIONZX_CAMERA.md) | Wire `TargetProfile` directly into `UnicornMachine` and `InterpreterProbe` for universal target selection |

Historical 2026-10-18 and 2026-11-06 checkpoints are preserved in [docs/archives/](archives/).
