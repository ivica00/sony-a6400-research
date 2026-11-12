# E0404 — B1b read-only inspection: Mass Storage gadgetcore gate blocks the MS OS 2.0 WinUSB path (B2/B3 not started)

Date: 2026-11-12. Read-only physical inspection in Mass Storage only. No kernel
write, no descriptor change, no module file outside `/tmp_bt`, no PC Remote, no
UVC/`VS_PROBE`/`ffmpeg` change, no reboot, no battery pull.

The B1b pre-flight answered the two open questions — and the answer is that the
approved B2/B3 plan cannot bind WinUSB in Mass Storage: the gadgetcore Microsoft
OS descriptor mode gate is **0** in this mode, so Windows will not receive the
OS-string descriptor needed for the MS OS 2.0 query, regardless of the approved
18-byte `MSFT20` patch. B2/B3 were therefore not started.

## 1. Method (read-only)

`usb_gadgetcore_register_driver` loads the gadgetcore pointer from a fixed
kernel-data slot (literal at preserved-vmlinux VA `0x602b873c`, value
`0x6051b17c`). A second RAM-only helper module (same audited carrier, GPL
`.modinfo`, no writes at all) read that slot and the live tree through
`probe_kernel_read`, then unloaded:

- module: `artifacts/native/a6400-dbg-probe-e0404/final/a6400_dbg_probe.ko`
  23,888 B, SHA-256
  `dfc8bc03e35f097b3516c1a45dbf4956fd2b91612dd66e4f819678d3e4248672`,
  audited (ARM `ET_REL`, carrier vermagic, init/exit redirected, imports
  resolved); staged at `/tmp_bt/a6400_dbg_probe.ko`, `rmmod`ed and deleted.
- receipts: `artifacts/hardware/e0404-b1b-probe.json`,
  `artifacts/hardware/e0404-b1b-dmesg.txt`.

## 2. Observed live state (B1b answers)

```
A6400DBGPROBE gadgetcore=68aa4ec0
A6400DBGPROBE mode=0 max_speed=1 root=69567d20 read_error=0
A6400DBGPROBE device len=0 type=2 bcdUSB=0000 class=00 configs=1 config_ptr=65caa2c0
A6400DBGPROBE config value=1 interfaces=1 interface_ptr=65caa420 ...
A6400DBGPROBE iface0 number=0 alternates=1 alt_ptr=65c378e0
A6400DBGPROBE iface0 alt0 class=08 subclass=06 protocol=50 endpoints=2 ...
```

- **`gadgetcore+0x84 (MS OS mode gate) = 0`.** The stock kernel's `0xEE`
  string handler and the built-in `0x30/4` compat-ID handler both return
  `-ENODEV` when this byte is zero (E0402 §2.4). In Mass Storage the gate is
  zero, so the host never receives `MSFT100`/`MSFT20` and never asks for a
  Microsoft OS descriptor. The approved 18-byte `MSFT100 -> MSFT20` patch is
  necessary but not sufficient.
- The installed configuration is the expected single-interface Bulk-Only MSC
  topology: one interface, one alternate (`class 08 / subclass 06 / protocol
  50`), two bulk endpoints. A vendor interface appended as interface 1 is
  consistent with the tree, but this alone does not produce a driver binding.
- `max_speed = 1` matches the descriptor-install precondition.
- The native root table's device-entry field decode is **not yet correct**: the
  first 16-byte entry read as `len=0,type=2,bcdUSB=0x0000,class=0`, while the
  config pointer at `+8` and the config/interface records are plausible. The
  exact per-speed device-descriptor layout (and therefore `bcdUSB`) needs
  another decode pass or a Windows-side descriptor query; no bcdUSB conclusion
  is drawn here.

## 3. Why B2/B3 stopped

Binding WinUSB automatically needs Windows to query MS OS 2.0, which needs the
`0xEE` string to be served with `MSFT20`/vendor-code `0x02`. With `mode=0` the
stock handler refuses that request. The possible ways forward all exceed the
current approved write set and/or the prepared implementation:

1. **Set `gadgetcore+0x84` to a nonzero value** (a one-byte heap kernel-data
   write) with save/restore, analogous to B1c. This may also change gadgetcore's
   descriptor behaviour in Mass Storage and needs its own reversibility and
   enumeration-impact test.
2. **Hook the `0xEE`/compat handler** (kernel-text patch) to serve the OS string
   unconditionally. This is a text patch with a much larger blast radius.
3. **Bypass MS OS binding** and use a class driver with a built-in Windows INF
   (e.g., CDC-ACM serial) so no OS descriptor is needed. This still requires the
   EP0/endpoint/char-device stack and a different host transport, and it is a
   scope change from the requested WinUSB interface.

Additionally, B2 itself still requires the not-yet-written pieces listed in
E0403 §6: EP0 vendor request/response queueing (64-byte chunks first), the
`/dev/a6400_dbg` character device, descriptor injection, and the daemon chunk
bridge. Only the B1c 18-byte patch primitive is hardware-proven so far.

## 4. Reversibility / cleanliness receipts

- Probe module loaded only from `/tmp_bt`, `rmmod` completed
  (`A6400DBGPROBE unloaded`), `/proc/modules` no longer lists it, file deleted.
- No kernel write of any kind was performed by the probe (read-only path); the
  18-byte OS string remains the stock `MSFT100` descriptor (B1c restore already
  verified).
- Camera stayed in Mass Storage, uptime continuous (4,742 s → 4,778 s), daemon
  pid 1056 answers `ping`/`dmesg`/`dump-ring`, no reboot or battery pull.

## 5. Decision required before B2

To continue the WinUSB route, one of these must be authorised:

- **A.** Bounded save/restore write of the one-byte `gadgetcore+0x84` mode gate
  (plus the already-approved 18-byte OS-string patch and a descriptor-tree
  `bcdUSB`/device-field correction once decoded), then B2 with control-only
  EP0 transport; or
- **B.** An audited kernel-text hook of the OS-string/compat handler; or
- **C.** A different zero-INF transport class (CDC-ACM) that avoids MS OS
  descriptors entirely, accepting the scope change.

Until that decision, no vendor interface is exposed, no `/dev/a6400_dbg` node
exists, WinUSB has not been bound, and `camera_debugger.py --transport winusb`
still fails closed. PC Remote was not entered.

## 6. Commands

```
.\venv\Scripts\python.exe -m tools.research.build_debug_patch_module --audit-only --name a6400_dbg_probe --output-dir artifacts/native/a6400-dbg-probe-e0404
artifacts/hardware/e0404-b1b-probe.json
artifacts/hardware/e0404-b1b-dmesg.txt
```

Full suite: **1,371 tests OK** (no camera access in unit tests).
