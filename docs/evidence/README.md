# Platform evidence

One record per hardware or software claim. Records are dated and are **not** rewritten
when a later result supersedes them: the newer record says what changed.

Current consolidated state: [README research status](../../README.md) and
[UVC/PTP status and next steps](../UVC_PTP_STATUS.md) (through **E0424**, 2026-11-12).

## Latest records

| ID | Date | Claim |
| --- | --- | --- |
| [E0424](0424-cxd90045-pl011-primecell-and-ash-shell.md) | 2026-11-12 | PL011 PrimeCell IDs added (`0x00141011`/`0xB105F00D`) → `console [ttyAM0] enabled`; live serial capture (52,976 B) and scripted RX injection verified (`help`, `shell` -> disabled); live log shows `setup_arch(): invalid cmdline override @ 0x60103000` — Sony kernel ignores ATAGS cmdline and uses built-in `init=/sbin/init`, so boot still panics `No init found` |
| [E0423](0423-cxd90045-crcdc-clock-and-ash-shell.md) | 2026-11-12 | CRCDC clock path decoded (`0xF2A31000+0x30` write 1/poll bit0) and modelled deterministically; CRCDC timeout removed from dmesg; CRCDC + cmdline tests added; `init=/bin/ash` still not effective (built-in kemco cmdline wins), boot still panics `No init found`, `ttyAM0` 0 bytes |
| [E0422](0422-cxd90045-pl011-membase-and-userspace-init.md) | 2026-11-12 | Enabled console proven to be `klog0` (not ttyAM0) with CRCDC timeout `0xF2A31000`; PID-1 failure proven to be kernel panic `No init found` (cramfs rootfs has `/bin/ash` but no `/sbin/init`); bidirectional PL011 model (TX/RX, FR/RIS/ICR/IMSC) implemented and tested; cmdline overrides prepended to survive kernel truncation |
| [E0421](0421-cxd90045-ttyam0-uart-and-cramfs-init-boot.md) | 2026-11-12 | `ttyAM0` = UART0 `0xF2000000` confirmed from kernel resources; explicit capture hooks + write-byte probe added; klog buffer dumped from PA `0x034A0000` shows userspace reached (`/sbin/init` -> `/bin/sh` PID 1, busybox) before a userspace NULL-vector fault entered the Sony exception monitor (the 2.5B loop, not cramfs inflate); ttyAM0 log still 0 bytes (console mapping unresolved) |
| [E0420](0420-cxd90045-ex-table-fixup-and-ttyam0-boot.md) | 2026-11-12 | Direct __ex_table fixup delivery (`0x6015BDCC -> 0x60364BD4`, 46,277 pairs) recovered futex_init (5 fixups); boot reached console registration, driver probes, VFP and `RAMDISK: cramfs filesystem found at block 0` with the ramdisk-load spinner; ttyAM0 still 0 bytes (UART base/mapping unresolved) |
| [E0419](0419-cxd90045-data-abort-and-ttyam0-boot.md) | 2026-11-12 | Futex probe verified (cmpxchg on NULL at 0x6015BDCC with __ex_table entry insn 0x6015BDCC -> fixup 0x60364BD4); ARMv7 data-abort delivery (DFAR/DFSR, ABT mode, 0xFFFF0010) implemented and 2 aborts delivered, but the kernel still Oopses instead of fixup-recovering; ttyAM0 remains 0 bytes |
| [E0418](0418-cxd90045-fast-exclusives-and-ttyam0-boot.md) | 2026-11-12 | Corrected the exclusive diagnosis (Unicorn supports LDREX/STREX; the stop is a guest data abort at VA 0 in `cmpxchg_futex_value_locked`), added deterministic single-core exclusive translation (1,990 LDREX->LDR, 1,990 STREX trampolines, 3,324 barriers->NOP) and variant tests; run still reaches PCI/initrd/PMU/hwtimer but `ttyAM0` remains 0 bytes |
| [E0417](0417-cxd90045-timer-gic-and-ttyam0-boot.md) | 2026-11-12 | Timer/GIC contract decoded (`setup_irq(153)`, `gic_init(0,29,0xF8001000,0xF8000100)`, timer `0xF2403000` registers) and a deterministic GIC+timer IRQ model delivered 368 real timer IRQs: `calibrate_delay` passes on real jiffies and boot advances through PCI/initrd/PMU/hwtimer; serial still 0 bytes (blocked by Unicorn's missing ARMv7 exclusive instructions at `cmpxchg_futex_value_locked`) |
| [E0416](0416-cxd90045-qemu-updater-bringup.md) | 2026-11-12 | Machine ID `0x00000DA9`/`ARM-CXD900X0` recovered from both kernels; updater ATAGS contract at `0x00103000` reconstructed; no local QEMU → minimal Unicorn machine boots the nflasha1 kernel through head/MMU/`setup_arch`/timer init to the timer-IRQ-dependent `calibrate_delay` (labelled `lpj` preset reaches the idle loop); GIC `0xF8001000`/timer `0xF2403000` bases recovered |
| [E0415](0415-nflasha-boot-decode-and-full-emulation-roadmap.md) | 2026-11-12 | Offline EXBL/nflashaB0 loader decode (container, records, boot-mode 0x0051000F, INS/updater strings), nflasha3 boot-set unpack (raw ARM kernel + ext2 initrd, live build 8.2.6.0), kernel-backed Unicorn mapping and QEMU/Unicorn full-emulation roadmap |
| [E0414](0414-nflasha-readonly-device-check-and-boot-area-dumps.md) | 2026-11-12 | Read-only check: `/dev/nflashaB0/B1/1/3` exposed and readable (not hardware-locked); boot-area dumps with SHA-256; B0 `EXBL` loader payload, B1 all-zero; no mmc mount and no `df` on camera |
| [E0413](0413-cxd90045-updater-mode-offline-analysis.md) | 2026-11-12 | Offline CXD90045 analysis: updater boot set/markers vs missing loader; backup boot-mode record `0x51000F`; `CautionConfig.so`/MENU; updater-ramfs recovery and UART 115200 |
| [E0374](0374-run-b13-gc-context-and-second-queue-proof.md) | 2026-11-12 | Run B13: gadgetcore ep0 **is** the class ep0, and `setup_req 0x9fd8` really queues a second EP0 request (caller LR `602b9fdc`); camera rebooted after teardown |
| [E0373](0373-corrected-lpos-timeline-set-data-acked-by-other-ep0-resource.md) | 2026-11-12 | Corrected `lpos` timeline: GET status did complete; SET's OUT data was ACKed by a different ep0 resource while the bounce TRB stayed HWO=1 |
| [E0372](0372-gevnt-word-map-and-setup-req-queue-path-recheck.md) | 2026-11-12 | GEVNT word map, setup_req queue-path re-check and UDC setup-return semantics |
| [E0371](0371-run-b12-gevnt-double-queue-and-stale-completion.md) | 2026-11-12 | Run B12: a stale pending `XferComplete(ep0)` caused SET's HWO=1 giveback; setup_req return 0 double-queues a delegated ep0 request |
| [E0370](0370-offline-giveback-hwo1-and-status-nrdy-disassembly.md) | 2026-11-12 | Offline disassembly of the HWO=1 giveback, the dropped GET Status NRDY and gadgetcore's setup/queue behaviour |
| [E0354](0354-run-b-selector-accepts-084-renderstream-fails.md) | 2026-11-11 | Physical Run B/B2: the 0x84 selector accepts; RenderStream still fails; WPD cannot bind composite MI_00 |
| [E0353](0353-run-a-teardown-success.md) | 2026-11-11 | Physical Run A: unconfigure-first soft disconnect returns the camera to Mass Storage without a battery pull |
| [E0352](0352-offline-teardown-soft-disconnect-fix.md) | 2026-11-11 | Teardown root cause and clean unconfigure-first soft-disconnect sequencer (offline, Unicorn 12/12) |
| [E0351](0351-offline-renderstream-verdict-and-crash-safe-logging.md) | 2026-11-11 | RenderStream failure ranked to START endpoint selection; crash-safe SD logging and host ETW ready |
| [E0350](0350-trackb-transport-enumerates-but-renderstream-fails.md) | 2026-11-11 | Track B composite enumerates (parent + PTP + Camera) but DirectShow cannot connect the UVC pins |
| [E0349](0349-p1-foreign-get-jpeg-succeeds-in-pc-remote.md) | 2026-11-11 | P1: a foreign `GET_JPEG` sees liveview DMM frames at 29.8 FPS in PC Remote |
| [E0348](0348-uvc-monitor-architecture-probe-and-reference-client.md) | 2026-11-11 | UVC-monitor architecture, read-only MSC snapshot, safe DMA probe and reference client |
| [E0332](0332-sync-callback-delivery-first-invocation.md) | 2026-11-11 | Opt-in kernel-to-user sync callback delivery runs the original h4109 callback to completion |

## Record format

```text
ID:
Claim:
Status: unknown | inferred | verified
Firmware hash / camera configuration:
Source: artifact hash + file/offset/symbol, or recorded physical observation
Method:
Observation:
Alternative explanations:
Confidence and limitations:
Dependent implementation/scenarios:
Next experiment:
```

Do not promote source comments or log strings to verified hardware facts. Keep dumps and
large/private observations outside versioned documentation.
