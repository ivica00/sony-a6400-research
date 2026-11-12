# E0406 — BCM4339 Wi-Fi/Bluetooth capability and tuning surface (read-only static analysis)

Date: 2026-11-12. **Offline static analysis only.** No camera I/O, no module load,
no radio transmit, no write to camera/firmware/SD/partition. Inputs are the
already-extracted a6400 firmware images plus the ZV-E10 2.03 reference image.
Everything below is string/symbol/table evidence from those images; live runtime
defaults are *not* claimed (see §5).

## 0. Verified inputs

Paths relative to `firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/` unless noted.

| File | Size | SHA-256 (first 16) |
| --- | ---: | --- |
| `wlan/bcm/bcm4339.bin` (normal FW) | 558,561 | `6b720704c8fc3914…` |
| `wlan/bcm/bcm4339_mfg.bin` (manufacturing FW) | 549,271 | `1a9356667894c5cd…` |
| `kmod/bcmdhd.ko` | 492,512 | `6ba8c852e9eccaa6…` |
| `kmod/cfg80211.ko` / `mac80211.ko` / `compat.ko` | 197,856 / 283,840 / 8,248 | — |
| `kmod/mmcioWrapper.ko` / `wlanIrq.ko` / `wlanMemoryAllocator.ko` | 6,760 / 3,788 / 7,080 | — |
| `bin/bsa_server` | 4,802,499 | `dac46418c82ed0e6…` |
| `bin/bt_firm.hcd` / `bt_firm_sar.hcd` | 58,748 / 54,028 | — |
| `bin/wpa_supplicant` | 758,180 | `91236ba7b42335f0…` |
| `bin/wl` / `bin/dhd` / `bin/iperf` / `bin/Wltestcmd` / `bin/btRFTest.elf` | 1,152,221 / 238,100 / 62,462 / 22,127 / 36,192 | — |
| `lib/iw.so` | 95,264 | `ab7364cac7c74dd0…` |
| `lib/libWlanResource.so` / `libWlanAdjust.so` / `libWlanControlCommon.so` | 35,248 / 55,984 / 14,792 | — |
| `lib/libNetService.so` | 682,040 | `1557bfa2c3e205e3…` |
| `lib/libInfraBluetoothCore.so` / `lib/libInfraBluetoothLowEnergy.so` / `lib/libBTAdjust.so` | 144,292 / 237,084 / 10,984 | — |
| `bin/startBTCore.sh` | 1,283 | `33c82447cdbcdbd2…` |
| ZV-E10 `wlan/bcm/bcm4339.bin` / `kmod/bcmdhd.ko` (reference) | 564,167 / 522,740 | `cbb464370e3a9547…` / `bb3522abe11ec8cd…` |

All modules carry vermagic `3.0.27_nl-rt106+ SMP preempt mod_unload ARMv7` on
both a6400 and ZV-E10, i.e. same kernel ABI in the reference image.

## 1. What the module can do (static evidence)

* FW banner a6400: `4339a0-roml/sdio-ag-pool-p2p-pno-pktfilter-keepalive-aoe-sr-mchan-proptxstatus-lpc-autoabn-mfp-txbf-ipa-ecal-txpwr-ltxwat-clm_43xx_sony_DI-sndi Version: 6.37.39.81 (r666296 CY) CRC: 2c4bc2ba Date: Thu 2017-08-10 02:24:09 CDT Ucode Ver: 918.2006 FWID 01-ca76f58c`.
* NVRAM header: *“Sample variables file for BCM94339 WLIPA board (WLBGA module with eTR, iPA and iLNA-2G/eLNA-5G)”* — the module has a **5 GHz front end**.
* NVRAM contains 5 GHz calibration and 40/80/160 MHz power tables (`pa5ga0`,
  `pa5gbw40a0`, `pa5gbw80a0`, `mcsbw805glpo`, `mcsbw1605glpo`, `swctrlmap_5g`,
  `aa5g=1`) and 2.4/5 GHz low-power flags (`lowpowerrange2g/5g`).
