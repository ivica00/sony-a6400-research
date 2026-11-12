# E0401 — USB Debugger v2: in-band dmesg/warm-ring readout, process-context recover, and the measured mode-switch boundary

Date: 2026-11-12. Physical work on the a6400 (MSC `054C:0CA8`, PC Remote
`054C:0CAA`), offline Unicorn work for the Phase 2 probe. No UVC descriptor,
`VS_PROBE` or `ffmpeg` change; no kernel-text write; no firmware/boot change.

This evidence supersedes E0400's design-only status for the parts listed in
§1–§6. It does **not** claim an always-on debugger in PC Remote, an in-band
mode switch from PC Remote, or a deployed runtime kernel hook: those remain
explicit boundaries in §7.

## 1. What was built

Protocol v2 keeps every v1 wire operation (`info`, `read`, `exec`, `mem`,
`ps`, `threads`, `stop`) and adds four camera-side operations, all in the same
fixed 4096-byte frame (`MAGIC 0x44343641`, feature `0x23`, opcode `0x7a`):

| Op | Name | Behaviour |
| --- | --- | --- |
| 8 | `usb_state` | bounded USB/module/klog/debugger receipt |
| 9 | `recover` | process-context removal of **allowlisted** authored modules (`delete_module`, `O_NONBLOCK`, 20 × 100 ms poll, never forced), post-state receipt; no arbitrary shell, no physical-memory write |
| 10 | `dmesg` | non-destructive kernel printk ring (`SYSLOG_ACTION_READ_ALL`, `__NR_syslog`) with snapshot-length verification |
| 11 | `ring_dump` | raw read of the cmdline-verified warm klog ring through `/dev/mem` **O_RDONLY**, 4064 bytes per request |
| 12 | `ring_info` | klog header validation, CRC32 over header+data, boot-segment count |

Host side: `tools/camera_debugger.py` gained `usb-state`, `dmesg`, `dump-ring`
and `recover [--to-msc]`, plus a chunked-readout discipline that rejects a
snapshot whose length changes between chunks. `src/a6400/usb_debug_ring.py`
parses/validates the ring; `tools/research/upgrade_usb_debugger.py` performs
the staged upgrade with a preserved rollback copy.

Build/audit: `tools/research/build_usb_debugger_v2.py` (static ELF audit) with
`tools/research/build_usb_debugger_v2.ps1` (raw WSL compile wrapper, needed in
this sandbox). The daemon now retries both the advisory lock and the feature
registration so a staged v2 can take over from a running v1 without ever
leaving the camera without a debugger.

Built daemon: **20,212 bytes**, SHA-256
`ae90244a271076d29aeb98d5986765f7f75bac99dc94805b21d685564ce68d86`,
`ET_EXEC`/`EM_ARM`, `DT_NEEDED libc.so.6`, 43 undefined symbols all resolved by
the pinned Sony libc, 28 defined symbols, no writable+executable `PT_LOAD`, no
`PT_TEXTREL`. Artifact + manifest: `artifacts/native/usb-debugger-e0401/`.

## 2. Verified memory map and warm-persistence mechanism (not guessed)

The running camera reports `/proc/cmdline`:

```
klog.addr=0x035a5000 klog.size=0x20000
...
mem=1G@0 memrsv=1M@0 memrsv=0x8000@0xF00000 memrsv=0x1A5E000@0x02E68000
memrsv=0xA6EB000@0x09915000 memrsv=704M@0x14000000:uc
mem=256M@0x80000000@1 memrsv=14M@0x80000000:uc memrsv=242M@0x80e00000:uc
```

and `/proc/iomem` shows `00000000-3fffffff System RAM`,
`80000000-8fffffff System RAM`, `Kernel text 00108000-0048d023`,
`Kernel data 004bc000-0051f613`. The daemon validates `klog.addr`+`klog.size`
against `/proc/iomem` System RAM before every read; a mismatch fails closed.

Header read live from physical `0x035a5000`, first 16 bytes:

```
6b6c6f67 62830000 00000000 5b202020 ...   => magic "klog", write_position 33634, wrap 0
```

The preserved a6400 `vmlinux.bin` (SHA-256
`12eeec829407595e28265f7d0db3b88c56f63a9f0fdd725c9c53c66a49643707`,
matching E0364) contains the keep/initialize logic. With image base
`0x60108000` (file offset + `0x60108000` = VA):

- function at file offset `0x72fe4` reads `[global+0xd4]` = buffer header
  `{magic, write_position, wrap}`, compares the header magic to the literal
  `0x676f6c6b` ("klog") by **bit distance** and takes the keep path when the
  distance is ≤ 2 and `write_position < capacity`;
- keep message string at file `0x348dd0`:
  `<6>klog: keep logging buffer: 0x%08lx@0x%08lx, magic wrong nbit: %d\n`
- initialize string at file `0x348e15`:
  `<6>klog: initialize logging buffer: ... nbit: %d(0x%08lx)`;
