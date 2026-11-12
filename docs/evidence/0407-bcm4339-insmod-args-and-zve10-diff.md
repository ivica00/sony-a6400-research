# E0407 — bcmdhd insmod arguments, compiled defaults, CLM ownership, and a6400↔ZV-E10 WLAN/BT diff

Date: 2026-11-12. **Offline static analysis only.** No camera I/O, no module load,
no radio transmit, no flash/partition write. All results come from the already
extracted a6400 8.2.6.0 image and the ZV-E10 2.03 reference image, plus Capstone/
pyelftools disassembly of the preserved ELF files. Evidence artifacts:
`artifacts/analysis/e0407-bcm4339-insmod-args/`.

## 0. Inputs and identities

| File | a6400 size / SHA-256 (first 16) | ZV-E10 size / SHA-256 (first 16) |
| --- | --- | --- |
| `lib/libWlanResource.so` | 35,248 / `1892e7684090972f…` | 35,240 / `41629f4785072359…` |
| `lib/libNetService.so` | 682,040 / `1557bfa2c3e205e3…` | 674,776 / `da6f6d6900b0f47d…` |
| `lib/libWlanAdjust.so` | 55,984 / `178a885acae4fd9e…` | 56,308 / `a3b9e7226a2db5b9…` |
| `kmod/bcmdhd.ko` | 492,512 / `6ba8c852e9eccaa6…` | 522,740 / `bb3522abe11ec8cd…` |
| `kmod/cfg80211.ko` | 197,856 / `7b1ef3788a669964…` | 192,992 / `536d8164d350e3fb…` |
| `kmod/mmcioWrapper.ko` / `wlanIrq.ko` / `wlanMemoryAllocator.ko` | 6,760 / 3,788 / 7,080 | 6,788 / 3,800 / 8,268 |
| `bin/bsa_server` | 4,802,499 / `dac46418c82ed0e6…` | 5,390,567 / `cfad2e351a3f82a4…` |
| `bin/wpa_supplicant` | 758,180 / `91236ba7b42335f0…` | 766,436 / `766e8855fc9ac76c…` |
| `bin/Wltestcmd` | 22,127 / `a0817c1f96ec2327…` | 30,159 / `57e5bcab4a8e78f0…` |
| `bin/startBTCore.sh` | 1,283 / `33c82447cdbcdbd2…` | 1,283 / `33c82447cdbcdbd2…` (identical) |
| `lib/netconf/p2p.conf`, `bss.conf`, `p2p_multi_go.conf` | `d57a4e64…`, `ea1ec953…`, `d57a4e64…` | identical |

Firmware: a6400 `wlan/bcm/bcm4339.bin` 558,561 B / `6b720704…`;
ZV-E10 564,167 B / `cbb46437…`. mfg firmware: a6400 `bcm4339_mfg.bin`
549,271 B / `1a935666…`.

## 1. Exact bcmdhd load path (a6400, verified instructions)

`WlanResource::loadWlanHostDrivers_bcm4339(bool testOrMfg, unsigned char powerMode)`
(`0x6939`, 308 B) loads **six modules in this order**, from the
`.data.rel.ro` table at `0x8054`:

1. `/usr/kmod/wlanIrq.ko` (no args)
2. `/usr/kmod/compat.ko` (no args)
3. `/usr/kmod/cfg80211.ko` (no args)
4. `/usr/kmod/mmc_core.ko` (no args)
5. `/usr/kmod/mmcioWrapper.ko` (no args)
6. `/usr/kmod/bcmdhd.ko` **with one args string only**

(`mac80211.ko` is shipped but is *not* loaded by this path; bcmdhd is fullmac
over cfg80211.)

`insmod(path,args)` (`0x6468`, 120 B) does not shell out:
`open(path, O_RDONLY)` → file stat via local wrapper (`0x6db4`) → `mmap` →
`syscall(128, image, length, args)` (`__NR_init_module`) → `munmap` → `close`.
The args string is passed verbatim as the module's `param_values`.

### 1.1 bcmdhd args string — the only thing the product passes

`get_bcmdhd_insmod_args(unsigned char powerMode, char *out, bool mfg, char allowMnt)`
(`0x6731`, 520 B) selects one of **eight literal templates** and fills one
format field:

