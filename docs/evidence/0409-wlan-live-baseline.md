# E0409 — WLAN live baseline: BLOCKED. Camera reboots when Wi‑Fi is enabled (stock WLAN-loader error-path null write after mmcio mount failure)

Date: 2026-11-12. Read-only observation and offline disassembly only. **No camera
writes, no flash/Backup writes, no `wl band a`/TX override, no direct OSAL
`0x1000` injection in this step.** Wi‑Fi was attempted by the owner through the
camera's own menu; it crashed/rebooted the camera. The live baseline was
therefore **not collected**. Receipts: `artifacts/hardware/e0409-wlan-baseline/`.

## 1. What was attempted

* Owner charged the battery (was ~1 % during E0408), disconnected USB, and
  started Wi‑Fi through the camera's own menu (*Send to Smartphone* /
  *Ctrl with Smartphone*). Result: **the camera reboots every time Wi‑Fi is
  enabled.**
* The owner also clarified that the a6400's Wi‑Fi is **AP-only** (the camera
  does not join an external Wi‑Fi network).
* Parallel history: E0408's direct OSAL start injection also produced a
  `WlanResource_Ma` fault and reboot.

Both the E0408 injected attempt and the owner's stock-menu attempt produce the
**same crash signature**.

## 2. Crash signature (read-only, warm-boot ring)

`dump-ring` after the latest reboot (`artifacts/hardware/e0409-wlan-baseline/
ring-current.txt`, 46,486 bytes, boot_count=1) contains the exception record:

```
[call stack]
function entry : 0x083e7939 [ factor : 0x083e7a2e ] -- _Z27loadWlanHostDrivers_bcm4339bh
                              @ /usr/lib/libWlanResource.so : 0x6a2e
<- function entry 0x040118c9 [ caller : 0x040118ed ] -- u_osal_free_msg
                              @ /usr/lib/libosal_uipc.so : 0x28ed

[modules]  ... wlanIrq, compat, cfg80211, mmc_core, wlanMemoryAllocator ... 
           (no mmcioWrapper in the runtime module list)
[system maps] ... 040d7000-040d9000 r-- 0x00000000 mmcioWrapper.ko ...
[current task] program: im.elf(WlanResource_Ma) (pid: 347, cpu:3, tid:-1)
address: 00000000, trap_no: 0000000e, error_code: 0x817
[Exception Syndrome] page translation fault (0x817) at 0x00000000
[    0.764040] WARMBOOT
```

The same record in E0408 had `pc=0x083E7A2E`, `lr=0x040118ED` and the same
`WlanResource_Ma` page translation fault at `0x0`.

## 3. Decoded fault site (offline disassembly, libWlanResource.so)

Faulting instruction at `libWlanResource.so+0x6A2E` (`loadWlanHostDrivers_bcm4339`):

```
000069f0  blx insmod(path, args)
000069f4  cbz r0, 0x6a32        ; success -> next module
...
00006a06  ldr r4, [r7, #0x80]  ; allocated error message pointer
00006a10  strb r0, [r4, #2]
00006a12  mov r0, r5
00006a14  strh r3, [r4]
00006a16  str  r5, [r4, #-4]
00006a1a  blx osal_snd_sync_msg
00006a1e  ldr  r1, [r7, #0x80]
00006a22  ldrb r4, [r4, #2]    ; r4 = 0
00006a24  cbz  r1, 0x6a2c
00006a26  blx  osal_free_msg
00006a2c  cbnz r4, 0x6a3e      ; r4 == 0 -> fall through
00006a2e  strb r4, [r4]        ; store 0 to address 0 -> page translation fault
```

This path is reached **only when a module `insmod` fails** (`r0 != 0`); the
failure-reporting path then writes a zero byte to NULL. That is a **stock
firmware bug** in the WLAN loader error handling, independent of the emulator
and independent of the E0408 injection method.

Which module failed can be inferred from the same crash dump: the runtime
module list contains `wlanIrq`, `compat`, `cfg80211`, `mmc_core` and
`wlanMemoryAllocator`, but **not `mmcioWrapper`**, while `mmcioWrapper.ko` is
mapped into the process (the failed `insmod` file image). E0408's ring had the
explicit kernel messages from the same load stage:

