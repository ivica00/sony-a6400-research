# Sony ILCE-6400 (a6400): low-latency Live View + camera-control architecture

**Status: architecture decision + offline implementation set (E0348), 2026-11-11.**
Nothing in this document has been physically verified by this round: no module was
loaded, no USB mode was switched, no frame was streamed, no control was written.
The camera was used **read-only in Mass Storage** through the existing USB debugger
(standing read-only authorization) to replace assumptions with live observations;
every receipt is under `artifacts/analysis/recon-e0348/camera-mss/`.

Inputs synthesized here:

| Source | Content |
| --- | --- |
| `artifacts/analysis/recon-e0348/REPO_RECON.md` | repository map, code-execution paths, known/unknown triage |
| `artifacts/analysis/recon-e0348/LIVEVIEW_DMA.md` | frame producers, buffer ownership, interception ranking, probe list |
| `artifacts/analysis/recon-e0348/USB_GADGET.md` | kernel gadget facts, Path A/B/C evaluation, latency arithmetic |
| `artifacts/analysis/recon-e0348/CONTROL_IPC.md` | PTP control semantics, internal setting lanes, protocol design |
| `artifacts/analysis/recon-e0348/camera-mss/` | **live** MSC snapshot captured this round (see Â§3.2) |
| `docs/evidence/` | E0134, E0143, E0144, E0145, E0149, E0151, E0154, E0288, E0316, E0319, E0320, E0339, E0340, E0342, E0343, E0344, E0345, E0346, E0347 |

Tags used throughout: **[V]** physically verified in this repository (evidence ID),
**[E]** verified only in the emulator/offline decode, **[I]** inference, **[?]** unknown.

---

## 1. Executive decision

The mission brief assumed the bottleneck is the PTP *request/response pull* and that
replacing it with a synchronous camera-side push (UVC isochronous/bulk or raw bulk
push) is the shortest way to sub-35 ms. The evidence says something more precise:

1. **A camera-side push is not the only way to remove the pull round-trip.**
   The host can keep 2â€“3 `GetObject 0x1009` liveview transactions in flight in one PTP
   session. That turns the "one request per displayed frame" model into a continuously
   fed pipeline with **zero new camera-side code** â€” and PTP liveview is the **only**
   transport on this camera that has ever carried real sensor frames to a real host
   (E0151, E0339, E0343: real 1024Ă—680 JPEGs at 24.6â€“30.8 fps, with a control write
   confirmed in the same session).
2. **A camera-side UVC push is architecturally possible but not yet physically proven.**
   The composite UVC+PTP descriptor binds on Windows (E0347) but no sensor frame has
   ever crossed UVC on this camera (`sensor_frames=0` in every attempt), the transport
   build currently binds yet produces no DirectShow samples, and its audit path is
   incomplete (see Â§8.2). It is the right **second** track because its ceiling is
   higher (removes the per-frame request entirely, gives a standard UVC device for any
   host), not the right **first** track.
3. **Sub-35 ms glass-to-glass is not achievable by any transport choice.**
   Every known producer is frame-based MJPEG at â‰30 fps (33.3 ms frame period;
   descriptor interval 333,333 Ă— 100 ns). Realistic end-to-end is **â‰40â€“55 ms**.
   The honest target is "â‰¤1.5 frame periods, â‰45 ms typical, measured p95". If
   <35 ms is a hard requirement, it is a **producer-format research question**
   (is there a non-frame-based liveview path on this SoC?), not a USB question.
   The three levers that actually matter are host-only: pipeline the requests,
   remove the client's 200 ms control settle, shorten decode/present.

**Decision:**

| Track | Content | Why | Status |
| --- | --- | --- | --- |
| **A (primary, ship now)** | Host-driven **pipelined PTP push pipeline** over the stock PC Remote link (`054C:0CAA`), controls over the same PTP session (`0x9207` notch / `0x9209` readback), decode + SGSR upscale on Snapdragon 8 Gen 3 | only path with verified real frames + verified concurrent control; zero camera code; cannot crash `scalar`; RAM-only by construction | implemented in `android-client-ref/` |
| **B (secondary, gated)** | Camera-side **daemon** (`camera-daemon/`) merging session runner + sensor feeder, feeding **composite UVC bulk-IN MJPEG** (PID `0x0322`) with a depth-1 queue, plus a control bridge | highest ceiling; removes request round-trip; standard UVC for any host | implemented offline; gated on module audit + stage-2/3 physical tests + explicit authorization |
| C (rejected) | Pure UVC + Extension Units for controls on EP0 (Path A) | no XU exists in any reference descriptor (`bmControls = 0`), needs the ZV-E10 five-component overlay **and** authored control entities **and** an internal apply contract that does not exist | not implemented |

Both tracks share the same Android decode/render/upscale pipeline and the same
control semantics, so the host app does not fork when B lands.

---

## 2. Mission constraints that shaped the design

