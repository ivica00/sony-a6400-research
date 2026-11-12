# E0408 — BCM4339 CLM blob parse (a6400 normal/mfg, ZV-E10) and the blocked WLAN baseline attempt

Date: 2026-11-12. Step 1 is offline static analysis. Step 2 was the
explicitly authorized single bounded, read-only WLAN-active observation — but
WLAN could not be brought to a usable active state safely: one authorized
activation attempt reached the WLAN module-load path, then the camera
warm-rebooted. **No persistent flash/Backup writes were made.** The camera is
healthy in Mass Storage afterwards. Details and receipts below.

## 0. Inputs and tools

* a6400 normal FW: `wlan/bcm/bcm4339.bin` 558,561 B, SHA-256 `6b720704c8fc3914…`
* a6400 factory FW: `wlan/bcm/bcm4339_mfg.bin` 549,271 B, SHA-256 `1a9356667894c5cd…`
* ZV-E10 2.03 normal FW: `bcm4339.bin` 564,167 B, SHA-256 `cbb464370e3a9547…`
* Parser: `artifacts/analysis/e0408-clm-baseline/bcmclm_parse.py` (Python,
  read-only), following the `CLM DATA` header/lookup layout of OpenWrt
  firmware-utils `bcmclm.c`
  (<https://git-03.infra.openwrt.org/project/firmware-utils/plain/src/bcmclm.c>).
* Format context: Quarkslab, *Reverse-engineering Broadcom wireless chipsets*
  (<https://blog.quarkslab.com/reverse-engineering-broadcom-wireless-chipsets.html>):
  RAM firmware is either a plain blob with a version/CRC/date trailer or a TRX
  image; BCM4339 RAM is loaded at `0x180000`; the RAM firmware carries code,
  data and the D11 microcode.
* Raw receipts: `artifacts/analysis/e0408-clm-baseline/clm-parse.json`,
  `clm-comparison.json`, `lib` disassembly/rodata dumps of the relevant
  libraries; Step-2 receipts under `artifacts/hardware/e0408-wlan-baseline/`.

## 1. Firmware format checks (what applies to these a6400 images)

* All three files are the **plain RAM-firmware blob** format, not TRX: no
  `HDR0`/`TRX` magic, no `rtecdc` string (count 0), and the file ends with the
  familiar version/FWID trailer (`… clm_43xx_sony_DI Version: 6.37.39.81 …
  FWID 01-ca76f58c`).
* The `0x180000` RAM load layout is confirmed independently: for every CLM
  header found, `offsets_fixup = clm_offset − virtual_header_address =
  −0x180000`, i.e. the CLM's virtual addresses are the file offset plus
  `0x180000` (SRAM base).
* The CLM block is located by the OpenWrt predicate (`"CLM DATA"` magic at a
  4-byte-aligned offset, with `unk & 0xff00ffff == 0`). Header fields parsed:
  magic `CLM DATA`, `unk0`, `unk1`, API string, compiler string, virtual header
  address, virtual lookup-table address, `ClmImport` version, manufacturer.
  The lookup table is at `virtual_lookup_address + fixup`; entries 0 and 1 are
  `channels_2ghz` and `channels_5ghz` lookups (`{num, offset}` each), followed
  by further table offsets. Channel ranges are `{first, last, unknown}` bytes.

## 2. Parse results (verified)

| Image | CLM offset | API | Compiler | ClmImport | 2.4 GHz ranges | 5 GHz ranges |
| --- | --- | --- | --- | --- | --- | --- |
| a6400 normal | `0x77EA0` | `9.10.50` | `1.26.11` | `1.36.3` | 1–13 | **34–46, 36–64, 100–144, 149–177** |
| a6400 mfg | `0x75AB0` | `9.10.50` | `1.26.11` | `1.36.3` | 1–13 | **34–46, 36–64, 100–144, 149–177** |
| ZV-E10 normal | `0x79058` | `9.10.139` | `1.26.11` | `1.36.3` | 1–13 | **34–46, 36–64, 100–144, 149–177** |

Virtual header addresses: a6400 normal `0x1F7EA0`, a6400 mfg `0x1F5AB0`,
ZV-E10 `0x1F9058`; all with `fixup = −0x180000`.

Additional comparisons:

* **a6400 normal vs a6400 mfg CLM:** after normalizing the virtual-address
  fields (relative offsets), both extracted CLM windows are the same size
  (7,051 bytes — heuristic bounds; the CLM block has no explicit length field)
  and the content is largely identical (long SAME runs, e.g. `0x430–0x1800` and
  `0x1830–0x1A90`); only a handful of small regions differ (e.g.
  `0x90–0xB0`, `0xD0`, `0x110`, `0x170`, `0x1B0`, `0x2F0`, `0x420`,
  `0x1800–0x1830`, `0x1A90–0x1B90`). The channel declarations are identical.
* **a6400 normal vs ZV-E10 normal CLM:** same channel declarations; the
  extracted ZV-E10 window is larger (≈7.8 KB vs ≈7.0 KB) and the blobs differ
  substantially after the common prefix — ZV-E10 is API `9.10.139` vs
  `9.10.50`, i.e. an updated CLM dataset/tables, not a different band
  capability.

### Conclusion for the 5 GHz question

**The a6400 normal firmware CLM already carries 5 GHz channel tables**
(identical ranges to the factory firmware and to ZV-E10 2.03). 5 GHz is
therefore **not** gated by the absence of `band a`/5 GHz entries in the normal
`bcm4339.bin` CLM, and it is **not** “hidden only in `bcm4339_mfg.bin`” — the
mfg CLM is essentially the same band dataset (same API version and identical
channel ranges).

What remains different/undecoded offline:

1. The CLM API/tables version and per-channel power/regulatory entries
   (`9.10.50` vs `9.10.139`) are only partially decoded; a per-country/
   `regrev` power/disable table could still suppress 5 GHz operation at
   runtime even though the channel ranges exist.
2. a6400's control path selects one power mode (`high/`+`low/` NVRAM dirs,
   no per-band model), while ZV-E10 selects per-band power tables
   (`2_4GHz_*_5GHz_*`) — see E0407. That is a *product configuration*
   difference, not a CLM absence.
3. The only way to decide whether the normal FW exposes 5 GHz channels is a
   live `wl bands`/`wl chanlist`/`iw phy` (and later, if authorized, a
   `wl band a` TX test) with the normal firmware — exactly the Step 2 that is
   currently blocked.

## 3. Step 2 — authorized WLAN-active baseline: attempt and blocker

### 3.1 Pre-state (read-only)

* Debugger: `A6400_USB_DEBUG_V1`, protocol 2, `usb_extcmd`, camera uid/euid 0;
  USB UDC `dwc3.0` configured, high-speed; camera enumerated as MSC/MTP;
  `modules.custom=none`.
* App `im.elf` PID 149, `bsa_server` PID 705, uptime 7,842 → 8,263 s.
* **WLAN off:** only `wlanMemoryAllocator` loaded; no `bcmdhd`/`cfg80211`/
  `mmc_core`/`mmcioWrapper`/`wlanIrq`; no `wlan0` interface; `/sys/class/net`
  contains only `lo`/`tunl0`/`gre0`/`sit0`/`ip6tnl0`.
* OSD A/B captured read-only via im.elf's `/dev/stream` mappings
  (`0x0BFD0000`/`0x0CFDD000`) using debugger process-memory reads: a
  PlayMemories Mobile/Home USB guide screen with an “OK” button.

### 3.2 Activation attempts (bounded, RAM-only)

1. **UI key injection** through the established input queue
   `/usr/bin/sndcmd.elf --sync 0x007A018C d:2 d:<key> d:0 d:1|0 d:0`
   (MENU `0x1AC`, ENTER `0x1AD`): the OSD changed once (a checkbox state
   changed), but no menu was opened and no WLAN state changed; subsequent keys
   did not alter the screen.
2. **Direct OSAL message `0x3100`** to the WlanResource API queue
   (`sndcmd.elf --sync 0xA503FB d:0x3100 d:0x0000 d:0x0000`): no effect; no
   modules, no `wlan0`, camera normal.
3. **Direct OSAL message `0x1000`** (the message NetService itself sends as its
   “start WLAN” request; power-mode byte 0) to `0xA503FB`:
   * at t = 8,298.08 s the WLAN start path ran: `compat`/`cfg80211` loaded,
     `wlanMemoryAllocator` allocated 32,768 B for `mmcioWrapper`;
     `mmc_hwip_system_off START/END`; then **`mmcio_mount failed!`** and
     **`mmcio_wrapper_init failed!`**;
   * `usbg_ext_cmn.c(586): [E]OtherErr [-512]` appeared five times;
   * the **WlanResource_Ma thread faulted** — register dump `pc=0x083E7A2E`
     (libWlanResource base `0x083E1000` → `+0x6A2E`, the
     `loadWlanHostDrivers_bcm4339` module-load/error path),
     `lr=0x040118ED`, `r5=0x008F0139` (ULOG queue);
     `[current task] program: im.elf(WlanResource_Ma) (pid 347, cpu 3)`,
     `trap_no 0x0E`, `error_code 0x817`, *page translation fault (0x817) at
     address 0x00000000*;
   * the exception monitor ran, then the camera **warm-rebooted**
     (`WARMBOOT`, low-level resume).

### 3.3 Post-state and cleanup

* Rebooted camera: uptime reset; new `im.elf` PID 149 and `bsa_server` PID 705;
  MS Windows still sees ILCE-6400; USB UDC configured, high-speed;
  `modules.custom=none`.
* WLAN remains off: only `wlanMemoryAllocator` loaded; no `wlan0`.
* Camera responsive and stable: uptime advanced 52.96 → 67 → 109.79 → 130.84 →
  207.91 s across the checks; final OSD A/B match the pre-state USB guide
  screen; final `usb-state` shows MSC configured/high-speed and
  `modules.custom=none`.
* No flash/Backup writes; no camera files were written; no modules remain
  loaded. The only UI state change was a checkbox visibly toggled in the USB
  guide; it was not confirmed and was reset by the reboot.
* Receipts: `artifacts/hardware/e0408-wlan-baseline/`
  (`step2-attempt-receipt.json`, `dmesg-after-reboot.txt`,
  `ring-after-reboot.txt` with the warm-boot klog ring,
  `wlan-start-crash.log` excerpt).

### 3.4 Interpretation

The injection did reach the app's WLAN start path (module loading and
`wlanMemoryAllocator` traffic prove it), but it **bypassed the WLAN power/port
initialization sequence** that the normal UI/NetService flow performs
(`startWlan` → `setPortToStartWlan_bcm4339` → GPIO/power settle before the
driver attach). Without the radio/SDIO being powered up, `mmcio_mount` failed
and the driver attach aborted; the subsequent failure path in
`libWlanResource+0x6A2E` dereferenced a null pointer and the camera rebooted.