* Chains are configured `rxchain=1`, `txchain=1` → **1×1 module**. Public
  BCM4339 data describes a 2×2 11ac combo part, so this module purposely uses
  one chain; nominal ceiling (inference from tables + standard 802.11n/ac
  rates): 2.4 GHz HT40 1SS ≈ 150 Mbit/s PHY; 5 GHz 11ac 80 MHz 1SS ≈
  433 Mbit/s PHY.
* SDIO is the host bus: driver SDIO IDs are Broadcom vendor `0x02D0`
  (`sdio:c*v02D0dA8E7*`, `…d4324*`, `…d4334*` aliases), `mmcioWrapper.ko`
  registers the SDIO/mmc glue, `wlanIrq.ko` requests a GPIO IRQ.
* Bluetooth is the same combo chip: BSA stack + `bt_firm.hcd` over
  `/dev/ttyBT`; `libInfraBTCore.so` contains `CBTWoLE::bcm4339_hci_send_cmd`,
  BLE hibernate VSCs and BT sleep-mode configuration.

a6400 reference vs ZV-E10 2.03 reference, same chip, **different FW**:
ZV-E10 has `…clm_43xx_sony_DI-sndi-toe Version: 6.37.39.113 (r722271 CY) …
Ucode Ver: 918.2015` (2020-03-16) and a larger `bcmdhd.ko`
(522,740 vs 492,512 B). `toe` (TCP offload engine) is absent from the a6400
build.

## 2. Control surface present in the image (verified strings/tools)

### 2.1 Driver-level

`bcmdhd.ko` declares only two module params in `.modinfo`
(`dhd_irq` — “DHD oob gpio number”, and `clockoverride` — “SDIO card clock
override”). The same binary references the wider legacy-dhd parameter/iovar
set: `firmware_path`, `nvram_path`, `iface_name`, `dhd_msg_level`,
`dhd_slpauto`, `dhd_watchdog_ms`, `dhd_poll`, `dhd_idletime`, `dhd_intr`,
`dhd_rxbound`/`dhd_txbound`, `dhd_sdiod_drive_strength`, `sd_blockmode`,
`sd_blocksize`, `sd_dma`, `bus:txglom`/`bus:rxglom`, `txglomsize`,
`dhd_arp_enable`, `dhd_pkt_filter_enable`, `btc_params` (incl. the
save/override lists for SCO/eSCO coexistence parameters [50,51,64,65,71]),
`mpc`, `wowl`, `keepalive`.

a6400 ships only the two power-mode NVRAM sets `high/` and `low/` (15 files
each, `regrev` 75–89); the ZV-E10 reference ships three explicit
`2_4GHz_high_5GHz_high/`, `2_4GHz_low_5GHz_high/`, `2_4GHz_low_5GHz_low/` sets
(27 files each) — band/power selection is image-dependent.

`libWlanResource.so` builds the insmod argument from literal templates:
`firmware_path=/usr/wlan/bcm/bcm4339.bin nvram_path=/usr/share/network/nvram/{high|low}/bcm4339_{H|L}_%02d.txt`
(plus `_mfg` and `/mnt/…` override variants). The 15 H files are `regrev`
75–89 and the 15 L files are the same `regrev` 75–89 (all `ccode=XR`): the
`%02d` index selects a **regulatory revision**, not a power step. The H/L
directory selects TX-power mode (H: `maxp2ga0=74`, `maxp5ga0=58,…`,
`high_2g_power_mode=1`; L: `maxp2ga0=34`, `maxp5ga0=26,…`,
`lowpowerrange2g/5g=1`, `high_2g_power_mode=0`; units not decoded here — do not
read as dBm without verification).

The `wifi-scripts/` directory is **legacy/stale relative to the shipped
product path** (`load_firm.sh` references `/usr/backport/…brcmfmac.ko`,
`start_dhd.sh`/`wifi-test.sh` reference `bcmdhd-oob.ko`, `gpio-test.ko`,
`InitWlanISR.elf` that are not in the image). Current path is the app libraries
below; the scripts remain useful only as historical intent.

### 2.2 Factory / service tools (shipped on the camera)

