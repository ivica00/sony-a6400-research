# E0410 — Why `mmcio_mount` fails: read-only root-cause investigation (Wi-Fi down)

Date: 2026-11-12. Read-only only. **No Wi-Fi was triggered or toggled in this
step**; no camera writes, no modules loaded, no mode switch. Scope: explain the
`mmcio_mount failed!` → `WlanResource_Ma` crash → warm reboot on the stock
Wi-Fi path (cold boot, battery pulled, no SD card), audit `/setting` and Backup
against the preserved Nov-10 snapshot, and propose a reversible recovery plan
for explicit approval before any further Wi-Fi attempt.

## 1. Symptom, reproduced read-only from the cold-boot ring

`dump-ring` after the cold-boot Wi-Fi attempt (receipt:
`artifacts/hardware/e0410-wifi-rootcause/ring-coldboot.txt`, 60,546 bytes,
boot_count=2) shows the same failure chain as before, now with a full timeline:

```
[ 13.474] Compat-wireless backport release: compat-wireless-v3.5.4-1-brcm
[ 13.492] cfg80211: Calling CRDA to update world regulatory domain
[ 13.504] wlanMemoryAllocator: size:32768 ... g_pMemGfpAtomicMmcioWrapper[0]=68f38000
[ 13.859] [HW_WRAPPER] UHS2 FuncTable is NULL!! USH2 unsupported Controller
[ 13.859] [SD] isUSH2 = 0
[ 13.900] mmc_hwip_system_off START
[ 14.200] err 0x0
[ 14.200] mmc_hwip_system_off END
[ 14.200] mmcio_mount failed!
[ 14.201] wlanMemoryAllocator: Allocated Memory Returned ... for mmcioWrapper
[ 14.201] mmcio_wrapper_init failed!
...
[current task] program: im.elf(WlanResource_Ma) (pid 347, cpu:3)
page translation fault (0x817) at 0x00000000   pc=0x083e7a2e
Entering exception monitor -> [0.762] WARMBOOT
```

Excerpt saved as `artifacts/hardware/e0410-wifi-rootcause/wifi-mount-crash-excerpt.log`.
This is the **stock menu path** (owner, cold boot, battery pulled, SD removed) —
not the earlier OSAL injection.

## 2. Live firmware identity (important correction)

`/proc/version` on the camera:

```
Linux version 3.0.27_nl-rt106+ (jp10239@dic-build-scm-348)
(gcc 4.5.1 (20181205 (Sony CE Linux 8.2.6.0))) #1 SMP PREEMPT RT
Tue Aug 10 13:03:39 JST 2021
```

All `/usr/wlan`, `/usr/kmod`, `/usr/lib` WLAN files have **mtime Aug 10 2021**
(stock firmware files), e.g. `/usr/kmod/mmc_drv.ko` 224,064 B,
`/usr/kmod/mmcioWrapper.ko` 6,760 B, `/usr/lib/libWlanResource.so` 35,204 B,
`/usr/wlan/bcm/bcm4339.bin` 564,167 B and `bcm4339_mfg.bin` 552,765 B.

The repo's `extracted_a6400` tree is **not this build**: its WLAN modules and
libs have different hashes (e.g. old `mmc_drv.ko` 224,248 B vs live 224,064 B;
old `libWlanResource.so` hash differs), and its `bcm4339.bin` is 558,561 B.
The live `bcm4339.bin`/`_mfg.bin` sizes match the ZV-E10 2.03 extraction
(564,167 / 552,765 B) — i.e. the a6400 8.2.6.0 WLAN firmware generation is the
same as ZV-E10 2.03, not the older repo extraction. Receipt:
`artifacts/hardware/e0410-wifi-rootcause/firmware-identity.json`; live files
downloaded read-only to `artifacts/hardware/e0410-wifi-rootcause/live/`.

Consequences: E0407/E0408 used the older extracted tree; the live
`mmc_drv.ko`/`libWlanResource.so` were re-checked here. The live
`libWlanResource.so` still contains the **same WLAN-loader error-path null
write** at `+0x6A2E` (`ldrb r4,[r4,#2]` → `cbnz` → `strb r4,[r4]` with
`r4=0`), so E0408/E0409's crash analysis is valid for the live build.

## 3. Exact `mmcio_mount` conditions (live `mmc_drv.ko`, ARM disassembly)

`mmcioWrapper.ko` `mmcio_wrapper_init` (live, 0x51c):

1. `mmc_alloc_host(...)` and `kzalloc_mmcioWrapper`.
2. Reads Backup **`0x013E000C`** (size must be 1): low nibble = **slot**; `>=3`
   is invalid. Current value `01` → slot 1 (valid). Same value in
   `/setting/Backup.bin`, `.bak` and the Nov-10 snapshot.
3. Calls `mmcio_mount(slot)`.
4. On its result, starts IRQ/control/buswidth and `mmc_add_host`; on failure
   prints `mmcio_wrapper_init failed!`.

`mmcio_mount` (live `mmc_drv.ko`, 0x74A4–0x7580):