| # | template (verified rodata string) |
| --- | --- |
| 1 | `firmware_path=/usr/wlan/bcm/bcm4339_mfg.bin nvram_path=/usr/share/network/nvram/high/bcm4339_H_%02d.txt` |
| 2 | `…bcm4339_mfg.bin …/nvram/low/bcm4339_L_%02d.txt` |
| 3 | `…bcm4339.bin …/nvram/high/bcm4339_H_%02d.txt` |
| 4 | `…bcm4339.bin …/nvram/low/bcm4339_L_%02d.txt` |
| 5–8 | same four with `/mnt/`-prefixed firmware images (`/mnt/bcm4339_mfg.bin`, `/mnt/bcm4339.bin`) |

The `%02d` value is the byte read at entry from **Backup ID `0xA50006`**
(`0x01071563` is a *different* backup ID used for the default power mode; see
below). The value is validated `≤ 0x0F`; the files `_01.._15` carry
`regrev=75..89`, i.e. index *N* → regrev *74+N*.

Selection logic (verified branch structure):

* `powerMode == 1` → `high/…_H_%02d.txt`; any other value → `low/…_L_%02d.txt`.
* `mfg != 0` → `bcm4339_mfg.bin`; else `bcm4339.bin`.
* `allowMnt != 0` → probe `/mnt/bcmdhd.ko` (and `/mnt/bcm4339[_mfg].bin`); if the
  probe fails, fall back to `/usr` paths.
* No other module parameters appear anywhere in the templates → **the product does
  not pass `dhd_irq`, `clockoverride`, `txglom`, `sd_clock`, `sd_blockmode`,
  `sd_blocksize`, `sd_dma`, or any other param.** All of those are either
  compiled-in defaults (§2) or runtime iovars (not insmod args).

### 1.2 Which mode is used at runtime

* `loadWlanHostDrivers_bcm4339` receives its two bytes from
  `startWlan(bool testOrMfg, unsigned char powerMode)` (`0x4e29`, 448 B).
* Normal message-handler start (e.g. `processMessage` case at `0x5770`):
  `startWlan(<mfg/test flag from the message>, GetPowerMode())`;
  `GetPowerMode` returns the BSS global `0x8454`, whose only identified writer
  is `SetPowerMode` (`0x300c`; no init/resume writer found). No factory-adjust
  command at boot means **default 0 → `low/` NVRAM**. The adjust dispatcher
  sets it from message ids `0x1000`/`0x1011` (`SetPowerMode(byte)`), and the
  WLAN test start path (`0x35f8`–`0x3602`) passes `GetTestMode()` as the
  mfg/test flag.
* A second start path (`0x5ab0`) calls `startWlan(0, 0xFF)`; `powerMode == 0xFF`
  makes `loadWlanHostDrivers_bcm4339` read **Backup ID `0x01071563`** for the
  power mode (so 0xFF = “use stored default”).
* `/mnt` override: `loadWlanHostDrivers_bcm4339` reads **Backup ID `0xA50008`**;
  if the byte is `1`, it runs `system("mount -t vfat /dev/mmca1 /mnt")` and
  prefers `/mnt` module/FW paths.

Thus, the only writes this path performs are:
`firmware_path=<one of 8 templates>.bin` and `nvram_path=<…high|low…>_<index>.txt`.

### 1.3 Other verified backup/GPIO dependencies

`initializePort_bcm4339` (`0x6aa8`, 176 B): opens `/dev/gpio`, reads Backup IDs
`0x00F905ED` and `0x00F905EE` (validated `!= 0xFF`), issues
`ioctl(0xC0104702)` = `GPIO_CMD_SET_MODE` for the WLAN power/reset pins, then
settle delays (10,000 and 1,000 units) — power sequencing only, no throughput
effect. WLAN rail power itself goes through OSAL command `0xA503FB`
(seen in the retained `sndcmd.elf --sync 0xA503FB d:0x1020` script).

## 2. bcmdhd.ko compiled defaults (37 module params)

`bcmdhd.ko` `.modinfo` only describes `dhd_irq` and `clockoverride`; the full
`__param` table has 37 entries. Defaults recovered from the ELF parameter table
(`bcmdhd.module_params.json` + `bcmdhd.param_perms.json`):

