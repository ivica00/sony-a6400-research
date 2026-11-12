# E0411 — P4 preload isolation + single P3 stock-Wi-Fi check: preload interference ruled out, SDIO fault confirmed

Date: 2026-11-12. Strictly reversible procedure: one `/setting` file rename,
one cold boot, **one** stock-menu Wi-Fi attempt, restore. No deletion, no other
writes, no further Wi-Fi attempts afterwards. Receipts:
`artifacts/hardware/e0411-p4-isolation/`.

## 1. P4 scope decision (and why it is not both preloads)

E0410 named the two `/etc/ld.so.preload` payloads:
`/setting/touch_native_guarded_v1.so` and `/setting/usb_debug_launcher.so`.

Offline inspection of both preserved libraries showed:

* `usb_debug_launcher.so` (6,284 B) is only a launcher: constructor forks/setsid
  and execs `/setting/run_once.sh` → `/setting/a6400_usb_debugd.elf`
  (strings: `/setting/run_once.sh`, `a6400_usb_debugd.elf`, `PATH=…`).
* `a6400_usb_debugd.elf` opens only `/dev/usb/usb_extcmd`, writes
  `/setting/a6400_usb_debugd.log` / `/tmp_bt/a6400_usb_debugd.lock`, and uses
  `ptrace`/`read`/`write`/`process` inspection. It has **no** `/dev/gpio`,
  `/dev/mmc*`, `/dev/mem`, WLAN, or Backup imports/strings.
* `touch_native_guarded_v1.so` (11,052 B) is the **only preload that hooks
  im.elf**: it patches `InputService::setTpEventSw` and
  `PAS_MenuSelectMode::setTouchable` via ptrace (`BYTES_VERIFIED: two native
  touch gates patched`). It has no WLAN/hardware access either.

`usb_debug_launcher.so` must stay enabled: it starts the USB debug daemon, and
disabling it removes the only command channel (no ring dump, no remote rename
back, no restore). A full both-preloads test would therefore strand the camera
in the test state. P4 was executed as **P4a: disable the only hooking preload
(touch), keep the launcher for recovery**. This is sufficient to test the
"preload interference inside im.elf" hypothesis, because the launcher does no
app hooking and no hardware access.

## 2. P4a rename receipts (exact listings + hashes)

Before:

```
---x------ 0 0 11052 Jan 1 1980 /setting/touch_native_guarded_v1.so
---x------ 0 0  6284 Jan 1 1980 /setting/usb_debug_launcher.so
/etc/ld.so.preload:
/setting/touch_native_guarded_v1.so
/setting/usb_debug_launcher.so
```

Executed read/write command (single `mv`, reversible):

```
mv /setting/touch_native_guarded_v1.so /setting/touch_native_guarded_v1.so.disabled
```

After rename (verified):

```
---x------ 0 0 11052 Jan 1 1980 /setting/touch_native_guarded_v1.so.disabled
---x------ 0 0  6284 Jan 1 1980 /setting/usb_debug_launcher.so
```

* Renamed file SHA-256: `52b90bc7bed66cf30e97d184ed335256153145e2d9bb268afb4a7a5510d08929`
  (11,052 B; identical content, name only).
* Kept launcher SHA-256: `a6f368cc3ce4efc00c1b4f094271a0b99aebba9a7940492c60dd7c50033fa5e4`
  (6,284 B).
* `/etc/ld.so.preload` unchanged (expected loader warning:
  `object '/setting/touch_native_guarded_v1.so' … cannot be preloaded: ignored`).
* Receipt: `artifacts/hardware/e0411-p4-isolation/p4a-rename-receipt.json`.

## 3. P3 — single cold-boot stock-menu Wi-Fi attempt

Owner procedure: disconnect USB, battery out ~30 s, reinsert, boot with no SD
card, wait for the normal screen, activate Wi-Fi **once** via *Send to
Smartphone*, then reconnect USB in Mass Storage.

Result: **failed — the camera warm-rebooted on the single attempt.**

Test-validity checks on the post-reboot camera (read-only):

* `grep touch_native /proc/149/maps` during the test boot: **no match** → the
  touch preload was genuinely absent from im.elf.
* USB debug daemon alive (`a6400_usb_debug` PID 700) → the launcher/daemon was
  the only preload active, as intended.
* Camera back in Mass Storage, uptime reset, WLAN off (only
  `wlanMemoryAllocator`; no `wlan0`).

Warm-boot ring (`ring-p3.txt`, 60,185 B, boots=2) shows the **exact same**
signature as E0410:

```
41.398 [HW_WRAPPER] UHS2 FuncTable is NULL!! USH2 unsupported Controller
41.399 [SD] isUSH2 = 0
41.440 mmc_hwip_system_off START
41.740 err 0x0
41.740 mmc_hwip_system_off END
41.740 mmcio_mount failed!
41.741 mmcio_wrapper_init failed!
...
[current task] program: im.elf(WlanResource_Ma) (pid 347, cpu:3)
page translation fault (0x817) at 0x00000000
Entering exception monitor -> WARMBOOT
```

Excerpt: `p3-ring-excerpt.log`; dmesg: `dmesg-p3.txt`; result receipt:
`p3-result.json`.

## 4. Restore (verified)

```
mv /setting/touch_native_guarded_v1.so.disabled /setting/touch_native_guarded_v1.so
```

Post-restore:

* `/setting/touch_native_guarded_v1.so` present, 11,052 B,
  SHA-256 `52b90bc7bed66cf30e97d184ed335256153145e2d9bb268afb4a7a5510d08929`
  — identical to the pre-P4 file.
* No `.disabled` file remains.
* `/etc/ld.so.preload` unchanged: the two original payload paths.
* Camera remains in Mass Storage, debugger reachable, no WLAN modules loaded.

## 5. Conclusion (definitive for the preload question)

**Preload interference is ruled out.** With the only im.elf-hooking preload
absent, the camera still fails at exactly the same point: UHS2/controller
probe, `mmc_hwip_system_off`, `mmcio_mount failed!`, then the stock
`libWlanResource+0x6A2E` null-write crash and warm reboot. The E0410 read-only
audit already showed the WLAN/power/GPIO Backup IDs and stock WLAN files are
unchanged; together this confirms the fault is on the **BCM4339 SDIO/reset/
power-rail path** (host power-on succeeds, card never answers), not in
`/setting`, not in our debugger payloads, and not in the WLAN loader logic
itself (the loader's null-write only turns the SDIO failure into a reboot).

Residual note: the launcher/daemon preload was not removed (recovery channel);
it has no hardware access (see §1), so it cannot influence SDIO enumeration.
A future both-disabled test would need an independent restore route for
`/setting` before it is attempted.

## 6. Next step

No more Wi-Fi attempts. Proceed with hardware/service diagnosis of the WLAN
SDIO path (module seating/power rail/reset line, known-good battery already
tested; Bluetooth pairs cleanly, so the combo chip's main rail is alive).