```
74b8  bl  mmc_hwip_system_init(slot)      ; if fail -> return error
74d0  bl  mmc_hwip_system_on_1st(slot,1)  ; if fail -> return error
74e4  bl  mmc_hwip_system_on_2nd(slot,1)  ; if fail -> return error
74fc  bl  mmc_standard_mount(slot,&info,0x48)
7504  bne error
7510  bl  mmc_hwip_system_off(slot,1)     ; ERROR PATH (observed in ring)
```

The ring contains `mmc_hwip_system_off START/END`, which is reached **only**
from the `mmc_standard_mount` failure branch (0x7508→0x7510). Therefore:

* the earlier power-on stages (`system_init`, `system_on_1st`, `system_on_2nd`)
  returned success, and
* the failure is in **`mmc_standard_mount`**, i.e. SD/MMC/SDIO card probe /
  open, not in the power-on returns.

`mmc_hwip_system_off` (0x9890) prints `mmc_hwip_system_off`, calls the
mcmnd API power-off sequence (`mcmnd_api_setmediapower(0x29,…)`,
`mcmnd_api_setportctrl`, `mcmnd_api_setpullctrl`), waits `mmc_poff_waittime`
(the ring's 13.900→14.200 = 300 ms), then returns 0 — which is why the log
shows `err 0x0` even though unmount failed.

`mmc_standard_mount` (0x718) → `do_mmc_standard_mount` (0x52c):

```
cmp slot,#3 ; do_mmc_hw_open(slot) ; mmc_trc_open(slot)
mmc_mmcp_get_uhs2_limit_freq / mmc_hw_wrapper_check_card
  -> UHS2 path if card is UHS2 (host reports UHS2 FuncTable NULL, isUSH2=0)
  -> mmc_card_open(slot, info, &ctx)   ; SD / SDIO enumeration
     mmc_mmcp_detect(_each)  (MMC)
     mmc_io_detect(_each)    (SDIO; CMD52/CCCR vendor checks)
     mmc_mem_detect(_each)   (SD memory)
     mmc_io_simple_open / mmc_mem_detect_get_csd
```

The failing sub-step is not logged by the driver (no `mmc_log_error_log`
lines in the ring), but the only code before the error branch is the card
open/probe chain; `mmc_io_detect` additionally rejects the device unless the
CMD52-read vendor bits pass (`bics #0xff000000`, `tst #0x70000000`), i.e. it
requires a **responding SDIO function**.

Conclusion from disassembly: **the SDIO host controller power/clock sequence
returns success, but no responding WLAN SDIO card is found during
`mmc_standard_mount`/`mmc_card_open`.** This is a card/host/rail-level fault,
not a firmware-download, CLM, NVRAM or `bcmdhd` problem (none of those are
reached; `bcmdhd.ko` is never loaded in the failing boot).

## 4. Read-only audit of `/setting` and Backup vs the Nov-10 snapshot

Snapshot used: `artifacts/hardware/nflasha2-readonly/nflasha2-20971520.bin`
(E0307, 2026-11-10 14:32, `/setting` FAT image). Current `/setting/Backup.bin`
and `.bak` were read read-only and diffed byte-for-byte (same 1,171,036 B).

* Current `Backup.bin` hash `951d268b…`, `.bak` `5b30be77…`; Nov-10
  `9e1f3117…` / `f9489be2…`. 83 diff runs / 550 bytes in `Backup.bin`
  (138 / 349 in `.bak`) — ordinary state churn (SID 0x35/0x36/0x3C areas,
  counters/log fields, header strings). Notably there is **no changed run in
  the WLAN/power/GPIO ID ranges**.
* Key IDs are **byte-identical** between current `.bin`, current `.bak` and the
  Nov-10 snapshot:

| ID | meaning (E0407) | current |
| --- | --- | --- |
| `0x00A50002` | WLAN power/port variant | `01` |
| `0x00A50003` | — | `02` |
| `0x00A50004` | — | 16× `00` |
| `0x00A50005` | — | `00` |
| `0x00A50006` | NVRAM power index | `09` |
| `0x00A50007` | — | `00` |
| `0x00A50008` | `/mnt` override | `00` |
| `0x01071563` | power-mode byte | `00` |
| `0x00F90365` / `0x00F90366` | port group / bit (old XWLAN_RST IDs) | `03` / `1A` |
| `0x00F905ED` / `0x00F905EE` | WLAN GPIO pair read by `initializePort_bcm4339` | `09` / `12` |
| `0x013E000C` | mmcio slot/port selector | `01` (valid) |

* `/setting` changes since Nov-10 are **debug-tooling only**: the USB debugger
  ELF grew (11,384 → 20,692 B, E0401 v2), its log changed, and newer native
  helper files exist. `/setting/usb_debug_launcher.so` (6,284 B),
  `input_sniffer.so` (70,268 B) and `touch_native_guarded_v1.so` (11,052 B)
  are hash-identical to the Nov-10 snapshot; `/etc/ld.so.preload` still lists
  only those two payloads.
* The camera runs `bsa_server` (BT stack, PID 702) and UPM power-monitor
  threads; `/dev/gpio` exists (240:0). No WLAN module is loaded; `/proc/modules`
  has only `wlanMemoryAllocator`; `wlan0` absent.

So the WLAN configuration/backup values and stock WLAN files are **not**
changed. Nothing in this audit explains a `mmc_standard_mount` card-detect
failure.

## 5. Interpretation and remaining root-cause candidates

The failure occurs **after** the SDIO host power/clock sequence (which returns
success) and **before** any WLAN firmware transfer: no responding SDIO card is
detected (`mmc_card_open` chain). The stock WLAN loader then null-writes in
its error path (`libWlanResource+0x6A2E`), crashing `WlanResource_Ma` and
rebooting the camera — a **stock firmware bug that amplifies any SDIO bring-up
failure**, not the cause of the failure.

Given the unchanged config/stock files, the remaining candidates are:

1. **Hardware/power-rail fault on the BCM4339 SDIO path** (the most likely):
   the chip does not answer SDIO enumeration despite the host power-on
   reporting success; could be the WLAN rail, reset line, SDIO bus, or the
   module itself. Repeated Wi-Fi attempts only reproduce the crash/reboot and
   should stop.
2. **Persistent chip state** that a battery-pull cold boot does not clear
   (e.g. a latched power/reset line); a service-level power-cycle/reset check
   is the next discriminator.
3. A **rare firmware/driver regression in this 8.2.6.0 build** (not explained
   by the audited files) — possible but unsupported so far; needs comparison
   with a known-good identical build or a service diagnostic, not more
   toggling.

BT (`bsa_server`) is running on the same combo chip, but that only proves the
userspace BT stack started; a meaningful BT functional test by the owner would
discriminate “whole chip dead” from “WLAN SDIO-specific”.

## 6. Proposed recovery plan (needs explicit approval before any Wi-Fi touch)

Do not enable Wi-Fi until the following steps are approved/executed in order.
Nothing here has been performed beyond read-only capture.

**P0 — Freeze and preserve (done).** Stop all Wi-Fi/OSAL attempts. Keep the
receipts: ring/dmesg, live WLAN files, current `Backup.bin`/`.bak`, `/setting`
hashes (`artifacts/hardware/e0410-wifi-rootcause/`).

**P1 — Owner-side power/battery check (no writes).**
Use a known-good, fully charged Sony battery; clean the battery contacts;
remove battery for >1 minute; boot with **no SD card** and no USB. This repeats
the already-performed cold boot with a known-good cell (the earlier 1% event
leaves the battery suspect).

**P2 — Determine whether the BCM4339 is alive (no writes).**
Owner tests Bluetooth (pair a phone/remote, or check the camera's Bluetooth
menu). If BT is also dead → shared chip/power-rail fault, go to P5. If BT
works → WLAN SDIO/reset-specific fault, continue P3/P5.

**P3 — Controlled single Wi-Fi retry (only after P1/P2, needs approval).**
Exactly one attach attempt through the stock menu, with the USB debugger
attached and ring capture ready. If the same signature appears, stop; do not
retry. If Wi-Fi comes up, immediately capture the E0408 §4 baseline before
anything else.

**P4 — Optional reversible software-exclusion test (needs separate approval).**
To rule out the `/setting` debug preloads, temporarily rename
`/setting/usb_debug_launcher.so` and `/setting/touch_native_guarded_v1.so`
to `.disabled`, cold boot once, retry Wi-Fi once, then rename them back.
This is fully reversible but disables the USB debugger launcher while active
(so the revert must be done by the owner/SD path or by pre-arranged recovery);
accept only if P1–P3 did not explain the failure.

**P5 — Service-level WLAN check.** If P1/P2 point to hardware: Sony service /
board-level check of the BCM4339 WLAN module, SDIO bus, WLAN power rail and
reset line. Do not attempt board rework without service data. If a
**matching official 8.2.6.0 firmware package** is available, compare its
`mmc_drv.ko`/`mmcioWrapper.ko`/`wlanIrq.ko`/`wlanMemoryAllocator.ko`/
`libWlanResource.so`/`bcm4339*.bin` hashes with the live files first; only a
mismatch justifies a restore (live files are stock 2021, so a restore is
expected to be a no-op).

**Do not**: flash firmware, clear/reset Backup, edit `/setting` config, or
repeat Wi-Fi attempts until P1/P2 results are known. There is no evidence that
a config or file restore would fix this; the failure is below that layer.

## 7. Bottom line

`mmcio_mount` fails in `mmc_standard_mount` card enumeration on the stock
8.2.6.0 build even after a battery-pull cold boot with no SD card. The host
power-on calls succeed; the WLAN SDIO card never answers. The `/setting` and
Backup audit shows the WLAN configuration and stock files are unchanged
(debug tooling is the only `/setting` delta), so the likely cause is the
BCM4339/SDIO power/reset path or the module itself. The camera's stock WLAN
loader then null-writes in its error path and reboots — a firmware bug that
makes every attempt look like a “Wi-Fi crash”. The next safe discriminator is
the owner-side BT/battery check (P1/P2), not more Wi-Fi toggling.
