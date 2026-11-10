# E0313 — read-only physical observation of GPES BAR, GRM state and OSAL tables

Date: 2026-11-10. Physical camera work was **read-only** (user standing
authorization): `tools/camera_debugger.py exec/mem/threads`, native probes built
against the preserved Sony libc, pushed to `/tmp_bt` (RAM), executed, and
removed. No device write, no mode switch, no SD/internal-flash write, no
`/dev/stream` or `/dev/dmpgles2` open by the host. Camera stayed responsive
(uptime 35,874.63 s → 36,143.88 s, no reboot); `/tmp_bt` returned to its
pre-existing files.

## 1. Method and receipts

`artifacts/hardware/physical-readonly/`:

| file | content |
| --- | --- |
| `inventory-01.txt`, `inventory-02.txt`, `bin-list.txt` | camera uptime/kernel, `/proc/osal` presence, PID149 maps, interrupts, available tools |
| `osal-01.txt` … `osal-lmsgq2.txt`, `osal-sections.txt`, `osal-p149.txt` | `/proc/osal/uipc` pages (1,748 lines total; sections at 10/185/1024/1226/1241/1608/1729/1744/1747) |
| `mem-va-01.txt`, `mem-read-01/02.txt` | real libObj state via `camera_debugger.py mem 149 …` and `/proc/149/mem` |
| `threads-149.txt`, `grm-threads-01/02.txt` | real thread list; IMD-RM(2824)/grm_result(356)/grm_gpe(357) states |
| `gles-bar-probe-run.txt`, `gles-probe-push.txt` | read-only BAR probe run; push readback-verified |
| `gles-poll-run.txt`, `gles-poll-push.txt` | BAR status poll run (2,000,000 samples) |
| `bar-rmobj-01.txt`, `minfo-devmem-01.txt` | RM object page, `/proc/osal/minfo`, `/dev/mem` direct-read limits |

Native probes: `artifacts/native/gles-bar-probe/gles_bar_probe.elf`
(SHA-256 `2dd8daa1…7af265a`), `gles_bar_poll_probe.elf`
(SHA-256 `8922d5d8…9d1e44`); sources
`tools/native_camera/gles_bar_probe.c`, `gles_bar_poll_probe.c`. Both open
`/dev/mem` O_RDONLY, `mmap(0x4000, PROT_READ, 0xF1000000)`, only read words.

## 2. Observations (physical, this camera)

* Kernel 3.0.27_nl-rt106+; PID149 `im.elf`; `/proc/osal/{minfo,uipc,ulogio}`
  exist. `/proc/osal/uipc` global info: **836 msgqs, 197 sems, 16 msgs, 1135
  cbs, 358 misc**; four proxy threads; 1,748 lines of tables.
* Real library bases (PID149 maps): libObj `0x05d18000` (data
  `0x07016000–0x07106000`), libMWF `0x040f7000`, libosal_uipc `0x0400f000`,
  libInfraUsbCmn `0x04161000`, libUsbControl `0x04857000`,
  libUsbBusPower `0x05cd4000`, libBusPower `0x05ce1000`.