| Constraint (from the brief and `AGENTS.MD`) | Consequence in this architecture |
| --- | --- |
| **RAM-only; battery pull restores stock** | Everything camera-side lives in `/tmp_bt` (1 MiB tmpfs). No flash partition, bootloader, `/etc` preload or SD change. Track A deploys **nothing** to the camera. |
| **Never crash `scalar`/`im.elf`** | Track A touches only stock PTP property/GetObject operations. Track B keeps the entry-hook publish/retire and verified-stop attestation protocol; USB mode is never switched while an overlay is active (E0340 reboot hazard). |
| **No fabricated addresses** | Every constant is a message-ABI value from physically run code (feeder/runner) or a symbol confirmed live via `/proc/kallsyms` this round (Â§3.2). Nothing is hardcoded as a memory location; all buffers are discovered per session. |
| **No placeholders/mock success** | Every offline component fails closed with explicit status codes. Camera-setting opcodes that have no decoded internal contract answer `ROUTE_PTP_HOST`/`CONTRACT_UNKNOWN`, never "applied". |
| **<35 ms glass-to-glass** | Re-scoped honestly (Â§7): target â‰¤1.5 frame periods â‰45 ms typical p95. This is stated as a constraint on the *producer*, not something the transport can promise. |

---

## 3. Ground truth

### 3.1 Repository-verified facts (with evidence)

| Claim | Evidence | Grade |
| --- | --- | --- |
| PTP PC Remote liveview delivers **real sensor frames**: 1024Ă—680 JPEG, 52â€“141 KB, 24.6â€“30.8 fps | E0151:16-22, E0339:10-18, E0343:8-13 | **[V]** |
| A control write is confirmed **while frames stream** (`POST /api/control` â†’ `confirmed/applied`, re-read intact) | E0343:20-26 | **[V]** |
| Sony PTP semantics: handshake `0x1002[1] â†’ 0x9201[1,0,0] â†’ 0x9201[2,0,0] â†’ 0x9202[0xC8] â†’ 0x9201[3,0,0]`; `0x9209` = one 1730-byte property blob; `0x9207` signed notch is **effective** (shutter 1/100â†’1/125â†’1/100, aperture f/2.8â†’f/3.2â†’f/2.8, EV 0â†’+0.3â†’0); `0x9205` absolute writes are acknowledged but **not effective** (firmware maps those codes to UI keys via `CtrlCode2InputKey`) | CONTROL_IPC.md Â§1-2; E0343 | **[V]** |
| PTP liveview fetch costs â‰**10.2 ms** (`ptp_fetch_ms`) per frame | p8-status2.json:898 via CONTROL_IPC.md | **[V]** |
| UVC 720p MJPEG transport works end-to-end with a test-pattern source: 180 frames at 29.9592 fps, Windows `USB Streaming Device` `054C:0322` | E0143:26-34, E0339:20-29 | **[V]** |
| Composite UVC+PTP descriptor binds on Windows: parent + WPD `MI_00` + Camera `MI_01`, no ProblemCode, DirectShow `ILCE-6400` | E0347:27-44 | **[V]** |
| Composite module is **enumeration-only** in the E0345 build: `REG_BUF`/`ENABLE` return `-95` | E0345:28-31 | **[V]** |
| `IOCTL_UVC_INIT` is valid **only in PC Remote** mode (`-1/EINVAL` in MSC) | E0342:8-14 | **[V]** |
| Switching USB mode while a UVC overlay streams **rebooted the camera** | E0340:25-36 | **[V]** |
| A second `open()` of the video node fails `-12/ENOMEM`; the feed must go through the runner's own fd | E0339:52-57 | **[V]** |
| `im.elf` (PID 149) is restored from hibernation and **never exec'd**, so `/etc/ld.so.preload` cannot be applied to it; preload on this camera is a persistent flash write | E0084:45-57, E0085 | **[V]** |
| An external `/dev/stream` open+mmap **rebooted the camera**; the safe display read is ptrace of the app's own mapping | E0297:82-108, E0298:8-48 | **[V]** (incident) |
| UVC function does not exist in shipped a6400 firmware: no `usbg_video.ko`, no `libInfraStreamingUsb.so`, no `/dev/usb/video` 248:33, no `/dev/usb/audio` 248:32 | E0316, E0320, E0321 | **[V]** |
| Everything UVC on a6400 is the ZV-E10 reference module re-bound to a6400 symbols | E0316:47-75, E0319 | **[E]**+**[V]** |
| `0x50e` is a DMM **UnitType**, not a byte size; the historical fixed `PA 0x20000000` window is not ownership | E0144:29-33 | **[V]** |

### 3.2 Live MSC snapshot captured this round (new observations)

Read-only through `tools/camera_debugger.py` (`usb_extcmd`, PID 703, root). Logs in
`/tmp_bt`, fetched to `artifacts/analysis/recon-e0348/camera-mss/`; no writes to
flash/SD, no mode switch, camera stayed responsive.