* `wl` (Broadcom CLI) — contains iovars/commands for `mpc`, `lpc`, `pm`,
  `txpwr`, `chanspec`, `ampdu`, `wme_apsd`, `wowl`, `keepalive`, `arp`,
  `pkt_filter`, `rateset`, `interference`, `obss`, `coex`, `btc_params`,
  `txstreams`/`rxstreams`, `stbc`, `sgi`, `country`, `scan`, `assoc`, `status`.
* `dhd` — driver debug/console/coredump/statistics front end.
* `iw` / `lib/iw.so` — nl80211 client incl. `set_power_save`/`get_power_save`;
  `libWlanResource.so` links `iw.so`.
* `iperf` 2.0.5 — throughput tester is built into the image.
* `Wltestcmd` — factory WLAN RF test: `StartTest <wait> <power mode>`
  (`0=STD, 1=HI`), `TX/TX_Packet/TX CW/RX`, `index 0..65`, **`channel 1..165`**,
  and shell-level `wl -i wlan0 …` calls (`mpc 0`, `phy_watchdog 0`,
  `country ALL`, `phy_txpwrctrl 1`, `txpwr1`, `band a`, `5g_rate -v -s 1 -b`,
  `chanspec`, `pkteng_start/stop`). This is direct evidence that the FW/PHY
  path can transmit on 5 GHz channels in factory test mode.
* `btRFTest.elf` — BT RF test: `ExecuteLETransmitterTest`, `ExecuteLEReceiverTest`,
  `StopLETest`, HCI commands, `enable_lpm`, `hci_write_sleep_mode`,
  `use_baudrate_for_download`, `baud_rates`.
* `bsa_server` — Broadcom BSA host stack; flags include `-lpm` (enable low power
  mode), `-ssbi` (enable suspend at startup), `-r <baud code>` (14 = 3,000,000
  baud), `-k <BLE local key file>`, `-p <patchram>`, `-all=<trace level>`.
* `wpa_supplicant` **v2.1-devel** (2013) with full nl80211 + P2P build;
  `wpa_cli`; P2P operating class in product config is 2.4 GHz only
  (`p2p_oper_reg_class=81` in `lib/netconf/p2p.conf`).

### 2.3 Application service APIs (symbol level, libs shipped in `/usr/lib`)

* `libNetService.so`: `NsMiscEnableWifiPowerSave`,
  `NsMiscSetWiFiPowerMode`/`NsMiscGetWiFiPowerMode`(`…FromBackup`),
  `NsApiSetMaxPerformanceMode`, `NsMiscDisableWifiAmpdu`,
  `NsMiscSetGOBand`/`NsMiscGetGOBand`/`NsMiscGetGOFreqFromBackup`/
  `NsMiscUpdateGOChBackup`/`NsMiscIsSupportChannel`/`NsMiscRandomSelectFreq`,
  `NsMiscExeCommand` (popen), `wlanWatcher_*`.
* `libWlanResource.so`: `GetWifiPowerMode`/`SetWifiPowerMode`,
  `GetPowerMode`/`SetPowerMode`, `GetWifiType`/`SetWifiType`,
  `GetWifiCh`/`SetWifiCh`, `GetTestMode`/`SetTestMode`,
  `WlanResourceSetMaxPerformanceMode`, `wlanResource_sus/res`,
  `wifiPowerOn`, `startWlan`/`stopWlan`, BMI firmware loader.
* `libWlanAdjust.so`: factory TX-adjust surface — set/get TX rate, mode,
  channel, power, pattern, GI, packet size, packet gap, channel range,
  start/stop TX, ping, RSSI, SSID/PSK and backup-backed factory credentials.
* `libObj.so`: `ActionSetWifiPowerMode` string (a UI action exists somewhere in
  the state machine; reachability unknown).
* `libJiritsu.so` (service/self-test mode helper): WLAN test command IDs
  (`WLAN_TEST`, `WLAN_SET_TX_*`, `WLAN_SET_CH_RANGE`, …) and
  `SET_ADB_ENABLE`.
* No user-facing menu item exists for Wi-Fi power save / band / HT40: the UI
  string table’s `Power Save` is the camera auto-power-off setting
  (`string_english.uxc`), not a radio setting.
