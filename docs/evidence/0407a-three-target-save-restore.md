# E0407a — Three-target RAM save/restore verified in Mass Storage (no re-enumeration)

Date: 2026-11-12. Physical work in Mass Storage only (`054C:0CA8`). RAM-only
module staged at `/tmp_bt`, loaded with `/sbin/insmod`, unloaded with
`/sbin/rmmod`, and deleted. No descriptor-tree change, no USB re-enumeration, no
PC Remote, no `/setting` write, no reboot, no battery pull.

## 1. Module and targets

Built on the verified E0403 carrier path (pinned `usbg_video.ko` carrier; its
code unreachable, `__this_module` init/exit redirected to the helper, GPL
license, import aliases audited). Module:
`artifacts/native/a6400-dbg-patch3-e0407a/final/a6400_dbg_patch3.ko`,
**24,904 bytes**, SHA-256
`9bd85e1956887a3e0dde85a980098f1e6b96128c25d162d06465ad2b36702e67`,
vermagic `3.0.27_nl-rt106+ SMP preempt mod_unload ARMv7`, static audit OK.

Three volatile targets, each pre-checked, saved and read-back verified:

1. `VA 0x604e5130`, 18 bytes: `MSFT100` + vendor code `0x30` →
   `MSFT20` + vendor code `0x02` (stock CRC `6e795789` → patched `fdadfcba`);
2. `gadgetcore+0x84`, 1 byte: MS OS mode gate `0` → `1`
   (`gc = *0x6051b17c`, live `0x68aa4ec0`);
3. runtime-selected per-speed record `+0x00`, 2 bytes: `bcdUSB 0x0200 → 0x0210`.
   Selection follows the decoded builder exactly: `gadget = *[gc]`,
   `speed = [gadget+0x20]`, `root = [gc+0x6c]`,
   `speed 5 → root+0x20, 3 → root+0x10, else root+0`. On this boot
   `speed = 3`, so the record was `root+0x10 = 0x69567d30`.

Any precheck failure aborts before writing; any patch failure restores the
already-patched targets in reverse. `rmmod` restores all three with read-back
verification (up to 3 attempts) and only then returns.

## 2. Hardware receipts (two cycles)

Receipt: `artifacts/hardware/e0407a-three-target.json` and
`artifacts/hardware/e0407a-dmesg.txt`.

```
A6400DBG3 PRECHECK_OK os_crc=6e795789 gc=68aa4ec0 mode=0 bcdusb_addr=69567d30 bcdusb=0200
A6400DBG3 PATCH_OK os_crc=fdadfcba mode=1 bcdusb=0210
A6400DBG3 RESTORE_OK os_crc=6e795789 os_ok=1 mode=0 mode_ok=1 bcdusb=0200 bcdusb_ok=1 attempts=1
```

Cycle 2's `PRECHECK_OK` (same gc, same `bcdusb_addr`, stock CRC/value) is
independent proof that cycle 1 restored all three targets; cycle 2 then
patched and restored them again with the same result. `/proc/modules` no longer
lists `a6400_dbg_patch3`; the `/tmp_bt` file was removed.

Post-test state: camera still Mass Storage, uptime continuous
(6,581 s → 6,599 s), daemon pid 1056 answers `ping`
(`PONG … pid=1056 transport=usb_extcmd`); no reboot or battery pull.

## 3. Reversibility compliance

- Module staged only from `/tmp_bt`; no `/setting`/persistent write, no
  auto-load hook.
- Only the three volatile RAM targets changed; all restored and verified before
  unload. A battery pull still yields a stock cold boot.
- No descriptor tree or root pointer was changed and no re-enumeration was
  triggered, exactly as scoped for E0407a.
- The mode byte was written only while no USB reconfiguration was active; the
  module restores it before returning, satisfying the E0405 guard rule.

## 4. Not done (next gates)

- **E0407b (offline):** native descriptor-tree deep-copy + zero-endpoint vendor
  interface 1 append + root swap + soft-connect/re-enumeration trigger; EP0
  vendor queue serving the 46-byte MS OS 2.0 set (`wIndex=7/8`) in ≤64-byte
  chunks; `/dev/a6400_dbg` cdev/file-ops bridge to the v2.1 daemon; static
  audit + Unicorn execution tests.
- **E0407c (hardware):** RAM-only enumeration check (WinUSB binds interface 1,
  Mass Storage stays functional), then unload and restore-verify all three
  targets again.

E0407b was **not started** in this increment; no descriptor or EP0 kernel code
was written. The three-target restore primitive it depends on is now physically
proven.