| Observation | Value | Why it matters |
| --- | --- | --- |
| `/proc/uptime` | 3464.18 s (monotonic later in the round) | no reboot during the round |
| kernel | `3.0.27_nl-rt106+ â€¦ gcc 4.5.1 (Sony CE Linux 8.2.6.0) #1 SMP PREEMPT RT` | matches the emulator's vermagic target |
| `/proc/cmdline` | `init=/sbin/init initrd=0x700000,8M â€¦ cmpr.path=/system/sabin/ssboot.bin warm.mode=2 â€¦ root=/dev/ram0` | confirms hibernation restore (`warm.mode=2`), i.e. no exec of `im.elf` |
| UDC | `/sys/class/udc/dwc3.0` = `state=configured`, `current_speed=high-speed`, `maximum_speed=super-speed`, `is_otg=0` | the UDC is a high-speed bulk pipe; isochronous is available but not used by any existing descriptor |
| modules | **42** loaded; `usbg_storage`, `usbg_stillimage`, `usbg_sen`, `usbg_buspower`, `devno`, `osal_uipc`, `dma330`, `grm_gles`, `dmm`, â€¦ ; **no `usbg_video`, no `usbg_audio`** | confirms E0320/E0321 at this boot |
| `/proc/kallsyms` | `usb_gadgetcore_ioctl` **0x602b8844** (the entry-hook target), `usb_gadgetcore_register_driver` 0x602b8610, `usb_gcw_start` 0x602bd7f8, `usb_gcw_stop` 0x602bd834, `dma330_mem_transfer_async` 0x5f49d768; `usb_sync_alloc/free_phys_buffer` present per-module in `usbg_stillimage` 0x5f03f038/0x5f03f15c, `usbg_sen`, `usbg_buspower`, `usbg_storage` | the symbols the entry hook and the ZV-E10 driver need actually exist on this boot â€” read-only confirmation, not loadability proof |
| `/dev` | `/dev/uipc` **251:207**, `/dev/stream` **249:7**, `/dev/stream2` **249:8**, `/dev/dmpgles2` **248:29**; **no `/dev/video*`**, no `/dev/usb/video`, no `/dev/usb/audio` | the UVC node must be created by `mknod 248:33` from our module; documented majors now confirmed |
| `/dev/usb/*` | `event 242:0`, `gadgetcore 242:1`, `otgcore 242:2`, `usbcore 242:3`, `scsi 242:4`, `massstorage 248:0`, `sicd_core 248:1`, `sicd_data 248:2`, `sicd_event 248:3`, `sen 248:4`, `ter 248:5`, `vspe 248:6`, `usb_extcmd 248:7`, `cur 248:8`, `std 248:9`, `kikilog 248:10`, `portmon 248:11`, `buspwric 248:12`, `buspwr 248:13`, `usbg_bspwr 248:14`, `swic 248:15`, `adb 248:16` | the gadget namespace in MSC; the video node 248:33 is a hole |
| PID 149 `im.elf` | 175 threads, Uid 0, all caps, VmSize 499,884 kB, VmRSS 52,048 kB, `TracerPid: 0` | freezing 174â€“175 threads (runner evidence E0194/E0205) remains valid |
| `im.elf` maps (selected) | `libosal_uipc.so` 0x0400f000, `libMWF.so` 0x040f7000, `libInfraUsbCmn.so` **0x04161000 (loaded)**, `libUsbControl.so` 0x04857000, `libObj.so` 0x05d18000, `libInfraRemote.so` 0x0d049000, `libInfraPtpControl.so` 0x0e844000, `libInfraPtpExtCmd.so` 0x0ecd6000, `libptp.so` 0x10a28000, `viewUnified2.so` **0x155e6000 (loaded)**; `/dev/dmpgles2` mapped at 0x0b5a2000 | `libInfraStreamingServer.so` is still absent; `libInfraUsbCmn` is present but is the a6400 build without streaming symbols |
| `im.elf` fds | `/dev/uipc` fd 4; `/dev/usb/gadgetcore` **fd 86**; `/dev/usb/event` 12; `/dev/usb/otgcore` 13; `/dev/usb/buspwr` 11; `/dev/stream` 9/10/40/41/42/63/64/79/84; `/dev/stream2` 23/36/62; `/dev/dmpgles2` 33; `/dev/mem` Ă—17; `/dev/nflasha4` 29; `/dev/nflasha23` 68; `/dev/mmca` 70/72; sockets 65-67 | gadgetcore fd is **86** this boot vs 82/85 in earlier evidence â†’ fd identity is **not stable across boots**; never hardcode it |
| `minfo` | `(27160) 68900000 128928` | OSAL pool/segment view; not yet decoded |

Consequence: the "dynamic discovery" rule in Â§6 is not style, it is required â€”
library bases, gadgetcore fd and every DMM address change between boots.

### 3.3 What the repository still does **not** know (must be probed, not assumed)