* Static call sites for `NsMiscEnableWifiPowerSave` and
  `NsApiSetMaxPerformanceMode` exist only in the defining library — whether
  a6400 code paths call them, and with what defaults, is **unverified**.

## 3. Levers by goal (evidence, expected effect, constraints)

| Goal | Lever | Evidence | Expected effect | Constraint |
| --- | --- | --- | --- | --- |
| Throughput | 5 GHz / 11ac | NVRAM 5G cal + 40/80/160 tables; `Wltestcmd` channels 1–165, `band a`, `5g_rate … -b`; `aa5g=1` | Up to 433 Mbit/s PHY (1SS 80 MHz) and much cleaner spectrum vs 2.4 GHz | Product config is 2.4 GHz (`p2p_oper_reg_class=81`); a6400 ships only the two power-mode dirs `high/`+`low/`, while the ZV-E10 reference ships three explicit `2_4GHz_high_5GHz_high` / `2_4GHz_low_5GHz_high` / `2_4GHz_low_5GHz_low` sets (27 files each) — band/power selection is image-dependent. Normal-mode CLM/regulatory permission unverified; enabling is a product/regulatory change, not a knob |
| Throughput | 40 MHz in 2.4 GHz / P2P GO HT40 | `cfg80211.ko` param `cfg80211_disable_40mhz_24ghz`; 40 MHz NVRAM tables; `p2p_go_ht40` absent from `p2p.conf` (wpa_supplicant default 0) | Direct-connection (GO) PHY 72→150 Mbit/s if HT40 actually used | Congestion/regulatory risk; needs live confirmation of the operating channel width |
| Throughput | SDIO bus / IRQ path | `clockoverride` param; OOB IRQ (`dhd_irq`, `wlanIrq.ko`, IRQ 144 affinity in legacy scripts); `txglom`/`rxglom`, `sd_blockmode`/`blocksize`/`dma` | Possible bus headroom if clock/glom are not optimal | Default clock/bus width not resolved statically; SDIO may cap >150 Mbit/s 5 GHz use |
| Throughput | FW/driver offload | ZV-E10 reference FW adds `toe` + newer `bcmdhd`; a6400 host stack is kernel 3.0.27 + wpa_supplicant 2.1-devel | Lower CPU cost / better TCP throughput | Cross-model FW/driver substitution = flash write + unverified compatibility (same vermagic is necessary, not sufficient); high risk |
| Throughput | A-MPDU | Driver supports AMPDU; `NsMiscDisableWifiAmpdu` exists (so the app can turn it off) | Keep enabled; disabling would hurt | No win from disabling |
| Power | WLAN PS / offloads | `NsMiscEnableWifiPowerSave`; `wl pm`, `mpc`, `lpc`, `wowl`, `keepalive`, `arp`, `pkt_filter`; `dhd_slpauto`, `dhd_idletime`, `dhd_poll` | Idle battery improvement at latency cost | Runtime/state change; current defaults unknown; PS can reduce throughput latency |
| Power | TX power mode H↔L | `NsMiscSetWiFiPowerMode`; H `maxp2ga0=74`/`maxp5ga0=58` vs L `34`/`26` | Lower RF power consumption and SAR, less range/edge-rate | Product/region selection unknown; not a link-layer sleep feature |
| Power | BT host LPM / suspend | `startBTCore.sh` launches `bsa_server` without `-lpm`/`-ssbi` (same in ZV-E10); BSA supports both; BT core has `Set_Sleepmode_Param` + `BSA_BleWakeCfg/Enable` | Lower BT idle draw | Launch-flag change; wake/pairing timing risk |
| Power | BLE hibernate / WoLE | `LE_META_VSC_…LE_Hibernate_ON/OFF`, `startWoLE_observer/peripheral_observer`, `BSA_BleWake*` in `libInfraBluetoothCore.so` | Very low advertising/wake power (already implemented for BLE wake) | `libInfraBluetoothWoLEBoot.so` + `libWirelessPower.so` are referenced by `libIMDB.so` but **absent** from `/usr/lib` in this image → boot-time WoLE path partial/absent; needs verification |
| Power | Coexistence | dhd `coex`/`btc_params` (save/override lists), BSA `bta_dm_coex_cback`, `BTM_SetMwsTransportLayer` | Better concurrent BT+WLAN behaviour | Current tuning unknown; shared antenna means trade-offs, not free gains |
| BLE | Profiles already present | `DIPairingService`, `DILocationService`, `DIRemoteControlService`, `DICameraDeviceControlService` in `libInfraBluetoothLowEnergy.so`; BRCM adv-filter/IRK/RSSI VSCs | Pairing/location/RMT-P1BT remote are already covered | No user-facing tuning; interval/latency changes are profile-code changes |
| BLE | Startup config | `-k /tmp_bt/ble_local_keys`, `-all=0`; `-r 14` (3 Mbaud) only in the preloaded-FW branch; `bt_firm.hcd` vs `bt_firm_sar.hcd` (SAR variant) | 3 Mbaud UART avoids BT host transport as a bottleneck | Flag/config change; SAR FW is regulatory, not a performance knob |