| param | default | perm | notes |
| --- | --- | --- | --- |
| `firmware_path` | `""` | 0660 | passed by product |
| `nvram_path` | `""` | 0660 | passed by product |
| `iface_name` | `""` | 0000 | not passed; empty default (fallback naming not decoded) |
| `info_string` | `""` | 0444 | — |
| `dhd_irq` | **129** | 0644 | “DHD oob gpio number”; product does not pass it |
| `clockoverride` | **0** | 0644 | “SDIO card clock override”; product does not pass it |
| `sd_f2_blocksize` | 512 | 0000 | SDIO F2 block size |
| `sd_hiok` | 0 | 0000 | SD high-speed flag (semantics not decoded) |
| `sd_sdmode` | 2 | 0000 | SD mode selector |
| `sd_divisor` | 2 | 0000 | clock divisor |
| `sd_clock` | 1 | 0000 | clock selector |
| `sd_power` | 1 | 0000 | — |
| `sd_msglevel` | 1 | 0000 | debug level |
| `dhd_deferred_tx` | 1 | 0000 | deferred TX enabled |
| `dhd_intr` | 1 | 0000 | interrupt mode |
| `dhd_poll` | 0 | 0000 | no polled mode |
| `dhd_idletime` | 5 | 0000 | idle time value |
| `dhd_slpauto` | 1 | 0000 | auto-sleep enabled |
| `dhd_watchdog_ms` | 10 | 0000 | watchdog interval |
| `dhd_sdiod_drive_strength` | 6 | 0000 | SDIO pad drive strength |
| `dhd_rxbound` / `dhd_txbound` | 0 / 0 | 0000 | unthrottled |
| `dhd_dpcpoll` | 0 | 0644 | — |
| `dhd_doflow` | 1 | 0644 | flow control |
| `dhd_arp_mode` / `dhd_arp_enable` | 9 / 1 | 0000 | ARP offload |
| `dhd_pkt_filter_enable` | 1 | 0000 | packet filter |
| `dhd_msg_level` | 1 | 0000 | errors only |
| `instance_base` | 0 | 0644 | — |
| `op_mode` | 0 | 0644 | — |
| `disable_proptx` | 0 | 0644 | — |
| `dhd_dongle_ramsize` / `dhd_rxf_prio` / `dhd_dpc_prio` / `dhd_watchdog_prio` / `dhd_master_mode` / `dhd_pkt_filter_init` | 0 / 1 / 1 / 0 / 1 / 0 | 0000 | scheduler/packet settings |

Notes:

* Most params have `perm=0000` → **no sysfs entry**; they can only be changed by
  re-loading the module (`rmmod`/`insmod`) with explicit args.
* `dhd_irq`, `clockoverride`, `disable_proptx`, `op_mode`, `dhd_dpcpoll`,
  `dhd_doflow` are 0644 (sysfs-writable names), but they are read at
  init/attach time; writing the sysfs file does not by itself reconfigure the
  running bus.
* `txglom`, `rxglom`, `txglomsize`, `sd_blockmode`, `sd_blocksize`, `sd_dma`
  are **iovars, not module params** (strings present; no `__param` entries).
  Their live state therefore comes from the driver defaults and can be queried/
  changed with `wl` at runtime.
* A direct `.text` data-reference audit found live references for
  `dhd_intr`, `dhd_poll`, `dhd_idletime`, `dhd_deferred_tx`, `dhd_slpauto`,
  `dhd_watchdog_ms`, `dhd_dpc_prio`, `dhd_watchdog_prio`,
  `dhd_sdiod_drive_strength`, `dhd_arp_mode`, `dhd_msg_level`; no direct
  reference was found for `sd_clock`, `sd_divisor`, `sd_sdmode`,
  `sd_f2_blocksize`, `sd_power`, `sd_msglevel`, `dhd_irq`, `clockoverride`
  (they exist as parameter-table entries; indirect/param-table use cannot be
  excluded from this audit).

## 3. CLM / regulatory: driver vs firmware ownership

* **bcmdhd.ko contains no CLM data at all** — zero occurrences of `CLM`/`clm`/
  `CLM DATA`. It only carries country/chanspec plumbing:
  `wldev_set_country`, `dhd_bus_country_set`, `dhd_get_customized_country_code`,
  `wifi_platform_get_country_code`, `wiphy_apply_custom_regulatory`,
  `country`, `chanspec`, “country code setting failed”, etc.