| # | Unknown | Why it blocks | How to settle (read-only unless flagged) |
| --- | --- | --- | --- |
| P1 | **Does a foreign `GET_JPEG` on `QUEUE_SCALAR 0x0167046a` return `ready=1` while the camera is in PC Remote and a PTP host is also streaming?** | Decides whether Track B's frame source exists | **ANSWERED — YES (E0349)**: `err=0, ready=1` in 3 of 7 windows while the host streamed 7,698 frames at 29.8 FPS; DMM units at `0x1408/0x140c/0x141c_0000`, no host-FPS impact, no leaked handles. Track B frame source is real; B3/B5 remain |
| P2 | Does a 30 Hz foreign `GET_JPEG` poll perturb or starve the simultaneous host PTP stream? | Two consumers on one 12-slot ring may duplicate or drain each other | same session: measure both frame rates + probe `sensor_frames` |
| P3 | Real accepted geometry and the selector-`0x50` width gate (320/640/1024 allowlist is proven only for selector `0x20`) | never hardcode 1280Ă—720; the first real frame decides | parse SOF of the first physically returned frame |
| P4 | What `0xF002` (`IOCTL_UVC_WAIT`) actually does: blocking read-completion vs log/status (`-0xF` decode) | the daemon's pacing depends on it | module build with `--trace-control`, log return + elapsed; **module session = write, needs authorization** |
| P5 | Why the transport build binds but produces no DirectShow samples | blocks Track B stage 2 | strongest candidate found offline: the shim matches **EP 0x81 only** (`uvc_composite_shim.c:779-806`) while the composite VS endpoint is **0x84** (`uvc_ptp_descriptors.c:56,67`), so the bridge returns 0 without invoking reference START (`uvc_callback_bridge.c:79-84`). Audit fixture + one physical session settles it |
| P6 | Receiver of the setting-service ObjMsg `category 0x3A4A, id 0x00010010` (future <10 ms control route) | only route that could beat PTP's 10â€“30 ms without UI key injection | static RE of `libmpr`/`libBizFw`/`libIMDB` + read-only `/proc/osal/uipc` before/after a host control |
| P7 | AF trigger / touch focus / REC semantics | **no** code, opcode or property exists in the repo; candidates `0xD2C1`/`0xD2C2` (keys 13/14) are weak inference | untried Sony opcodes `0x9203/0x9206/0x9208`; decode `actionControlDevice` tbh cases; UI key table |
| P8 | Android behaviour on the composite UVC child (does `uvcvideo`/Camera2 claim it? cost?) | decides whether Track B is usable from Android at all | on-device `dumpsys media.camera`, raw-descriptor claim attempt |
| P9 | Glass-to-glass latency of any path | no measurement exists anywhere in the repo | Track A bench: host timestamps per stage (request, data complete, decode done, present) |

`bk.elf` is **not** a property registry (it is an ARM32 CLI over `libbackup.so` that
writes `/setting/Backup.bin` on internal flash â€” a forbidden write path). There is no
RAM property registry on this camera. That closes one of the brief's assumptions.

---

## 4. Track A â€” verified PTP push pipeline (primary, ships now)

**Idea.** Keep the stock PC Remote session. Replace the current "request frame â†’
wait â†’ display â†’ request next" loop with a pipelined producer:

```
PTP writer thread                     PTP reader thread
-----------------                     -----------------
txn N   GetObject(0x1009,0xFFFFC002) â”€â”€â–ş bulk IN 0x81: 12B container hdr + data phase
txn N+1 GetObject(...)  (in flight)   â”€â”€â–ş reassemble complete JPEG (cap 512 KiB)
txn N+2 GetObject(...)  (in flight)   â”€â”€â–ş seq++, captureNs=now, drop-oldest hand-off
        â–˛                                      â”‚
        â””â”€â”€â”€â”€â”€â”€ control lane (priority): 0x9207 / 0x9209 / 0x9202 â”€â”€â”
```

Rules that keep `scalar` safe (from USB_GADGET.md Â§4.2):
1. one PTP session (`OpenSession 0x1002` once), one transaction-id counter;
2. all containers strictly serialised on bulk OUT 0x02; one reader on 0x81;
3. pipeline at the **transaction** level (2â€“3 `GetObject`s in flight), never two
   concurrent data phases of the same transaction;
4. controls are ordinary PTP operations issued **between** a frame's request and its
   data phase â€” never inside a live transaction;
5. shutdown: `CloseSession 0x1003`, `releaseInterface`, `close`; the camera is left in
   PC Remote (return to MSC from the camera menu, the proven-safe transition);
6. the 8-byte "no new frame" reply is **not** an error: retry immediately.

**Controls (verified semantics only).**
- Change a setting with the **signed notch** `0x9207` (effective, confirmed);
- read state with `0x9209` (one 1730-byte blob: code, datatype, access, value, options);
- `0x9205` absolute write is exposed but labelled *acknowledged, not applied* â€” the UI
  must not claim success without a readback;
