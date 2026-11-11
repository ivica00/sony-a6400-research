# a6400 live-view daemon (`a6400-lived`)

The camera-side half of the composite UVC live-view transport for the Sony
ILCE-6400 (a6400).

It merges the two pieces that have only ever been run **separately** on the
camera:

* the composite session runner (`tools/native_camera/uvc_ptp_feed_runner.c`):
  freeze PID 149 â†’ publish entry hook â†’ INIT â†’ hold â†’ STOP â†’ freeze â†’ retire;
* the 30 fps sensor feeder (`tools/native_camera/uvc_sensor_feeder_30fps.c`):
  OSAL â†’ DMM rule 5 â†’ SET_PATH â†’ GET_JPEG â†’ DMM open â†’ WAIT â†’ UPDATE.

The merge is not cosmetic. A **second** `open()` of the video node failed with
`-12/ENOMEM` on fragmented memory (E0339:52-57), so the feeder must run inside
the process that owns the fd. This daemon is that process, and it opens the node
exactly once.

---

## 1. Status: offline, unverified, not deployable yet

| Claim | Status |
| --- | --- |
| Code written and cross-compiled for ARMv7-A softfp | **yes** (host build only) |
| Unit-tested offline against the contract headers | **yes** (399 assertions) |
| Ever executed on a camera | **NO** |
| Ever caused a frame to be streamed to a host | **NO** |
| Deployable under the project's own rules today | **NO** â€” boundaries B3 and B5 |

Do not read a successful build as hardware evidence. Two independent camera-side
blockers stand between this binary and a first frame, and neither is in this
directory (details in `module/README.md`):

* **B5** â€” the project's audit tool refuses transport builds
  (`tools/research/audit_uvc_ptp_module.py:30` requires `start_probe_only`, and
  every transport build necessarily has it false). No transport module may be
  deployed until a transport audit exists and passes.
* **B3** â€” the composite descriptor advertises the VS bulk-IN endpoint as
  `0x84`, while the START bridge matches only `0x81`
  (`uvc_composite_shim.c:779-806`, `uvc_callback_bridge.c:79-84`). That is why
  transport builds bind but never stream.

### What this daemon is NOT

* It is not a replacement for the module. It is a client of that module's ioctls.
* It is not a control-plane breakthrough. Camera settings are **not applied**
  here; they are routed back to the host's verified PTP session.
* It is not a latency claim. No glass-to-glass measurement exists anywhere in
  the repository (boundary B10), and `frame_age_ms` in the Android app is a
  host-side buffer age, not latency.
* It is not the primary path. Track A (Android PTP) is the verified path and
  needs no camera code at all (Â§10).

---

## 2. Architecture

```
                  one process, one video fd
  â”Śâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
  â”‚  main.c                                                          â”‚
  â”‚                                                                  â”‚
  â”‚  /tmp_bt/video (248:33) â”€â”€ uvc.c â”€â”€ INIT/REG_BUF/ENABLE/WAIT/     â”‚
  â”‚       â”‚                              UPDATE/UNREG/STOP            â”‚
  â”‚       â”‚                                                          â”‚
  â”‚  runner.c â”€â”€ ptrace freeze PID149 â†’ HOOK_PUBLISH â†’ resume        â”‚
  â”‚              ... teardown: STOP â†’ freeze â†’ HOOK_RETIRE â†’ resume  â”‚
  â”‚                                                                  â”‚
  â”‚  osal.c â”€â”€ /dev/uipc â”€â”€ dynamic reply id â”€â”€ DMM rule 5           â”‚
  â”‚              â”‚                    â””â”€â”€ SET_PATH start/stop        â”‚
  â”‚              â””â”€â”€ GET_JPEG â”€â”€ jpeg_result â”€â”€ DMM OpenUnit         â”‚
  â”‚                                              â”‚                   â”‚
  â”‚  frame.c â”€â”€ admission (order fixed, fail-closed) â”€â”€ slot 0/1     â”‚
  â”‚                                              â”‚                   â”‚
  â”‚  control.c â”€â”€ FIFO requests â†’ ack file       â”‚                   â”‚
  â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”Ľâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
                                                 â”‚
                              /dev/mem bounded pread (â‰¤64 B) for the JPEG prefix
```

Frame loop, per tick (absolute `CLOCK_MONOTONIC` deadlines, never relative
sleeps):

1. `GET_JPEG` with a 50 ms reply bound. Empty â†’ wait for the next deadline.
2. Ready â†’ `DMM OpenUnit` for `{phys, mapped_size}`.
3. Read â‰¤64 prefix bytes from `/dev/mem` (default: one bounded `pread`;
   `--read-prefix`: mmap the window). Failure is logged as `prefix_unavailable`
   and no SOI is ever fabricated.