* **cfg80211.ko** exposes only two regulatory knobs:
  `cfg80211_disable_40mhz_24ghz` (bool, default **0** → 40 MHz in 2.4 GHz is
  *not* disabled) and `ieee80211_regdom` (charp, default **"00"**, i.e. world).
* **CLM lives in the firmware image**: `bcm4339.bin` contains `CLM DATA`,
  `ClmImport: 1.36.3`, and the banner suffix `clm_43xx_sony_DI`. CLM marker
  offsets are `0x77EA0` (a6400) and `0x79058` (ZV-E10); nearby metadata differs
  (CLM data version `9.10.50` vs `9.10.139`, build date 2017-08-10 vs
  2020-03-16) and the FW banner gains `-toe` on ZV-E10. The CLM blob body is
  not decoded by this pass.
* The a6400 product path passes **no country/band argument** and does not call
  `wl band`/country itself. Band policy in user space is limited to:
  `p2p_oper_reg_class=81` (2.4 GHz) in `p2p.conf`; `NsMiscSetGOBand`/
  `GetGOBand` (NetService); `WlanAdjust::wlanSetChRange` (factory adjust).
  Station mode has no band restriction in `wpa_supplicant` config, so the
  channel list reported by the driver/FW is what it would scan.

**Answer to the CLM question:** 5 GHz / 40 / 80 MHz is **not** blocked by
`bcmdhd.ko` (it has no CLM blob and no static channel table). The gate can only
be (a) the firmware CLM identified by `clm_43xx_sony_DI`/`ccode=XR`/`regrev`,
and (b) product/user-space band policy. Whether the a6400 **normal** firmware
CLM admits `band a` cannot be decided from static strings; it needs a runtime
`wl chanlist`/`iw phy`/`wl band a` observation with normal FW (a radio-state
change, not covered by read-only authorization).

**Important caveat:** the shipped factory 5G test path does *not* prove normal-FW
5G. `Wltestcmd` channels are 1–165 and it invokes `wl band a`/`5g_rate`, but the
`StartTest` path runs `SetTestMode` → `GetTestMode()` → `startWlan(mfg=testMode)`
→ `get_bcmdhd_insmod_args(..., mfg=true)` → **`bcm4339_mfg.bin`** (manufacturing
firmware), not the normal firmware. So the 5G test capability is a mfg-FW
capability until proven otherwise.

## 4. a6400 vs ZV-E10 2.03 — WLAN/BT configuration diff

### 4.1 Identical

* `bin/startBTCore.sh` — byte-identical (`33c82447…`); BSA is launched with the
  same flags on both models (`-k /tmp_bt/ble_local_keys -u /tmp_bt/
  -d /dev/ttyBT -all=0`, plus SAR/normal `-p` firmware), **no `-lpm`, no
  `-ssbi`** on either model.
* `lib/netconf/p2p.conf`, `bss.conf`, `p2p_multi_go.conf` — byte-identical.
* `bcmdhd.ko` module parameter table and defaults — identical 37 params/values.
* `wpa_supplicant` version string — `v2.1-devel` on both (build differs).
* `Wltestcmd` 5 GHz TX/RX support (`band a`, channels 1–165) exists on both.

### 4.2 Different (ZV-E10 is per-band-aware; a6400 is single-band)

* `libWlanResource.so`:
  * a6400: `startWlan(bool,u8)` (`0x4e29`), `loadWlanHostDrivers_bcm4339(bool,u8)`
    (`0x6939`), `get_bcmdhd_insmod_args(u8,char*,bool,char)` (`0x6731`).
  * ZV-E10: `startWlan(bool,u8,u8)` (`0x4f05`), `loadWlanHostDrivers_bcm4339(bool,u8,u8)`
    (`0x6bd1`), `get_bcmdhd_insmod_args(u8,char*,bool,char,u8)` (`0x6885`),
    plus a new `convertPowerModeToPowerModeEachFreq(u8, u8*)` (`0x3045`, 188 B).
    `processMessage` is 1,456 B vs 1,364 B.