- AF trigger / touch focus / REC are **not implemented** in this round: no evidence
  exists for their codes. They are listed as P7 with the untried `0x9203/0x9206/0x9208`
  as the first candidates and require explicit authorization before any physical test.

**Why this is a "push" transport even though the host asks.** The host keeps the pipe
full; the camera is always emitting data on the bulk pipe while a captured frame is
being decoded/displayed. Latency is bounded by the producer cadence, not by a
request/response round trip per displayed frame. That is the same wire behaviour as a
push stream, achieved with stock firmware semantics.

---

## 5. Track B â€” camera-side daemon + composite UVC push (secondary, gated)

### 5.1 What it is

One process, `camera-daemon/build/a6400-lived`, that merges the two physically run
halves (E0345/E0339):

```
open /tmp_bt/video (248:33)
 â””â”€ wait PC Remote identity (0x054c:0x0caa)          [INIT requires PC Remote, E0342]
 â””â”€ freeze PID 149 â†’ publish entry hook â†’ resume      [E0194/E0205 lifecycle]
 â””â”€ IOCTL_UVC_INIT (56-byte probe info)
 â””â”€ MOD_QUERY_DMA â†’ REG_BUF(total) â†’ ENABLE            [owned coherent window]
 â””â”€ OSAL /dev/uipc â†’ DMM rule 5 â†’ SET_PATH start       [rate/width/level from config]
 â””â”€ loop: GET_JPEG(0x0167046a) â†’ DMM OpenUnit {phys,size}
          â†’ bounded JPEG prefix + SOF dimension check
          â†’ depth-1 admit â†’ WAIT â†’ UPDATE {size, slot phys} â†’ release
          â†’ close+free DMM handles (close then free)
 â””â”€ control FIFO poll (session ops; camera settings route to host PTP)
 â””â”€ teardown: stop stream â†’ SET_PATH stop â†’ DMM rule 0 â†’ UVC STOP
              â†’ freeze â†’ retire entry hook â†’ resume â†’ receipt
```

The depth-1 policy is a design requirement, not an optimisation: a frame that arrives
while one is in flight is **dropped at the producer** (`drop-oldest`), because a queue
converts transport stalls into unbounded latency.

### 5.2 Frame source (the one honest risk)

`GET_JPEG` on `QUEUE_SCALAR 0x0167046a` is the same producer that feeds the verified
PTP liveview. The reply ABI (E0144:21, feeder:484-529):

| Field | Offset | Meaning |
| --- | --- | --- |
| `err` | reply payload +12 | 0 = accepted |
| `ready` | +16 | 0 = no frame |
| `handle1` | +20 (u16) | DMM unit holding the JPEG |
| `size_shift` | +22 (u16) | `size = size_shift << 7`, an **upper bound** (handler reports `(size+127)>>7`), so the real length is â‰¤127 bytes below it |
| `handle2` | +24 (u16) | second DMM unit, 0/0xffff when absent |

Then `DMM OpenUnit(handle1)` returns `{phys @ +16, size @ +20}`. Ownership transfers
to the caller; both units must be closed then freed (E0144:21). Nothing is hardcoded:
the reply queue id, the physical addresses, the accepted geometry and the stage epoch
are discovered per session (LIVEVIEW_DMA.md Â§4.1).

**P1 is now measured (E0349): the foreign poll works in PC Remote.** While a host stream held 29.8 FPS (7,698 frames), foreign `GET_JPEG` windows returned `ready=1` with 256 KiB DMM frame units (phys `0x1408/0x140c/0x141c_0000`) and no host-FPS impact; `im.elf` stayed at 175 threads and no DMM handle leaked. `handle2` was identified as the 0x274 DMM UnitType, not a handle (free returns `-EIO`). Remaining Track B blockers are the module-side B3/B5 defects, not the frame source.

### 5.3 Module gates (do not skip)

1. **Transport-enabled build.** `build_uvc_composite_module --shared-ptp-enumeration-candidate --composite-transport`
   (the E0345 build omitted this flag, hence `-95`). Builds already exist locally
   (`artifacts/native/uvc-ptp-module-e0348-transport` 72,860 B sha `6e794039â€¦`,
   `â€¦-e0349-transport-feed` 72,796 B sha `8d774c02â€¦`) but have no physical result and
   **no full audit**.
2. **Audit gap (B5).** `tools/research/audit_uvc_ptp_module.py:30` requires
   `manifest['start_probe_only']`, so transport builds cannot be audited by the current
   tool at all. A transport audit mode must be written before deployment under the
   project's own rules.
3. **START-bridge defect (B3).** `a6400_uvc_bulk_endpoint` matches only EP `0x81`
   (`uvc_composite_shim.c:779-806`) and the bridge returns 0 without invoking the
   reference START when no match (`uvc_callback_bridge.c:79-84`). The composite
   descriptor's VS endpoint is `0x84` (`uvc_ptp_descriptors.c:56,67`). This is the
   strongest candidate explanation for "binds but no samples" and must be fixed and
   re-audited before another physical session.