4. `a6400_frame_admit` â€” depth 1, full validation order.
5. `WAIT` (bounded by an interval timer, duration measured) â†’ `UPDATE`
   `{frame_size, slot phys}` â†’ `release(slot)` â†’ `DMM close+free`.
6. Poll the control FIFO (non-blocking) and act on STREAM_STOP.

Depth is exactly **1**. When a frame is still in flight the new frame is
**dropped at the producer**, never buffered: buffering turns a transport stall
into growing latency, which is the failure mode this design forbids.

---

## 3. Files

| Path | Role |
| --- | --- |
| `include/a6400_*.h` | The six contract headers. Unchanged **except additive fields** in `a6400_daemon.h` (SD options) and `a6400_log.h` (second sink); neither is a wire ABI (see Â§11). |
| `include/a6400_internal.h` | **Added.** Internal (non-wire) declarations shared by `runner.c`, `control_bridge.c` and the host tests. |
| `include/a6400_sdlog.h` | **Added.** SD policy/status declarations (`--sd-log`); see `src/sd_policy.c`, `src/sd_mount.c`. |
| `src/osal.c` | `/dev/uipc` client, DMM ops, SET_PATH, GET_JPEG. |
| `src/usb_stream.c` | Video-node client, single open, mknod fallback under `/tmp_bt`. |
| `src/frame_hook.c` | Bounded SOF parser + depth-1 admission queue. |
| `src/runner.c` | ptrace freeze/resume, attest v2 publish/retire, stop attestation, park. |
| `src/control_bridge.c` | Wire protocol, routing table, FIFO re-framing, ack file. |
| `src/log.c` | Bounded 256 KiB JSONL logger + optional O_SYNC SD second sink. |
| `src/sd_policy.c` | **Added.** Pure device/mount-point/window/rotation gates (host-tested). |
| `src/sd_mount.c` | **Added.** mount(2)/umount2/stat//proc/mounts/sentinel verification. |
| `src/main.c` | Lifecycle, pacing, teardown, receipt. |
| `build.sh` | Static ARM build + `build/manifest.json`. |
| `Makefile`, `make.cmd` | Thin wrappers (see Â§4). |
| `test/host_test.c`, `test/run_host_tests.py` | Offline unit tests. |
| `tools/deploy.py` | Documentation-with-checks deploy plan; executes nothing. |
| `module/README.md` | Module prerequisites, B3/B5, E0340 hazard, RAM-only protocol. |

`src/*.c` are the only objects in the daemon; there is no optional component and
no conditional `#ifdef` that changes behaviour between builds.

---

## 4. Build and test

All builds are offline. Nothing in this directory talks to a camera.

```powershell
# from camera-daemon/, Windows PowerShell
.\make.cmd arm              # == mingw32-make arm; calls build.sh through WSL
.\make.cmd host-tests       # builds and runs the unit tests
.\make.cmd clean

# or directly
wsl -d Ubuntu -- bash -lc "cd '/mnt/c/Users/Administrator/Desktop/a6400 project/camera-daemon' && ./build.sh"
python test/run_host_tests.py
```

* **ARM build**: `arm-linux-gnueabi-gcc -std=gnu11 -march=armv7-a
  -mfloat-abi=softfp -O2 -Wall -Wextra -Werror -Iinclude`, linked `-static`.
  Full static glibc works, so the `sony_sysroot`/`snapshot_start.S` fallback was
  not needed.
* **GNU make is not installed on this host**; `mingw32-make` is. `make.cmd` is a
  one-line forwarder so `.\make arm` works from PowerShell.
* **Host tests**: the runner prefers an x86 `gcc`/`cc`/`clang` **inside WSL**
  (the documented path). This machine has no x86 compiler or libc headers in
  WSL (`gcc` absent, `/usr/include/stdio.h` absent, no sudo), so the runner
  invokes the Windows MinGW gcc through WSL interop when it is started inside
  WSL, and uses it directly when started from Windows. The compiler and command
  are always printed, so the receipt is unambiguous. See "Deviations" (Â§11).

Current receipts (measured, host build only):

```
ARM    build/a6400-lived      629592 bytes
       sha256 aa2c1cb020b9afcbb63f4d14b65bb8a5bc578b3691fa1955a9b3bc4f96d90ec6
       warnings 0 under -Werror; statically linked ARM EABI5
host   build/host_test.exe    399 checks, 0 failures
```

Re-run the commands above to refresh them; the numbers in this file are a
receipt, not a promise.

---

## 5. Flags and the evidence behind each one