* NVRAM templates:
  * a6400 (8 templates): `…/nvram/high/bcm4339_H_%02d.txt` and
    `…/nvram/low/bcm4339_L_%02d.txt` (15 files each, regrev 75–89).
  * ZV-E10 (12 templates): `2_4GHz_high_5GHz_high/bcm4339_H_H_%02d.txt`,
    `2_4GHz_low_5GHz_high/bcm4339_L_H_%02d.txt`,
    `2_4GHz_low_5GHz_low/bcm4339_L_L_%02d.txt` (27 files each, regrev 75–147).
  * ZV-E10 `convertPowerModeToPowerModeEachFreq` mapping (verified): `1` → 1
    (H_H); `0xFF` → read Backup `0x01071563`; otherwise read Backup `0xA50009`
    and `0xA5000A` (the L_H combination shows the first is the 2.4 GHz mode and
    the second the 5 GHz mode): 0/0 → 0 (L_L), 1/1 → 1 (H_H), 0/1 → 2 (L_H).
  * a6400 has no per-band mapping; the single global power-mode byte (Backup
    `0x01071563` default, or `SetPowerMode`) picks `high/` or `low/`.
* `libNetService.so`: ZV-E10 adds explicit 5 GHz / channel APIs missing from
  a6400: `isValidWifi5GHz`, `NsMiscFreqToBand`, `NsMiscEnableDynamicBandWidth`,
  `NsMiscGetAvailableWifiChRange`, `NsMiscGetApChannel`, `NsMiscSetApChannel`,
  `NsMiscGetGOPowerModeFromBackup`, plus Wi-Fi ifconfig and PcRemote-PSK
  helpers. a6400 has none of these.
* `libWlanAdjust.so`: ZV-E10 adds `wlanLoadFirmwareTest` and
  `UnLoadAndLoadFirmware(u8,u8,u8,u8)` (firmware reload/test variants).
* Firmware: 6.37.39.81 (2017) vs 6.37.39.113 (2020, `-toe`), and the newer
  driver/build set (`bcmdhd.ko` 522,740 vs 492,512; cfg80211 192,992 vs 197,856;
  wlanMemoryAllocator 8,268 vs 7,080; etc.).

### 4.3 What the diff means

The module/NVRAM hardware description already carries 5 GHz calibration on
a6400 (E0406), but the **a6400 control path has no per-band power/channel
model**: one power mode, two NVRAM dirs, no `isValidWifi5GHz`/band-channel
NetService API, no `convertPowerModeToPowerModeEachFreq`. ZV-E10 2.03 has that
model (three band-power dirs, 5 GHz APIs, per-band conversion). This is the
strongest static evidence that normal-mode 5 GHz on a6400 is a
product/control-path limitation rather than a radio limit — but it still does
not prove whether the a6400 normal FW CLM allows or denies band a.

## 5. Reversible lever inventory (what can be changed without flash, and what cannot)

### 5.1 Volatile RAM-only (no flash write; still camera state changes requiring authorization)

Reads (baseline evidence, once WLAN is enabled):
`cat /sys/module/bcmdhd/parameters/{firmware_path,nvram_path,dhd_irq,clockoverride,…}`
(the first two are 0660 and show the actual template selected);
`wl -i wlan0 status`, `wl pm`, `wl mpc`, `wl lpc`, `wl bands`, `wl chanlist`,
`wl bss`, `wl rssi`; `iw phy`, `iw dev wlan0 info`,
`iw dev wlan0 get power_save`; `/proc/interrupts` (mmc0/irq);
`dmesg` filtered for `bcmdhd|dhd|sdio|mmc`; `/sys/kernel/debug/mmc*/ios` if
debugfs is mounted.

Writes that are volatile (driver RAM state, revert by toggling WLAN/reboot):
`wl -i wlan0 pm 0|1|2`, `wl -i wlan0 mpc 0|1`, `wl -i wlan0 lpc …`,
`wl -i wlan0 txpower …`, `wl -i wlan0 chanspec/band …`,
`wl -i wlan0 ampdu …`, `wl -i wlan0 wme_apsd …`, `wl -i wlan0 wowl …`,
`wl -i wlan0 keepalive …`, `wl -i wlan0 arp …`, `wl -i wlan0 pkt_filter …`,
`wl -i wlan0 rateset …`, `wl -i wlan0 coex/btc_params …`;
`iw dev wlan0 set power_save on|off`; `wpa_cli` runtime commands; `iperf`
(2.0.5 shipped) for measurement.