4. **Safety.** `INIT` only in PC Remote; never switch USB mode during an overlay
   (E0340 reboot); single fd; log to `/tmp_bt` and read receipts back **before** any
   mode change; battery pull is the only guaranteed recovery.

---

## 6. Control channel

| Route | Latency | Evidence | Used by |
| --- | --- | --- | --- |
| **PTP notch `0x9207` + readback `0x9209`** (host, same session as frames) | ~10â€“30 ms per control (PTP fetch measured 10.2 ms) | E0343, CONTROL_IPC.md | **Track A primary**; also the answer for every camera-setting opcode the daemon cannot apply |
| Setting-service ObjMsg `category 0x3A4A, id 0x00010010` (in-camera) | 50â€“200 Âµs [I] | CONTROL_IPC.md Â§3, static decode | future Track B route; receiver unidentified (P6) |
| UI key injection via `CtrlCode2InputKey` â†’ `SendEvtToInput` | 100â€“500 Âµs [I] | CONTROL_IPC.md Â§3 | exactly what stock PC Remote does; in-process, not reachable by an out-of-process daemon without an internal message |
| UVC XU / class requests on EP0 | ~0.1â€“1 ms [I] | handler exists (`core_cb_class` 0x17B0) but **no selector is advertised** (`bmControls = 0`) and no XU exists in any reference descriptor | rejected (Path A) for controls |

The daemon's control protocol (`camera-daemon/include/a6400_control.h`) is therefore
**route-aware, not aspirational**:

| Opcode class | Answer |
| --- | --- |
| PING / DAEMON_INFO / GET_CAPS / GET_STATE / GET_STATS / SET_LATENCY / DROP_STATS_RESET | handled locally |
| STREAM_START / STREAM_STOP / STREAM_CONFIG | handled locally, returns the session action to carry out |
| SET_ISO / SET_SHUTTER / SET_APERTURE / SET_EXPOSURE / SET_WB / AF_MODE / STEP | `ROUTE_PTP_HOST` â€” the host must use PTP `0x9207` (changes) / `0x9209` (readback); the daemon never claims it applied them |
| AF_TRIGGER / TOUCH_FOCUS | `CONTRACT_UNKNOWN` â€” no evidence exists |

Units mirror the PTP wire so the two routes are interchangeable: shutter =
`(numerator<<16)|denominator`, aperture = `f-number*100`, EV = millistop,
ISO value with `0xFFFFFF` = Auto; each carries `code` = firmware property code
(`0xD20D` shutter, `0x5007` aperture, `0x5010` EV, `0xD21E` ISO).

The hostâ†”daemon carrier is a POSIX FIFO in `/tmp_bt` (implemented, testable offline)
with an optional kernel "control ring" ioctl designed for the module bridge. The ring
does not exist in today's modules; the daemon detects `ENOTTY`, logs it and continues
with the FIFO only â€” it never pretends the ring works.

For Track A the hostâ†”camera control carrier is the PTP session itself (P1 in
USB_GADGET.md Â§5.1), which is the only control path physically verified concurrent
with streaming.

---

## 7. Latency model and the <35 ms question

Measured/known terms, provenance in USB_GADGET.md Â§5.4:

| Term | Value | Basis |
| --- | --- | --- |
| Frame quantisation (wait for the next complete frame) | 0â€“33.3 ms, avg â‰17 ms | 30 fps producer (descriptor interval 333,333; 24.6â€“30.8 fps measured) |
| Camera-side encode/copy | unknown, assumed 2â€“8 ms | no repo measurement; encoder limits explicitly not claimed (E0144:25) |
| Transport (140 KB over HS bulk) | 3â€“5 ms | 4.2 MB/s average need; bulk 512 B packets |
| Host JPEG decode | 3â€“8 ms | assumption for SD 8 Gen 3 / libjpeg-turbo (not measured in repo) |
| Host compose/present | 8â€“16 ms | 60 Hz display pipeline assumption |

**Sum â‰33â€“70 ms, typical â‰40â€“55 ms.** A 33.3 ms frame period leaves ~1.7 ms of a
35 ms budget for encode + USB + decode + present, which no transport change removes.
The honest commitment is **â‰¤1.5 frame periods, â‰45 ms typical, measured p95**, with
the host pipeline (pipelining, decode, present) as the only levers. If <35 ms is a hard
requirement, the next research question is **producer format** (is there a
non-frame-based liveview path on the CXD90045 SoC?), not USB.

---

## 8. Implementation map (delivered this round)