## 4. Limits that no knob removes

* Module is 1×1 (`rxchain=1`, `txchain=1`), so 2×2 BCM4339 rates are not
  reachable.
* a6400 is a 2.4 GHz 802.11b/g/n product; the 5 GHz/11ac path is visible only
  through factory-test tooling and reference NVRAM tables.
* 2013-generation driver/FW, kernel 3.0.27 and wpa_supplicant 2.1-devel bound
  protocol/CPU efficiency.
* No UI surface for band/HT40/power-save; changes require runtime commands or
  firmware/config writes.
* Module authentication and boot-time verification (earlier project evidence)
  make driver/FW substitution non-trivial; nothing here should be attempted
  under the current read-only authorization.

## 5. What this analysis does **not** establish

* Actual runtime defaults: current Wi-Fi power-save state, SDIO clock/width,
  active NVRAM index/H-L mode, CLM band list, whether P2P GO uses HT20 or
  HT40, BT LPM state, coexistence values. These need a live camera with WLAN/BT
  enabled (a state change, not covered by the standing read-only allowance).
* Any measured throughput or current draw.
* That the 5 GHz/11ac path is available in normal (non-factory-test) mode.
* That any lever would survive or be safe on real hardware.

## 6. Bounded follow-ups

Read-only (offline, no camera):
1. Disassemble `get_bcmdhd_insmod_args` and `WlanResource` port init to recover
   the exact insmod argument string (does the product pass `dhd_irq`,
   `clockoverride`, WLAN_SDIO selection?).
2. Use REA on `bcmdhd.ko` to recover the default SDIO clock/idle parameters and
   the `clockoverride` unit.
3. Diff a6400 vs ZV-E10 `libWlanResource`/`libNetService` to see whether the
   newer model's band/power-save paths exist in a6400 code.

Requires explicit authorization (camera state change):
4. Enable WLAN in a bounded test window and capture `wl status`, `wl pm`,
   `wl mpc`, `wl chanlist`/`wl bands`, `iw phy`, `iw dev wlan0 get power_save`,
   `/proc/interrupts` for mmc0/irq, `dmesg` SDIO clock line; then `iperf`
   baseline before/after a PS toggle.
5. BLE: capture `bsa_server` local version (`-r`/read local version), test LPM
   on/off effect on wake/connect timing, and LE connection interval behaviour.
6. Coexistence: concurrent BLE + Wi-Fi throughput/latency baseline before any
   tuning.

## 7. Bottom line

The chip is more capable than the a6400 product exposes: the module carries a
5 GHz front end and 11ac 80/160 MHz calibration, the FW can drive 5 GHz channels
in factory test, and both the app libraries and the shipped `wl`/`iw`/`dhd`/BSA
tooling expose power-save, TX-power, AMPDU, GO-band, BLE-profile and BT-LPM
surfaces. None of that is user-facing, and **all real changes are writes or
runtime operations outside the current read-only scope**. Highest-value safe
next step is the offline disassembly in §6 items 1–3; the biggest potential
throughput gain (5 GHz) is gated by product/regulatory configuration and must
first be proven to be even reachable in normal mode.