| Flag | Default | Evidence / reason |
| --- | --- | --- |
| `--device PATH` | `/tmp_bt/video` | The node is major 248 minor 33 (E0320/E0321). `devno.ko` on this firmware does not create it, so the client mknods it â€” only under `/tmp_bt`. |
| `--log PATH` | `/tmp_bt/a6400_lived.jsonl` | `/tmp_bt` is a 1 MiB tmpfs (`reports/a6400_hw_dump.txt:234`); `log.c` refuses any path outside `/tmp_bt/` and caps the file at 256 KiB. |
| `--receipt PATH` | `/tmp_bt/a6400_lived_receipt.json` | A file log does not survive a reboot (E0342:24-26); the receipt is the durable record and is written before any mode change. |
| `--control-fifo PATH` | `/tmp_bt/a6400_ctrl.fifo` | Request source (Â§6). Created by the daemon if absent. |
| `--control-ack PATH` | `/tmp_bt/a6400_ctrl.ack` | Reply path (Â§6). One frame per rewrite. |
| `--dry-run` | off | Discovery only: open, identity, USB state, `MOD_QUERY_DMA`. No freeze, no INIT, no REG_BUF, no ENABLE, no UPDATE, no SET_PATH. |
| `--arm-transport` | off | **Required** for every destructive step. Without it (and without `--dry-run`) the daemon refuses with exit 3 before touching anything. E0340's mode-switch reboot is why the default is refusal. |
| `--wait-pcremote` | off | INIT returns `-1/EINVAL` in Mass Storage (E0342), so the runner gated on `0x054c:0x0caa` before INIT (`uvc_ptp_feed_runner.c:135-158`). |
| `--timeout SEC` | 120 | Bound on the PC Remote wait. The runner default was 300; 120 keeps a stuck session short. |
| `--duration SEC` | 0 (until SIGINT) | The runner held for a fixed 90 s. 0 lets a control `STREAM_STOP` or SIGINT end it. |
| `--pid N` | 149 | `im.elf` is PID 149 (E0313/E0339). |
| `--fps N` | 30 | The feeder's `33333333 ns` period (30 fps). |
| `--comp-level N` | 5 | Feeder's SET_PATH component level (`uvc_sensor_feeder_30fps.c:550`). |
| `--path-width N` | 1280 | Feeder's SET_PATH width hint. **A hint only**: the accepted width gate for selector `0x50` is undecoded (LIVEVIEW_DMA.md:691-697). |
| `--width/--height` | 0/0 | 0/0 means "learn from the first real frame"; any other value makes the SOF dimensions mandatory. Do **not** hardcode 1280Ă—720: real frames on the PTP path are 1024Ă—680, and the 320/640/1024 allowlist applies to a different selector. |
| `--dma-phys HEX`, `--dma-size N` | 0 | Fallback only when `MOD_QUERY_DMA` is absent (stock driver, `-25/ENOTTY`). Without them the daemon fails closed rather than reusing the historical fixed window `0x20000000/1294 KiB` (`docs/UVC_HANDOVER_PLAN.md:36-38`). |
| `--read-prefix` | off | Use mmap of the DMM window for the prefix instead of one bounded `pread` (both are â‰¤64 bytes; the feeder mmap'ed, `uvc_sensor_feeder_30fps.c:683`). |
| `--wait-ms N` | 1000 | Bound on the WAIT ioctl (boundary B4: semantics undecoded). |
| `--stats-interval SEC` | 0 | Periodic stats event + receipt rewrite. |
| `--sd-log` | off | E0350: mirror every completed JSONL line **and** the final receipt to the SD card. A battery pull wipes `/tmp_bt`; the SD copy is the only receipt that survives. A failed SD write drops the sink, counts the error and leaves RAM logging intact. |
| `--sd-mount` | off | Explicit mount(2) consent. **Requires `--sd-log`.** Refused unless PC Remote `054c:0caa` was confirmed, INIT has not started, and this is not a dry run; never mounted in Mass Storage (the camera app owns the card). |
| `--sd-dev PATH` | `/dev/mmca1` | SD data partition (block 250:11, E0222). Only that exact node is accepted; `/dev/mmca` (whole card) and every `/dev/nflasha*` internal-flash node are refused before any syscall. |
| `--sd-mountpoint PATH` | `/tmp_bt/sd` | Rootfs is read-only ext2 and `/tmp_bt` is the only writable directory, so the mount point must be a child of `/tmp_bt/`. `mkdir` is attempted there only; `/setting`, `/etc`, `/system`, `/log`, `/tmp`, `/lens`, `/cert` are refused. |
| `--verbose` | off | DEBUG-level logging and control-layer diagnostics on stderr. |

### 5.1 SD logging: mount window, verification, and what it cannot promise

```
             MSC (camera app owns SD)          PC Remote confirmed          INIT/streaming
  mount:            REFUSED  <--- gate --->  ALLOWED (mount + verify)  <--- REFUSED (too late)
  unmount:                                                                  teardown, every path
```

* **Window.** The daemon mounts only after `await pcremote` observed
  `054c:0caa` and before the freeze/INIT block. `--sd-log` without `--sd-mount`
  stays RAM-only (`mount_rc = -9`); a dry run reports `mount_rc = -10`; an
  unconfirmed PC Remote reports `-12`. There is no retry outside the window.
* **Verification is four independent checks.** (1) `stat(/dev/mmca1)` must be a
  block node with `rdev == 250:11`; (2) `/proc/mounts` must not already contain
  the device or the mount point; (3) after `mount(...,"vfat",0,NULL)`
  `/proc/mounts` must contain exactly `/dev/mmca1` at exactly that mount point
  (E0222: names/majors in that table are not identity); (4) a sentinel file is
  written with `O_SYNC` and read back byte-for-byte. Any failure unmounts what
  this call mounted and reports `mounted: 0` â€” never a fabricated success.
* **Sink.** `A6400LD.LOG`, `O_WRONLY|O_CREAT|O_APPEND|O_SYNC` (`fsync` per line
  if a build lacks `O_SYNC`), capped at 128 KiB with one rotation to
  `A6400LD.1`, strict 8.3 names (E0236). Every RAM line is mirrored
  synchronously; the write is bounded by the 512-byte line cap, so the frame
  loop is not blocked. The receipt is copied as `A6400RCPT.JSON` (the
  brief-mandated 8+4 name; vfat long names carry it) with `O_SYNC` + `fsync`.
* **Teardown.** `sd_teardown()` runs on *every* teardown path, including the
  stop-attestation **park** (before parking, so a later battery pull cannot lose
  the receipt): it rewrites the receipt while mounted, closes the sink, then
  `umount2(mountpoint, 0)`. A failed unmount leaves `mounted: 1` and records
  `unmount_rc`; it is never reported as clean.
* **Risks, stated plainly.**
  * The camera app owns the SD in Mass Storage, so a mount after a missed mode
    check can fail `EBUSY` (`mount_rc = -16`) or mount the wrong namespace. The
    gate exists because that failure is not hypothetical. **Do not mount in
    MSC.**
  * A battery pull during an `O_SYNC` write can leave a partial last line
    (valid JSONL up to that line) or a partial receipt copy; the previous
    complete receipt is not preserved (the file is `O_TRUNC`). Treat the SD
    receipt as best-effort durability, not a journal.
  * The card may be unformatted/read-only/full: all of those are counted in
    `sd_log.errors` / `log_sd_errors` and the stream continues.
  * Mounting vfat makes the card host-visible from the camera; the session must
    unmount before returning to Mass Storage. A mount that is still live at
    process exit is reported, not hidden.

Exit codes: **0** clean, **2** stage failure, **3** refused, **4** fatal.

---

## 6. Control protocol (FIFO in, ack file out)

This channel exists because **host PTP control costs 10â€“30 ms** (CONTROL_IPC.md
Â§0) and absolute writes are unreliable on this camera. It does not replace PTP;
it splits by route.

### 6.1 Request framing (FIFO)

* Each request is exactly `12-byte header + payload_len` bytes, little-endian,
  written with **one** `write()` of at most `PIPE_BUF` (4096) bytes. With
  `A6400_CTL_MAX_PAYLOAD = 64` a frame is at most 76 bytes, so writers never
  interleave.
* A reader may still see partial frames or several frames in one `read()`; the
  daemon re-frames by the `payload_len` field and **fails closed** on a bad
  magic or an impossible length (it drops bytes and resynchronises on the next
  `0xa640`, never guessing a frame start).
* A FIFO with no writer attached reads as EOF (`read()` returns 0). The daemon
  treats that as "no request", not as a fatal error.

Header (packed, 12 bytes): `magic=0xa640`, `version=1`, `opcode`, `seq`,
`payload_len`, `flags`, `crc16`.

CRC is CCITT-FALSE (poly `0x1021`, init `0xffff`, no final xor) over **header
bytes 0..9 followed by the payload**. A stored CRC of `0` disables the check.
A wrong magic or a bad CRC is reported as `BAD_LENGTH` because the status enum
has no `BAD_MAGIC`/`BAD_CRC` member and inventing a value would break hosts.

### 6.2 Ack framing (file)

* Each reply **rewrites** the ack file: `lseek(0)`, one `write()` of
  `18-byte ack + reply payload`, `ftruncate()`. No `fsync`: on the camera the
  path is tmpfs and the protocol makes no durability claim.
* Ack (packed, 18 bytes): `magic`, `version`, `opcode`, `seq`, `status`,
  `detail`, `value`, `crc_state`.
* `crc_state` is used as an integrity word: CRC-16/CCITT-FALSE over the first 14
  ack bytes. `0` is never emitted, so it cannot be confused with "not computed".
* Reply payloads: `GET_STATS`/`GET_STATE` append `a6400_ctl_stats_reply`
  (40 B); `GET_CAPS` appends `a6400_ctl_caps_reply` (16 B); everything else
  appends nothing.

### 6.3 Routing table

| Opcode | Ack status | detail / value |
| --- | --- | --- |
| `PING` 0x00 | `OK` | `value = protocol version` |
| `DAEMON_INFO` 0x01 | `OK` | `detail = 1` (reply layout revision), `value = uptime ms` |
| `GET_CAPS` 0x32 | `OK` | + 16-byte caps payload |
| `GET_STATE` 0x30 | `OK` | `detail = session_active`, + stats payload |
| `GET_STATS` 0x31 | `OK` | + stats payload |
| `SET_LATENCY` 0x40 | `OK` | `detail = 1` = **recorded only**; it does not bound transport latency |
| `DROP_STATS_RESET` 0x41 | `OK` | `value = 5` counters re-baselined (see below) |
| `STREAM_START` 0x20 | `OK` | action `STREAM_START` |
| `STREAM_STOP` 0x21 | `OK` | action `STREAM_STOP` |
| `STREAM_CONFIG` 0x22 | `OK` | action `STREAM_CONFIG` + echoed config |
| `SET_ISO` 0x10 | `ROUTE_PTP_HOST` | `detail = 0x9207`, `value = 0xD21E` |
| `SET_SHUTTER` 0x11 | `ROUTE_PTP_HOST` | `detail = 0x9207`, `value = 0xD20D` |
| `SET_APERTURE` 0x12 | `ROUTE_PTP_HOST` | `detail = 0x9207`, `value = 0x5007` |
| `SET_EXPOSURE` 0x13 | `ROUTE_PTP_HOST` | `detail = 0x9207`, `value = 0x5010` |
| `SET_WB` 0x17 | `ROUTE_PTP_HOST` | `detail = 0x9207`, `value = 0x5005` |
| `AF_MODE` 0x14 | `ROUTE_PTP_HOST` | `detail = 0x9207`, `value = 0x500A` |
| `STEP` 0x18 | `ROUTE_PTP_HOST` | `detail = 0x9207`, `value` = one of `0xD20D/0x5007/0x5010` |
| `AF_TRIGGER` 0x15 | `CONTRACT_UNKNOWN` | no code, property or mechanism in the evidence base |
| `TOUCH_FOCUS` 0x16 | `CONTRACT_UNKNOWN` | same |
| anything else | `UNKNOWN_OPCODE` | `value = the opcode` |

Why `ROUTE_PTP_HOST`: the camera-side handler for these codes,
`InfraRemoteUsb::CtrlCode2InputKey`, converts a Sony control code into a
**directional UI key** (`0xD20D`â†’15/16, `0x5007`â†’8/9, `0x5010`â†’3/4). PC Remote
control is virtual key injection, which is exactly why absolute `0x9205` is
acknowledged but not effective and why the signed notch `0x9207` was physically
confirmed (CONTROL_IPC.md Â§0, Â§2.4; CINEMAHUD_STOCK_PTP.md:38-46).

`detail` can carry only one opcode: it is `0x9207` for the change. **The
readback opcode is `0x9209`** and the host must issue it itself to confirm a
new value. The daemon cannot read back, so it never claims a value was applied.

`applied` is not a wire field. The invariant this code enforces and tests is:
`status == OK` is the only success, and **no setting opcode can ever produce
it**. That is the honest, testable form of "never report applied without a
readback".

### 6.4 Payload units (mirrored from PTP, never rescaled)

`struct a6400_ctl_set_value { uint32_t code; uint32_t value; }` is the payload
of `SET_ISO`, `SET_SHUTTER`, `SET_APERTURE`, `SET_EXPOSURE`, `SET_WB`,
`AF_MODE` and `STEP`. `code` is the firmware property code and `value` is that
property's own raw unit:

| Control | Code | Encoding |
| --- | --- | --- |
| Shutter | `0xD20D` | `(numerator << 16) | denominator`; `0x00010064` = 1/100; denominator `0` = Bulb |
| Aperture | `0x5007` | f-number Ă— 100 (`280` = f/2.8) |
| Exposure comp | `0x5010` | millistop (`300` = +0.3 EV) |
| ISO | `0xD21E` | absolute ISO; `0xFFFFFF` = Auto |
| White balance | `0x5005` | camera enumeration (`2` Auto, `4` Daylight, `6` Tungsten, `0x8010` Cloudy, `0x8011` Shade) |
| AF mode | `0x500A` | camera enumeration (`1` MF, `2` AF-S, `3` AF-C, `0x8004` AF-A, `0x8005` DMF) |

`STEP` uses the same 8-byte payload; the low byte of `value` is the signed
one-byte notch. A wrong `code` for the opcode is `BAD_VALUE`.

`DROP_STATS_RESET` establishes a baseline; subsequent stats replies report
**deltas** for dropped/rejected/transport-error counters while the daemon's
absolute counters (and the receipt) keep running. That re-baselines the control
view without a second write path into the daemon core.

---

## 7. Deliberately fail-closed behaviour

Every item below is an intentional refusal, not an unfinished path.

1. **No `--arm-transport`, no destructive work.** Exit 3, receipt written.
2. **Paths outside `/tmp_bt` are refused** for the video node, FIFO and ack file;
   the log refuses too and degrades to stderr only.
3. **`mknod` only under `/tmp_bt/`.** Anywhere else returns `-EPERM`.
4. **One open attempt.** `ENOMEM` is never retried; a second large DMA open
   cannot be satisfied (E0339:52-57).
5. **`MOD_QUERY_DMA` unavailable and no operator window** â†’ stage failure, exit
   2. The historical fixed window is not reused.
6. **`REG_BUF` rejection** â†’ stage failure before any frame is attempted.
7. **Repeated transport errors** (30 consecutive `GET_JPEG`/`WAIT`/`UPDATE`
   failures) â†’ stage failure, exit 2. No infinite retry loop.
8. **Stop attestation failure** â†’ **park**. The receipt is written, and the
   process keeps the fd and hook state instead of retiring, closing or retrying.
   A signal is the operator's explicit decision to leave.
9. **Freeze / retire / resume failure** â†’ exit 4 with the exact rc in the
   receipt. Never a fabricated clean session.
10. **Unknown control opcode** â†’ `UNKNOWN_OPCODE`, never ignored.
11. **Never `OK` for a camera setting.** No readback exists today, so no
    "applied" claim exists.
12. **No fabricated JPEG prefix.** If `/dev/mem` cannot be read, the frame is
    admitted only while the accepted geometry is still unknown (the documented
    byte-free discovery admission) and is otherwise rejected as `ERR_JPEG`.
13. **No second video open for a control ring.** `enable_ring` is refused
    explicitly: there is no decoded ring ioctl and the fd is owned by the core.
14. **Oversized or wrapping lengths** are rejected before any driver call
    (`frame_size + 12 > slot`, `phys + size` wrap, `size_shift << 7` wrap).
15. **The log never writes a partial line**; a line that would cross the 256 KiB
    cap is dropped and `truncated` is set.
16. **SD mount requires two independent opt-ins.** `--sd-mount` without
    `--sd-log` is refused (exit 3) before the camera is touched; `--sd-log`
    alone never mounts.
17. **The SD device is not configurable past the SD partition.** Any
    `--sd-dev` other than `/dev/mmca1` is refused at config validation, with
    `/dev/nflasha*` reported as internal flash specifically. The mount helper
    re-checks the block-node identity (`250:11`) even after that.
18. **A mount that cannot be verified is not a mount.** No exact `/proc/mounts`
    entry or no sentinel read-back â‡’ unmount and `mounted: 0`.
19. **A failed SD write drops the SD sink.** The error is counted
    (`log_sd_errors`), the RAM log continues, and the frame loop is never asked
    to wait for the card.
20. **No unmount is claimed when `umount2` fails**; `unmount_rc` stays negative
    and `mounted` stays 1 in the receipt.

---

## 8. Known limitations and open boundaries

| Boundary | Effect on this daemon |
| --- | --- |
| **B3** EP `0x81` vs `0x84` START bridge | INIT/REG_BUF/ENABLE may succeed and no sample ever completes. The daemon reports transport errors and exits 2. |
| **B4** `0xF002` WAIT semantics undecoded | The daemon bounds the call with `setitimer`/`SIGALRM`, but an uninterruptible kernel sleep still cannot be bounded from userspace. `--wait-ms` is a best effort and the measured duration is always logged. |
| **B5** transport builds unauditable | No deploy under project rules. |
| `0x50e` size-vs-UnitType unresolved | Not used. The daemon never requests a DMM unit type. |
| JPEG length is an upper bound | `UPDATE` sends `size_shift << 7`, clamped to `mapped_size`; the last â‰¤127 bytes may be padding from the DMM unit. EOI-terminated decoders tolerate it, but the exact length is not knowable (E0144:21). |
| Geometry after SET_PATH | Never assumed from the request; learned from the first parsed SOF. `STREAM_CONFIG` cannot retune geometry because the selector-`0x50` width gate is undecoded â€” it is logged as ignored. |
| `A6400_CTL_STATUS_ROUTE_PTP_HOST` | Not a control success; it is a routing instruction to the host. |
| Receipt schema | Versioned `a6400-lived-receipt/1`; fields may grow. |

---

## 9. Physical test plan (for a future, authorised session)

The plan is a **checklist**, not an automation. Every step is read-only unless it
says otherwise, and step 2 is a hard gate: if the audit does not pass, stop.

| # | Step | Success criterion | If it fails |
| --- | --- | --- | --- |
| 0 | Obtain explicit user authorization for a camera-module session; record `/proc/uptime`, module list, `TracerPid` | Authorization recorded in the session note | Do not proceed |
| 1 | Build the module (`--shared-ptp-enumeration-candidate --composite-transport`) and run the audit | `offline_module_audit_passed`, hash pinned, `start_probe_only: false` accepted by a **transport-capable** audit | **STOP.** B5: today's audit refuses transport builds |
| 2 | Read-only preflight: `cat /proc/uptime; grep -E 'usbg_video|usbg_cmn' /proc/modules; ls -l /tmp_bt` | No `usbg_video`; `/tmp_bt` at baseline | Investigate before touching anything |
| 3 | Push daemon + module; `sha256sum` both on the camera | Hash equals `build/manifest.json` and the audit hash | Do not execute; re-push |
| 4 | Put the camera in **PC Remote by hand** (camera menu), then `mknod /tmp_bt/video c 248 33` if absent, then `insmod` | Node is a char device 248:33; `insmod` returns 0 | Unload/stop; never switch mode with the overlay streaming (E0340) |
| 5 | `a6400-lived --dry-run --wait-pcremote --timeout 60 --verbose` | JSONL has `usb_identity 054c:0caa`, `dma_window` (source `mod_query_dma`, or ENOTTY + explicit window), `dry_run_complete`; exit 0; receipt `status=clean` | If `ENOTTY`, rerun with `--dma-phys/--dma-size` from the module's own report; if no window is known, stop |
| 6 | `a6400-lived --arm-transport --wait-pcremote --timeout 60 --duration 10 --stats-interval 2 --verbose` — add `--sd-log --sd-mount` when a battery-pull-survivable receipt is required (the mount happens only after `054c:0caa` is confirmed). Launch it **detached** if the debugger's `exec` cannot be interrupted, because a failed stop attestation parks the process and writes the receipt first | Exit 0; receipt `status=clean`, `stop_verified=1`, `hook_retired=1`, `frames_submitted > 0` for at least some ticks; with SD: `sd_log.mounted=1`, `verified=1`, `sentinel_ok=1` and `A6400RCPT.JSON` present on the card | Any stage failure: read the receipt, do **not** rmmod, park/power-cycle per §6 of `module/README.md`. A parked daemon can still be released with SIGINT/SIGTERM |
| 7 | While step 6 runs, enumerate from the host | Windows sees `054C:0322`; a UVC client receives frames with a valid SOI and plausible SOF dimensions | If it binds and no samples arrive, record it as **B3 confirmed** and stop |
| 8 | Control smoke test against the FIFO: `PING`, `GET_CAPS`, `GET_STATS`, `SET_ISO` | `PING`â†’OK; `GET_CAPS.camera_setting_route=1`; `SET_ISO`â†’`ROUTE_PTP_HOST` with `detail=0x9207`, `value=0xD21E`; ack file parses | A wrong status is a protocol bug; capture the ack bytes |
| 9 | Let the daemon stop (duration, or `STREAM_STOP`) and read both files | Receipt `stop_verified=1`; log ends with `teardown_complete` | **PARK.** Do not retry cleanup |
| 10 | `rmmod` **only** with the verified receipt; remove owned `/tmp_bt` files | `usbg_video` absent, `/proc/uptime` monotonic, camera back in MSC | Battery pull; `/tmp_bt` evidence is lost, so read it first |

SD logging changes only how evidence survives, never the session:
`--sd-log --sd-mount` must be passed together, the mount is attempted after the
PC Remote gate and before the freeze, and every teardown path unmounts. Read
`A6400RCPT.JSON`/`A6400LD.LOG` from the card after recovery; read
`/tmp_bt/a6400_lived_receipt.json` first if the camera is still up. The host-side
counterpart (USBPcap/ETW capture of the same negotiation) is documented in
`artifacts/analysis/trackb-diag-e0351/HOST_CAPTURE_PLAN.md`.

Variables that are explicitly **not** settled by the offline build and must be
observed in step 6:

* Whether SET_PATH must be started **before** INIT. The feeder started it before
  opening the node; this daemon starts it after INIT because the single fd (and
  the runner's INIT) come first. Neither order has been run as a merged process.
* Whether `WAIT` blocks, and for how long (B4).
* The accepted SET_PATH geometry for selector `0x50`.
* The real `size_shift<<7` overshoot for a 1024Ă—680 frame.
* Whether `ENABLE` before SET_PATH start is accepted by the module.

---

## 10. Relationship to Track A (Android PTP) â€” the primary path

Track A needs **none of this**. It is the only path with physically verified
real-sensor frames on a real host:

* stock single-function PTP (`054C:0CAA`), no module, no hook, no descriptor,
  no `mknod`, no `/tmp_bt`;
* `OpenSession(0x1002)` â†’ `0x9201[1,0,0]` â†’ `0x9201[2,0,0]` â†’ `0x9202[0xC8]`
  â†’ `0x9201[3,0,0]`;
* `GetObject 0xFFFFC002` returns 1024Ă—680 MJPEG (~52â€“150 KB, ~11â€“31 fps
  depending on the client cadence) and 8 zero bytes when no new frame is ready;
* controls use the same session: `0x9209` readback, `0x9207` signed notch for
  changes (physically confirmed for shutter, aperture and EV);
* recovery is "leave PC Remote", not "battery pull".

This daemon is **Track B**, the composite UVC path. It is ranked second because
stage 1 (descriptor, enumeration) is won, but **no UVC build has ever carried a
sensor frame** â€” every UVC frame to date is a built-in test pattern. Use Track A
for latency work; use Track B only to remove the per-frame request round trip,
and only after B3 and B5 are closed.

---

## 11. Deviations from the brief, and additions

Reported honestly so nothing is buried:

1. **The contract headers are unchanged except for additive, non-wire fields.**
   `a6400_control.h`, `a6400_frame.h`, `a6400_osal.h` and `a6400_uvc.h` are
   byte-identical to the Lead's versions. `a6400_daemon.h` gained four config
   fields (`sd_log`, `sd_mount`, `sd_dev`, `sd_mountpoint`) and `a6400_log.h`
   gained the second-sink state, for `--sd-log` (E0350). Neither is a wire ABI:
   no ioctl, FIFO frame or ack byte changed. Other added declarations live in
   `include/a6400_internal.h` and `include/a6400_sdlog.h`.
2. **Byte-free discovery admission.** `a6400_frame_admit` normally requires a
   parseable prefix (the contract's `ERR_JPEG`). When the prefix is unavailable
   **and** the expected geometry is still unknown, it admits on the byte-free
   size/address/overlap checks and the daemon logs `prefix_unavailable`. Once a
   geometry has been discovered from a real frame, a missing prefix is a hard
   rejection. This is the only way to honour both "admit with the size checks
   that do not need bytes" and "never fabricate SOI".
3. **`--dma-phys`/`--dma-size` were added.** The contract config has no DMA
   window field, and inventing `0x20000000` would be a fabricated address. They
   are needed only when `MOD_QUERY_DMA` returns `ENOTTY`.
4. **Host tests use the Windows MinGW gcc in this environment.** WSL has no x86
   compiler or libc headers and no sudo to install one. `run_host_tests.py`
   prefers a Linux `gcc`/`cc`/`clang`, then (inside WSL) the Windows compiler via
   interop, then a Windows compiler directly; it always prints which one it
   used, so the documented path works unchanged on a host that has a Linux x86
   compiler. The test binary is a Windows executable in the interop case; the
   299 assertions and their meaning are identical.
5. **`UNREG` was added to teardown** before `STOP`. It is part of the physically
   run feeder's teardown (`uvc_sensor_feeder_30fps.c:742-743`); the runner never
   registered a buffer so it had no such step. The stop-attestation gate is
   unchanged and still covers `STOP` + all-zero session state.
6. **`make.cmd` was added** because GNU make is not installed on this host.
7. **Periodic receipt rewrite** (`--stats-interval`) overwrites the receipt; the
   final write at exit is authoritative. This is intentional progress evidence
   on a tmpfs that a reboot can erase.
8. **Ack-file writes are not `fsync`ed**, for latency and because the path is
   tmpfs. The receipt *is* `fsync`ed.
9. **The daemon does not unlink the device node it created.** Removing a device
   node is an operator action; the daemon cannot know whether another process is
   about to use it.

---

## 12. Safety summary

* Offline authoring only: build, unit test, documentation. No camera access, no
  module load, no debugger, no mode change.
* Every write is confined to `/tmp_bt` (log enforced by prefix check; video node
  creation enforced by prefix check). The only exception is the explicitly
  opted-in SD card (`--sd-log --sd-mount`): `/dev/mmca1` only, mounted inside
  `/tmp_bt/sd`, verified, and unmounted in every teardown path.
* **Internal flash is never mountable.** `--sd-dev /dev/nflasha*` and every
  mount point outside `/tmp_bt/` (including `/setting`, `/etc`, `/system`,
  `/log`) are refused before any syscall.
* Destructive steps require `--arm-transport` and are logged **before** they
  happen (`destructive_step` events).
* The default failure mode is refusal, not a retry, and the default success claim
  is "not verified".

Read `module/README.md` before planning any physical session.