| Path | Content | Verification |
| --- | --- | --- |
| `ARCHITECTURE_UVC_MONITOR.md` | this document | synthesis of 4 recon reports + live MSC snapshot |
| `probes/` | `uvc_dma_probe.c` (ARMv7, read-only default, bounded), `build_probe.py` (WSL ARM build + host-check), `run_probe.sh`, `README.md`, report validator | offline build + host smoke + unit test |
| `camera-daemon/` | `include/` contracts, `src/` (osal, uvc, frame, runner, control, log, main), `build.sh`, `Makefile`, `test/` host tests, `tools/deploy.py`, `module/README.md` | WSL ARM build `-Werror`, host unit tests, repo suite |
| `android-client-ref/` | Gradle project, Kotlin PTP/UVC transports + app, native `cpp/` (libjpeg-turbo decode â†’ AHardwareBuffer/EGLImage â†’ GLES 3.2 SGSR-1.0-class pass), JNI contract, shader, static verifiers | host compile + assertions, shader validation, structure verifier; **no NDK/on-device build available** |

### 8.1 Probes (`probes/`)

Default mode is **purely observational**: `/proc`/`/sys` reads, `/dev` stat,
PID-149 maps/fds, kallsyms lookups, one-open OSAL `/proc/osal/uipc` snapshot,
bounded `/dev/mem` only with an explicit `--devmem PA LEN` (â‰¤4096). The decisive
extra mode `--poll-get-jpeg N` sends the exact 40-byte DataflowInfra GET_JPEG
transaction and records `err/ready/size_shift/handle*`; it requires
`--i-understand-foreign-get-jpeg`, prints a warning, and is the P1 experiment. Bulk
`/dev/mem` scans are **forbidden** â€” a 16 MiB sweep rebooted the camera (E0454).

### 8.2 Module build prerequisites for Track B

- build: `--shared-ptp-enumeration-candidate --composite-transport` (transport ioctls
  forwarded, `A6400_UVC_ENUMERATION_ONLY` off);