* Real libObj GRM/teardown state (debugger `mem`): slot
  `libObj+0x13F0868` = **0**; guard struct `libObj+0x13F0A28` fields
  `+0x90` = **1**, `+0xa8` = **1** — the same values our retained checkpoints
  have. RM base cell `libObj+0x136a320` = `0x06078960` (heap address differs
  from the emulator's, as expected).
* **GPES/Sugilite BAR (0xF1000000, read-only mmap):** word `0x00` =
  **0x000b0000** (identity/version); idle `0x34`=0, `0x38`=0, `0x3c`=0,
  `0x44`=0, `0xc0`=0, `0xc18`=0, `0x1000`=0.
* **BAR+0x34 status poll (2,000,000 reads):** 1,285 nonzero reads with exactly
  two distinct values — **0x40000000 (793×)** and **0x80000000 (492×)**. No
  other bits were caught (IRQ ack runs promptly). This is the first physical
  evidence of the GPES status bits E0341 previously left unknown.
* IRQs: `76 dmpgles2` = **1,107,089**; `230 fusb_usb_vbus` = 6;
  `231 fusb_usb_id` = 0.
* Real app threads include `IMD-RM` (2824), `grm_result` (356), `grm_gpe`
  (357), `UsbControl` (323/2822/2823), `UsbBusPower` (320), `BusPower` (328)
  and the full UI tier (`ObjRenderer`, `ObjDisplay`, `ObjMixer`, …).
  IMD-RM/grm_result/grm_gpe are all in `futex_wait_queue_me` (normal idle) —
  the real RM/GRM bring-up is complete and idle, not in a GPES wait.
* `/proc/149/mem` reads of the BAR mapping return EIO; `/dev/mem` direct
  `dd` reads of 0xF1000000 return EFAULT ("Bad address"), while a read-only
  `mmap` of the same page works. This is why the native probe was needed.
* `/proc/osal/uipc` LMSGQ: static local ids (`0x4C…0x70C`) and dynamic
  pool ids (`0x6000…`) with two extra columns (e.g. `00a1 653b477`); the
  ubiquitous callback `0x04113c67` resolves to libMWF `+0x1cc67`. GMSGQ/GSEM
  and the extra-column meaning are not yet decoded.
* `/proc/osal/ulogio`: ULOG 2.6 header (log name `181H_Dslr-Diadem`, log
  buffer `0x03085000`/`0x00477fc4`, print buffer `0x034fd000`); `/proc` text
  is only the 30-line header/statistics, the record log lives in `/log/`.

## 3. Implications

1. **The emulator's GRM guard/teardown state matches the real camera**
   (slot 0, guards +0x90/+0xa8 = 1), so E0312's teardown-only conclusion is a
   real property, not an emulation artifact.
2. **The real boot completes the hw-log wait via the GPES engine**, and the
   real GRM/RM threads are later futex-idle. Our replay's BAR is an anonymous
   zero page, so the guest never observes an engine completion -> the
   decoded `0xC004820D` wait parks forever (`blocked_gles_wait`, E0312).
3. The physically observed status bits **0x40000000 / 0x80000000** and BAR
   word 0 = **0x000b0000** are now available as evidence. Seeding word 0 is
   implemented (`GuestGles.bar`, only when the guest maps 0xF1000000); status
   bits must only be produced by an evidenced device-work model, not injected
   as a host success.
4. The OSAL tables are a new source of real registration/producer evidence
   (dynamic id + callback + owner columns) for the USB lane boundary
   (`usb_vbus_changed_mwf_0x0a4000_producer_not_derivable`), pending decoding.

## 4. New instrumentation (offline, opt-in)

`--trace-gles-bar` on the experiment runner installs observe-only
`UC_HOOK_MEM_READ/WRITE` on the resumed `dmpgles2` device range, records
`report['gles_bar_reads']` (per-offset counts) and `report['gles_bar_writes']`
(offset/size/value/tid/pc, capped), and mirrors guest writes into
`GuestGles.bar`. It changes no execution and is off by default. Full suite
**877 tests OK**.

Experiments: `e0372-run-glesbar.py` resumes `boot-e0315-live-block.ckpt`
(308,622,155) with the E0350 policy set plus `--trace-gles-bar`.

## 5. Remaining boundaries / next

* `gles_kick_completion_unmodelled` — still the boot blocker; the physical
  bits make an evidence-labelled engine/work model possible (kick or driver
  START -> status 0x40000000 observed by the guest), but not a fabricated
  completion of the guest wait.
* `gles_wait_signal_keymap_unmodelled`, `rm_dispatcher_consumer_unidentified`,
  `rm_hw_log_start_not_reached` — unchanged.
* Decode `/proc/osal/uipc` LMSGQ extra columns + GMSGQ/GSEM from the saved
  tables to identify real cross-process producers/consumers (USB lane).
* No GUI frame, no UVC/PTP function claimed. No camera/user-data writes.