Module reload with explicit args (RAM only, but requires WLAN down + root):
`insmod bcmdhd.ko firmware_path=… nvram_path=… sd_hiok=1 sd_clock=… sd_divisor=…
clockoverride=… dhd_irq=… dhd_poll=… dhd_slpauto=… dhd_idletime=…
dhd_watchdog_ms=… dhd_sdiod_drive_strength=…`. Note: these are init-time values
and many have `perm=0000`; the exact effect of `sd_*`/`clockoverride` in the
mmcioWrapper build is unresolved (no direct code references found for several
of them), so treat any expectation as a test, not a guarantee.

BT (RAM only): restart `bsa_server` manually with `-lpm` and/or `-ssbi`
(flags supported by the shipped stack, absent from `startBTCore.sh` on both
models); run `btRFTest.elf` LE TX/RX/LPM tests. Revert by restarting the normal
script.

### 5.2 Persistent (flash/config; not authorized now)

* NVRAM files under `/usr/share/network/nvram/…` (H/L or band-power dirs).
* Backup IDs: `0xA50006` (NVRAM file index 1–15), `0x01071563` (default power
  mode), `0xA50008` (SD `/mnt` override switch), `0xA50009`/`0xA5000A`
  (ZV-E10 2.4G/5G power modes), `0xA50002` (WLAN power/port variant),
  `0x00F905ED`/`0x00F905EE` (WLAN GPIO pins). Writing any of these persists.
* `startBTCore.sh` flags (`-lpm`/`-ssbi`), `p2p_go_ht40`/`p2p.conf`/`bss.conf`.
* Replacing `bcmdhd.ko`, `cfg80211.ko`, `bcm4339.bin`/`_mfg.bin` (different
  build or ZV-E10 code) — flash write + module authentication/vermagic/CLM risk.

## 6. Proposed bounded baseline (requires explicit scope because it starts WLAN)

One authorized, bounded session could settle every “predicted but unverified”
item with reads only after WLAN is brought up normally:

1. `cat /sys/module/bcmdhd/parameters/firmware_path` → expect
   `/usr/wlan/bcm/bcm4339.bin`.
2. `cat /sys/module/bcmdhd/parameters/nvram_path` → expect
   `…/nvram/low/bcm4339_L_<NN>.txt` (prediction: LOW default) and record `<NN>`.
3. `cat /sys/module/bcmdhd/parameters/dhd_irq` / `clockoverride` → expect
   `129`/`0` (compiled defaults, since product passes neither).
4. `wl -i wlan0 status`; `wl pm`; `wl mpc`; `wl lpc`; `wl bands`;
   `wl chanlist`; `iw phy`; `iw dev wlan0 get power_save` — record live
   power-save/band/channel facts.
5. `dmesg | grep -iE 'bcmdhd|dhd|sdio|mmc'` and `/proc/interrupts` — record the
   actual SDIO clock/IRQ line and whether OOB IRQ or SDIO IRQ is in use.
6. `iperf` baseline capture (measurement only, but it is traffic; separate
   explicit authorization if treated as load rather than observation).

Any `wl band a`/`chanspec`/TX test is a radio write, not a read: it should be a
separate explicitly-authorized step, and it must be run with the **normal**
firmware (test mode off) to answer the 5 GHz question.

## 7. Bottom line

* The a6400 loads bcmdhd with exactly one string:
  `firmware_path=<usr|/mnt>/…/bcm4339[ _mfg].bin nvram_path=<usr|/mnt>/…/{high|low|(ZV band dirs)}/…_%02d.txt`,
  plus the six-module load order above; **no perf/SDIO/OOB params are passed**.
* Driver defaults are now recorded (37 params, perms included): auto-sleep on,
  deferred TX on, interrupt mode on, poll off, SDIO block 512, `sd_hiok=0`,
  `clockoverride=0`, `dhd_irq=129`.
* CLM is firmware-side (`clm_43xx_sony_DI`), never in bcmdhd.ko; cfg80211
  defaults do not restrict band/40 MHz (regdom “00”, 2.4 GHz-40 MHz allowed).
* ZV-E10 2.03 has an explicit per-band (2.4G/5G) power/channel/NetService model
  that a6400 lacks; that is the most plausible reason 5 GHz is not a product
  feature on a6400, but whether the normal a6400 FW CLM denies it is still
  unresolved offline.
* All reversible knobs are runtime/RAM (wl/iw/wpa_cli/iperf, BSA restart flags,
  module reload args); persistent changes are NVRAM/backup IDs/scripts/FW/driver
  and remain out of scope.
