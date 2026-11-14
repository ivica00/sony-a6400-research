# E0510 — Offline `nflasha1` Linux kernel boots to interactive BusyBox `/bin/ash` shell on `ttyAM0` (`uname -a`, `ls -la /`)

Date: 2026-11-14. **Strictly offline.** No camera access, no USB, no writes. Inputs: E0414
dumps, E0416 contract, E0420–E0504 offline chain, `nflasha1` updater kernel & initrd
(artifacts archived under `artifacts/analysis/e0505/`).

## 0. Short answer

1. **Root cause #1 — `amba2.console=` override + PL011 IRQ 150 (`_sync_uart_irq`) [C].**
   - `UpdaterBootContract` (`src/a6400/execution/machine_contract.py`) now strips any prior
     `amba2.console=` token when `cmdline_extra` supplies `amba2.console=1` (`ttyAM0` enabled) [C].
   - `UnicornMachine` (`src/a6400/execution/unicorn_machine.py`) adds `UART_IRQ = 150` and
     `_sync_uart_irq()`, asserting/clearing IRQ 150 from `PL011_RIS` (RX/TX) masked by
     `PL011_IMSC` when GIC CPU/Distributor interfaces are enabled [C].
2. **Root cause #2 — kuser (`0xFFFF0000..0xFFFF1000`) hooks, `ret_to_user` target, and `0xFFFF0FCC` COW Data Abort [C].**
   - Enabled `_install_kuser_hooks(tls_only=True)` for `virtual_tlb_enabled` /
     `virtual_tlb_on_userspace` and removed the `r0 = 0` clobber in `memory_barrier` [C].
   - `_ret_tail_hook` (`0x6010DF64`) now accepts `0xFFFF0000 <= target < 0xFFFF1000` [C].
   - `_decode_fault_address()` decodes `strexeq` COW Data Aborts in the kuser page
     (`0xFFFF0FCC`, `in_kuser = 0xFFFF0000 <= pc < 0xFFFF1000`) [C].
3. **Root cause #3 — Per-process `switch_mm` cputlb flush and post-`sys_clone` `SP_usr` preservation [C].**
   - `switch_mm_hook` sets `self._pending_cputlb_flush = True` whenever `pgd != self._cached_ttbr0` [C].
   - `_deliver_user_exception` set a single global `self.user_sp` + `self._restore_user_sp = True`,
     which `user_code` replayed after a context switch and overwrote the child's `SP_usr` after
     `sys_clone` (causing `SIGSEGV`) [C]. `_ret_tail_hook` now sets `self._pending_user_frame = frame`
     with `self._restore_user_sp = False`, and `run()` `_resume` applies `_apply_pending_tlb_work()`
     **before** `_set_pc_and_cpsr(_rpc, _rcpsr)` and restoring `_pending_user_frame` (`r0..r12`, `SP`, `LR`) [C].
4. **Outcome: Phase 1 complete — `nflasha1` boots to `/ # ` BusyBox `/bin/ash` on `ttyAM0` and executes commands cleanly [C].**
   In the standard 800M instruction run (`user_restores = 1083`, `serial_bytes = 11420`,
   `unmapped = []`, `stubs = {'0xf800277c': 1}`), the kernel mounts initrd, launches
   `BusyBox v1.13.4 (2016-01-19 17:59:17 JST) built-in shell (ash)`, executes `uname -a`
   (`Linux (none) 3.0.27_nl-rt106 #1 SMP PREEMPT RT Tue May 21 10:59:14 JST 2019 armv7l unknown`)
   and `ls -la /` (full rootfs listing), reports `/bin/ash: id: not found` (applet not built into
   updater BusyBox), returns to `/ # `, and reaches `instruction_limit` cleanly in `cpu_v7_do_idle+0x8`
   (`0x6011a23c`) [C].

## 1. Command & Artifact Hashes

```powershell
python -m tools.research.run_nflasha1_boot --limit 800000000 --no-exclusive-fallback --sony-override `
  --svc-dispatch --cmdline-extra "init=/bin/ash console=ttyAM0,115200n8 amba2.console=1" --trace-user-mode `
  --serial-input "uname -a`nid`nls -la /`n" `
  --output artifacts/analysis/e0505/nflasha1-boot-report.json `
  --serial-output artifacts/analysis/e0505/nflasha1-ttyAM0.log
```

| Artifact / Source | SHA-256 | Size / Notes |
| --- | --- | --- |
| `artifacts/analysis/e0505/nflasha1-boot-report.json` | `357e189cf01522df1422992862e78d5d33c4d70571acc93917f78b8417494e4c` | `stop_reason = instruction_limit`, `cpu_v7_do_idle+0x8` (`0x6011a23c`), `user_restores = 1083`, `unmapped = []` [C] |
| `artifacts/analysis/e0505/nflasha1-ttyAM0.log` | `408d846c29af03b3d3e5141532c48a5c3090201874c8be0463a21a0de22cc548` | `11,420 B` (`ttyAM0`, `BusyBox v1.13.4`, `uname -a`, `ls -la /`, `/ # `) [C] |

## 2. Observed Serial Transcript (`ttyAM0`)

- `uart0: ttyAM0 at MMIO 0xf2000000 (irq = 150) is a AMBA/PL011` / `console [ttyAM0] enabled` [C]
- `BusyBox v1.13.4 (2016-01-19 17:59:17 JST) built-in shell (ash)` [C]
- `/bin/ash: can't access tty; job control turned off` [C]
- `/ # uname -a` -> `Linux (none) 3.0.27_nl-rt106 #1 SMP PREEMPT RT Tue May 21 10:59:14 JST 2019 armv7l unknown` [C]
- `/ # id` -> `/bin/ash: id: not found` [C]
- `/ # ls -la /` -> 23 root entries (`bin`, `dev`, `etc`, `kmod`, `lib`, `media`, `mnt`..`mnt5`, `proc`, `ramdsk -> tmp_updater`, `root`, `sbin`, `setting`, `sys`, `system`, `tmp`, `tmp_updater`, `usr`, `var`, `version.txt`), returning to `/ # ` [C]

## 3. Verification & Next Boundary

- Five focused regression tests added in `tests/emulator/test_virtual_tlb.py` covering `_ret_tail_hook`
  kuser target & stale `user_sp` clearing, kuser `0xFFFF0FCC` `strexeq` Data Abort decode,
  PL011 IRQ 150 `_sync_uart_irq()`, `switch_mm_hook` `_pending_cputlb_flush`, and
  `UpdaterBootContract` `amba2.console=1` override [C].
- **Scope boundary:** `nflasha1` is the updater Linux kernel + initrd; main-firmware rootfs/services
  (`nflasha*` / `av-cam` / `Appframework` / `gui.so` / `dmpgles2`) and display rendering belong to
  subsequent phases [I].