- fix B3 (accept the descriptor's real VS endpoint) and re-run the 118-check audit
  with a transport-aware variant (B5);
- deploy RAM-only from `/tmp_bt`, `mknod /tmp_bt/video c 248 33`;
- receipt: `p4_session_completed` markers + `module_list_restored:true`,
  `usbg_video_after:false`, `reboot:false`, monotonic `/proc/uptime`.

---

## 9. Verification plan

### 9.1 Offline (this round)

| Check | Command | Pass criterion |
| --- | --- | --- |
| Repository suite | `.\venv\Scripts\python.exe -m unittest discover -s tests -q` | 1181 OK (baseline confirmed at round start) |
| Probe build | `.\venv\Scripts\python.exe probes\build_probe.py` (+ `--host-check`) | ARM binary produced, manifest hash, host smoke report valid |
| Daemon build | `wsl â€¦ camera-daemon/build.sh` | ARM binary, `-Wall -Wextra -Werror` clean |
| Daemon host tests | `wsl â€¦ camera-daemon/test/run_host_tests.py` | all assertions pass |
| Android native | `bash android-client-ref/tests/host_compile.sh` | host compile clean, host assertions pass |
| Android structure | `.\venv\Scripts\python.exe android-client-ref\tools\verify_structure.py` | pass |
| Shader | `.\venv\Scripts\python.exe android-client-ref\tests\validate_shaders.py` | pass |

### 9.2 Physical (requires explicit authorization; not done this round)

1. **P1 decisive probe — DONE (E0349, success).** Recorded for reference: PC Remote session, host streams `GetObject 0xFFFFC002`,
   run `probes/uvc_dma_probe --poll-get-jpeg 100 --i-understand-foreign-get-jpeg`
   from `/tmp_bt`; record `ready/err/size` distribution + host fps before/during/after.
   Success: `ready=1` with plausible JPEG prefix and host fps unaffected.
   Failure: `ready=0` (Track B frame source does not exist; Track A remains the answer).
2. **Track A bench** â€” pipelined PTP client on the phone (or Windows) with per-stage
   timestamps; success â‰Ą25 fps for 60 s, control round-trip p95, no reboot.
3. **Track B stage 2 — ATTEMPTED (E0350), blocked at host pin connect.** The audited transport module loads and INIT produces host-visible composite `054C:0322` with MI_00/MI_01 and a DirectShow "ILCE-6400" device, but every capture fails with `Could not RenderStream to connect pins`; no UVC frame was obtained, and post-session MSC enumeration required a battery pull (receipts lost).
5. **Controls** â€” `0x9207` notch for ISO/shutter/aperture/EV with `0x9209` readback
   during streaming; then, if P6 is solved, the internal `0x3A4A` route.

Each session keeps: RAM-only writes, receipts read back before any mode change,
camera responsiveness check, and any reboot recorded as a failure (not as a limit).

---

## 10. Safety, recovery and receipts

- **Write scope:** `/tmp_bt` only. No flash (`nflasha*`), no `/system`, no `/setting`,
  no `/etc/ld.so.preload`, no SD writes, no bootloader.
- **No bulk `/dev/mem`:** a 16 MiB physical sweep rebooted the camera (E0454). Only
  bounded 4 KiB reads, `/proc`/`/sys`, and ptrace reads of the owning process are used.
- **No `/dev/stream` open:** an external open+mmap rebooted the camera (E0297). The
  safe display read is ptrace of `im.elf`'s own mapping (E0298).
- **No USB mode switch while any overlay is active** (E0340).
- **Recovery:** battery pull restores stock; after every session verify MSC reachable,
  `/proc/uptime` monotonic, 42 modules, `usbg_video` absent, `TracerPid: 0`.
- **Receipts:** the daemon writes a JSON receipt before returning in every path; the
  probe writes a JSON report; `/tmp_bt` is wiped by a reboot, so receipts are fetched
  to the host before any mode change.

---

## 11. Risks and open boundaries

| ID | Risk / boundary | Mitigation / next step |
| --- | --- | --- |
| P1 | ~~foreign GET_JPEG may see no frames in PC Remote~~ | **resolved: succeeds (E0349)**; remaining Track B blockers are B3 + B5 |
| P2 | foreign poll may steal/drain host PTP frames | measure both rates; if so, only host-side capture is safe |
| B3 | composite UVC binds but never streams (EP 0x81 vs 0x84 START mismatch) | fix bridge match to the descriptor's VS endpoint, re-audit, one physical session |
| T2 | Track B UVC stream untested at host pin level (DirectShow `RenderStream` fails after enumeration) | teardown **physically fixed**: unconfigure-first soft-disconnect returns MSC without a battery pull (E0353); START selector still the top suspect for RenderStream (E0351); next: Run B with host stream + ETW capture |
| B5 | transport modules are unauditable (`start_probe_only` requirement) | add transport audit mode before deployment |
| P4 | `0xF002` semantics conflict (blocking WAIT vs status) | instrumented module run, log-only |
| P6 | internal `0x3A4A` setting route receiver unknown | static RE + read-only `/proc/osal/uipc` diff around a host control |
| P7 | AF/touch/REC have no contract at all | untried Sony opcodes + UI-key table decode; explicit authorization |
| P8 | Android UVC child claimability unknown | on-device descriptor/claim test |
| â€” | `<35 ms` unreachable | re-scope to â‰¤1.5 frame periods; producer-format study if hard requirement |
| â€” | camera can hang/reboot on overlay teardown (E0296/E0277/E0340 history) | stage-gated teardown with attestation, receipts, battery-pull recovery |

---

## 12. Decision log (rejected alternatives, with reasons)

| Alternative | Why rejected |
| --- | --- |
| **LD_PRELOAD hook into `im.elf`** | `im.elf` is restored from hibernation and never exec'd, so `/etc/ld.so.preload` is not applied; the only preload path is a persistent flash write to `/etc` (forbidden). Emulator preload experiments failed and are excluded. |
| **`/dev/stream` direct reader for the display buffer** | an external O_RDONLY open+mmap rebooted the camera (E0297). Safe method is ptrace of the app's mapping, which is for observation, not for a transport. |
| **`/dev/stream2` as frame source** | it maps caller-supplied physical ranges and carries no format/frame semantics; not even mmap'd in the captured app state. |
| **Local PTP loopback inside the camera** | no local entry point: `libptp.so` is the gadget-side library; only `libInfraPtpControl` defines `PTPT_open_usb`; the liveview queue global is 0 outside PC Remote; the "ip" transport is undecoded. |
| **`bk.elf` property registry** | it is the backup CLI writing internal flash (`/setting/Backup.bin`), not a property registry; no RAM property registry exists. |
| **UVC XU for controls (Path A)** | no Extension Unit exists in any reference descriptor (`bmControls = 0`), no selector decoded, requires the ZV-E10 five-component overlay. |
| **Isochronous UVC video** | at 1024 B/microframe a 140 KB frame needs ~17 ms vs 3â€“5 ms for bulk; the reference descriptor itself selects bulk. Iso only wins for jitter/small frames. |
| **Hijacked PTP bulk endpoint push (Path C2)** | would require a kernel-side hijack of `usbg_stillimage`'s bulk path inside stock firmware â€” no evidence it is reachable, and it puts `scalar`'s USB state machine at risk. Host-driven push (C1) achieves the same outcome with stock semantics. |
| **Fixed DMA window (PA 0x20000000)** | not ownership; the historical fixed-window feeder is an explicit experimental mode and must not be used for new work. |

---

## 13. Bottom line

- **What ships and works on evidence:** Track A â€” a pipelined PTP liveview + control
  client on Android with hardware-appropriate decode (libjpeg-turbo), AHardwareBuffer/
  EGLImage upload and a GLES 3.2 SGSR-1.0-class spatial upscaler for the 2670Ă—1200
  display. Real sensor frames, real controls, zero camera-side code, RAM-only.
- **What is built and honestly unverified:** Track B â€” a camera-side daemon that can
  push MJPEG over composite UVC with a depth-1 queue, gated on one decisive probe
  (P1), one bridge defect (B3), one audit gap (B5) and explicit authorization.
- **What is not promised:** <35 ms glass-to-glass. The evidence supports â‰45 ms typical
  with a measured p95; anything better is a producer-format question.