- the keep path repairs a 1–2 bit magic and does **not** reset
  `write_position`; the initialize path sets position/wrap to zero.

The live capture proves the appended-boot behaviour: the 33,693-byte ring body
contains two boots — boot A (`WARMBOOT`, "initialize logging buffer … nbit: 20",
logs through `2.83 s` MMCD mount) followed by boot B (`WARMBOOT`, "keep logging
buffer … nbit: 0", 5,545 bytes of log). That warm reboot was the historical
E0399/B22 reset, now readable after the fact; this is the requested
warm-reboot-safe log persistence, provided by the camera kernel, read only by
us. `dump-ring` verified it end-to-end against the daemon receipt
(CRC32 `0xa856c2bc`, capacity `0x20000`, 2 boot markers, magic distance 0).

## 3. Staged upgrade over USB (no service mode, no battery pull)

Receipt: `artifacts/hardware/e0401-debugger-upgrade/`. The old installed daemon
(11,384 bytes, SHA-256 `c5bb9c14…`) was preserved from `/setting`, the v2 binary
was pushed to `/tmp_bt` with read-back verification, started while v1 still held
the lock/registration, confirmed alive by `/proc/<pid>/cmdline`, and only then
was v1's `stop` sent. v1 unregistered (`debug unregister result=0`), v2
registered as pid 859. The `stop` read reported MSC sense `0x9 0x81 0x83`
because v1 unregistered during the reply transfer; this is a benign
consequence, confirmed by the daemon log and by v2 answering immediately after.

Persistence: v2 was then written to `/setting/a6400_usb_debugd.elf`
(read-back byte-equal, SHA `ae90244a…`), which the existing preload launcher
executes at boot. No Senser/updater mode was entered.

## 4. Hardware verification in Mass Storage

All receipts under `artifacts/hardware/e0401-debugger-v2/`:

- `info`: `A6400_USB_DEBUG_V1 / protocol=2 / pid=859 / uid=0`.
- `usb-state`: `udc=dwc3.0 state=configured speed=high-speed`,
  `modules.custom=none`, `nodes=…/usb_extcmd:present,…`,
  `klog.addr=0x035a5000 size=0x20000 position=33693 crc32=0xa856c2bc
  warmboot_markers=2`, `dmesg.bytes=5545`.
- `dmesg`: complete 5,545-byte kernel printk ring read over USB
  (`dmesg-over-usb.txt`), no SD card access.
- `dump-ring`: 33,693-byte warm ring, capacity 131,072, CRC32 verified against
  the daemon receipt (`klog-ring.bin`, `klog-ring.json`).
- `recover` (no mode change): `result=clean`, `custom_modules_absent=yes`,
  `stock_descriptors=already_stock`, `elapsed_ms=13`; camera responsive after.
- Camera uptime 1,344 s → 2,128 s across the session with no reboot.

## 5. Mode-switch measurement (MSC → PC Remote → MSC, zero battery pulls)

The user switched the camera to PC Remote via the camera menu and back via the
camera menu; the cable was never unplugged and the battery was never removed.

Observed in PC Remote (`pcremote-ops.json`, `pcremote-probe.json`):

- Windows enumerates Sony PTP `VID_054C&PID_0CAA` (`0x054c:0x0caa`),
  manufacturer `Sony Corporation`, `vendorExtension='Sony PTP Extensions'`.
- Advertised operations are exactly `0x1001-0x100A, 0x101B, 0x9201, 0x9202,
  0x9205, 0x9207, 0x9209`. **SonyDiExtCmd `0x9280/0x9281` and
  `SonyReqReconnect 0x9282` are absent**, so PMCA correctly does not classify
  the device as an MTP ext-command camera.
- The debugger frame over `0x9280/0x9281` is refused (WPD
  `MTP SendCommand failed: 0x8007001F`); `0x9282 [0]` is refused
  (`0x800700AA`). These WPD calls use the MTP-extension command path, so this is
  the camera/transport refusing the operation, not a host operation-list filter.

After returning to Mass Storage, v2 answered immediately with the **same pid
859**, the same klog ring (`write_position=33693`, CRC `0xa856c2bc`) and a
5,545-byte dmesg whose new tail line is `[ 2095.657116] usbg_ext_data.c(847):
[E]err=[-125]` from the mode transition. The debugger therefore survives a full
MSC→PC Remote→MSC round trip with zero battery pulls; it is simply **not
reachable while the stock PC Remote gadget is active** because that mode's PTP
server exposes no ext-command channel.

### 5.1 MTP mode was attempted but not confirmed

The camera also has an "MTP" USB setting, which would matter because MTP does
advertise the Sony ext-command operations. It was requested twice; each
transport-recorded attempt enumerated `SonyMscExtCmdDevice` (Mass Storage) by
the time the debugger connected, and the daemon still answered as pid 859
(`mtp-mode-observation.json`). An earlier `info` issued while the camera was
reported to be in MTP also answered pid 859, but it did not record the transport
type, so it is **not** counted as an MTP-reachability proof. Observed behaviour:
the camera re-enumerates as Mass Storage when no MTP session is held, so the
MTP window closes between separate host commands. `recover --to-msc` is
implemented to send `SonyReqReconnect 0x9282` on the same open MTP session
(`recover-inband-from-mtp.json` path), but it has only run in the
already-Mass-Storage case (`in_band_switch=already_mass_storage`,
`result=msc_recovered`). A live MTP→MSC switch is not yet observed.

## 6. Phase 2 offline: audited runtime ARM probe proven in Unicorn

Because the Phase 1 mode-switch requirement did not pass (see §7), the
execution rules forbid a hardware kernel-text write. The offline half was still
delivered as required:

- `tools/native_camera/hook/a6400_debug_hook_stub.S` — real ARMv7 trampoline:
  saves r0–r12/lr/cpsr, appends one 96-byte record (magic `A64H`, sequence,
  tick counter, r0–r12/sp/lr/cpsr, one configured pointer dereference), wraps a
  fixed-size ring, restores interrupted flags/registers, executes the saved
  instruction, continues at `target+4`.
- `tools/research/build_arm_hook_stub.py` — assembles/validates the object
  (no relocations; absolute addresses are literal slots filled by the
  installer) and generates `src/a6400/debug/arm_hook_stub.py`:
  288 bytes, SHA-256 `92923e8fefdacfcd9609ceba46bd605dffdd9cf6a9ce521404cbc055dfd953ed`.
- `src/a6400/debug/arm_hook.py` — target bounds from verified evidence
  (`Kernel text 0x00108000-0x0048d023` + PAGE_OFFSET `0x60000000` ⇒
  `0x60108000-0x6048d023`), PC-relative/PC-writing/branch/undef instruction
  rejection, B/BL encoding, install/clear with explicit `flush_icache_range`
  modelling, record decoder.
- `tests/test_arm_hook.py` — **15 tests pass**, including Unicorn execution of
  the assembled stub: the hooked `add r0,r0,#1` is executed (r0/r1/r2 =
  `0x42/0x42/0x84`), the captured record holds pre-instruction registers,
  `sp`, `lr`, `cpsr` and the configured dereference (`0xdeadbeef`), the
  sequence counter takes its preloaded value, ring wrap is exercised, and
  `hook_clear` restores the target word byte-for-byte and resets the stub
  saved-instruction slot, with both code ranges flushed on install and both on
  rollback.

Hardware hook installation was **not** attempted: it is a live kernel-text
write and remains blocked by the Phase 1 boundary and by the explicit rule that
UVC/hook hardware work waits for the debugger's hardware checks.

## 7. Boundaries / what is not claimed

1. **No always-on debugger inside stock PC Remote.** The stock PC Remote PTP
   server exposes no `usb_extcmd`/DiExtCmd transport. Keeping the debugger
   reachable there requires the authored composite-gadget overlay (a vendor
   interface or an extended descriptor lease in gadgetcore), which is Phase 2
   kernel work and was not attempted. No claim that the daemon can be reached in
   PC Remote by any host-side trick.
2. **No in-band PC Remote → MSC switch.** `SonyReqReconnect 0x9282` is not
   available in that mode. Zero-battery-pull recovery today is: return the
   camera to Mass Storage through its own menu (verified, pid preserved), or
   first add the composite overlay. MTP-mode reachability and a live
   MTP→MSC in-band switch are also unconfirmed (§5.1), so no claim is made for
   them either.
3. `recover` was hardware-verified only in the "no authored module loaded"
   state (`already_stock`). Its allowlisted `delete_module` path is statically
   audited but not exercised on a loaded authored module; do not treat it as a
   proven unload/descriptor-restore path yet.
4. The warm ring is the camera kernel's own text ring. Structured hook records
   need a separate reserved physical region (and a warm-boot test), which is
   not selected or written.
5. The hook prototype is single-writer by construction; per-CPU concurrency,
   IRQ-context re-entrancy, live kernel-text mapping (`set_memory_rw`-style) and
   real `flush_icache_range` are not modelled/executed.
6. No UVC descriptor, `VS_PROBE`, `ffmpeg`, firmware, boot or SD change was
   made. The camera remains in Mass Storage with the v2 daemon installed and
   responsive.

## 8. Repeatable commands

```
.\venv\Scripts\python.exe tools\camera_debugger.py usb-state
.\venv\Scripts\python.exe tools\camera_debugger.py dmesg --output artifacts/hardware/e0401-debugger-v2/dmesg.txt
.\venv\Scripts\python.exe tools\camera_debugger.py dump-ring --output artifacts/hardware/e0401-debugger-v2/klog-ring.bin
.\venv\Scripts\python.exe tools\camera_debugger.py recover
.\venv\Scripts\python.exe tools\camera_debugger.py recover --to-msc
.\venv\Scripts\python.exe -m tools.research.build_usb_debugger_v2 --audit-only
.\venv\Scripts\python.exe -m unittest tests.test_arm_hook tests.test_usb_debug_ring tests.test_camera_debugger_protocol
```