Consequences:

* **Direct OSAL “start WLAN” injection is not a safe activation path** while
  the camera is in USB Mass Storage with the radio unpowered. Do not retry it.
* **The Step 2 baseline was not collected** — no `wl`/`iw`/`sysfs` live values,
  no SDIO clock, no iperf throughput. The E0407 static predictions (normal
  firmware, `low/` NVRAM, `dhd_irq=129`, `clockoverride=0`) remain unverified
  live.

## 4. Recipe for the deferred baseline (when the camera itself has Wi-Fi up)

Only after the camera starts Wi-Fi through a supported path (for example the
camera's own “Send to Smartphone”/“Ctrl with Smartphone” flow with USB
disconnected, or another state the owner confirms as Wi-Fi-active) run the
following read-only queries (root shell/debugger). These are the exact checks
that were planned for this document:

```
cat /sys/module/bcmdhd/parameters/firmware_path
cat /sys/module/bcmdhd/parameters/nvram_path
cat /sys/module/bcmdhd/parameters/dhd_irq
cat /sys/module/bcmdhd/parameters/clockoverride
wl -i wlan0 status
wl -i wlan0 bands
wl -i wlan0 chanspec
wl -i wlan0 pm
wl -i wlan0 mpc
wl -i wlan0 lpc
iw phy
iw dev wlan0 get power_save
cat /proc/interrupts | grep -Ei 'mmc|dwc|wlan'
dmesg | grep -Ei 'bcmdhd|dhd|sdio|mmc|wlan'
```