```
Compat-wireless backport release: compat-wireless-v3.5.4-1-brcm
... mmc_hwip_system_off START / END ...
mmcio_mount failed!
wlanMemoryAllocator: Allocated Memory Returned. block = 0 (...) for mmcioWrapper
mmcio_wrapper_init failed!
usbg_ext_cmn.c(586): [E]OtherErr [-512]  (x5)
```

So the chain is: **SDIO/MMC WLAN bring-up fails (`mmcio_mount` /
`mmcio_wrapper_init`) → `insmod(mmcioWrapper.ko)` returns an error → the WLAN
loader's error path null-writes and crashes `WlanResource_Ma` → the camera's
exception monitor warm-reboots the system.**

## 4. Why the baseline is blocked, and what it means

* Wi‑Fi never becomes active; there is no `wlan0`, no `bcmdhd`, no
  `cfg80211` in the stable post-reboot state (only `wlanMemoryAllocator`).
  Therefore none of the requested live values could be read:
  no `/sys/module/bcmdhd/parameters/*`, no `wl`/`iw` output, no SDIO clock
  lines, and no `iperf` run.
* The repeatable reboot is not explained by the earlier 1 % battery alone:
  the owner reports the battery is charged now, and the reboot still occurs
  from the **stock camera menu**. The crash is in the camera's WLAN loader
  error path; the underlying failure is the SDIO/`mmcio` bring-up of the
  WLAN module. This points at the WLAN module/SDIO power or bus (hardware) or
  at a persistent WLAN initialization fault, not at the emulator work and not
  at the E0408 injection path.
* The camera is AP-only, so even a working Wi‑Fi baseline would be: camera
  creates its own AP, host joins that AP, host runs `iperf -s`, camera runs
  `iperf -c` (via the debugger shell). The host does have a Wi‑Fi adapter
  (Intel AX200), so that part is feasible later.

Battery voltage was not readable through `/sys/class/power_supply` (the
interface is absent on this firmware), so the “charged” state is owner-reported
only; a failing battery under load remains a possible secondary contributor to
the `mmcio`/power failure and is worth checking independently.

## 5. Camera disposition after the failed attempts

* Reconnected USB; camera is in Mass Storage, debugger reachable
  (`A6400_USB_DEBUG_V1`, `usb_extcmd`, UDC `dwc3.0` configured/high-speed),
  `modules.custom=none`, uptime advancing (~196 s at check time).
* Wi‑Fi off: only `wlanMemoryAllocator` loaded; no `wlan0`; no `bcmdhd`.
* No flash/Backup writes, no camera files written, no persistent modules.
* Current-boot dmesg is the normal warm-boot resume log (only the eMMC
  version warning); the crash record is in the warm-boot ring, preserved as
  the receipt.

## 6. Next steps

1. **Do not keep toggling Wi‑Fi** — every attempt crashes and reboots the
   camera through the stock error-path bug.
2. Hardware/service-level diagnosis is the correct next action: WLAN module
   (BCM4339) seating/power rail, SDIO host/controller, and a known-good
   battery under load. The repeated `mmcio_mount failed` is the place to
   start; a Sony service check is warranted if it persists with a known-good
   battery.
3. If Wi‑Fi is repaired (or can be made to start), rerun the read-only recipe
   from E0408 §4 with the camera in AP mode: read the four `bcmdhd` sysfs
   parameters, `wl status/bands/chanlist/chanspec/pm/mpc/lpc`, `iw phy`,
   `iw dev wlan0 get power_save`, `/proc/interrupts`, and dmesg SDIO lines;
   then join the camera AP from the host and run one brief `iperf` baseline.
   Note that USB-debugger availability while the camera is in AP mode still
   needs to be verified (USB data may not coexist with Wi‑Fi; if it does not,
   a separate authorized on-camera read path would be needed).
4. Retain E0408's static CLM result: the a6400 normal firmware CLM already
   declares the 5 GHz channel ranges; the live band/regulatory exposure
   question stays open until a working live WLAN baseline exists.

## 7. Bottom line

The requested live baseline could not be taken: with a charged battery and the
camera's own menu, Wi‑Fi bring-up still fails at `mmcio_mount` and the stock
WLAN-loader error path (`libWlanResource.so+0x6A2E`, `strb r4,[r4]` with
`r4=0`) crashes `WlanResource_Ma` and reboots the camera. No `wl`/`iw`/sysfs/
`iperf` data is claimed. The next useful move is hardware/service diagnosis of
the WLAN SDIO/module power path (plus a known-good battery check), not
additional software activation.