Expected from E0407 (to be confirmed): normal firmware
`/usr/wlan/bcm/bcm4339.bin`, NVRAM `…/nvram/low/bcm4339_L_<NN>.txt` (LOW is
the static prediction), `dhd_irq=129`, `clockoverride=0`. The `wl bands`/
`wl chanlist`/`iw phy` output is the direct answer to whether the normal
firmware exposes 5 GHz channels. An `iperf` baseline additionally needs a
network peer on the same WLAN; that was never reached here.

## 5. Bottom line

* The a6400 normal firmware CLM **does** contain 5 GHz channel ranges (and the
  mfg CLM is essentially the same); the 5 GHz question is therefore about
  runtime power/regulatory/runtime exposure, not absent CLM entries.
* The authorized WLAN-active baseline is **blocked** by the camera's current
  state: Wi-Fi is off in USB Mass Storage; the one authorized activation
  attempt reached the module-load path, failed at `mmcio_mount` because the
  radio/power sequence was bypassed, and the WlanResource fault path rebooted
  the camera. The camera recovered to the same Mass Storage state with no
  persistent writes.
* Next safe step: have the camera start Wi-Fi through its supported UI/flow
  (or explicitly authorize a different, verified activation method), then
  rerun the read-only baseline recipe in §4. Do not repeat the direct 0x1000
  injection.
