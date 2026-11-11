# E0350 — Track B physical attempt: transport module enumerates, but DirectShow cannot connect the UVC pins

Date: 2026-11-11. **Physical**, user-authorized Track B test after P1 succeeded (E0349).
RAM-only module/daemon from `/tmp_bt`; no flash/SD/boot writes. The camera required a
battery pull after each of the two completed sessions (known post-session USB
enumeration boundary), so the camera-side daemon receipts for those sessions were lost.
Host-side evidence was captured before each recovery.

## Claim

1. The audited transport-enabled composite module loads on the a6400
   (`insmod` rc 0; `/proc/modules` 43 entries; `usbg_video 56456 … Live 0x5f5a2000`)
   and its session INIT drives the USB transition: Windows enumerated
   **3 devices — composite parent + MI_00 (PTP/WPD) + MI_01 (Camera/UVC)** — and
   DirectShow listed **"ILCE-6400" (video)** while the daemon session was active.
2. Despite that, the host could **not open the UVC stream**: every capture attempt failed
   with `Could not RenderStream to connect pins` → `Error opening input: I/O error`.
   **No UVC frame was captured** (`trackb-uvc-frame.jpg` absent; `capture_attempts` log).
   Boundary: **`trackb_directshow_pin_connect_unproven`**.
3. The camera-side daemon did open the video node and obtain its DMA window on a
   **fresh boot** (the same open fails `-ENOMEM` on fragmented memory), but its log and
   receipt could not be read back: after teardown Windows reported the camera as
   "Device unknown" in Mass Storage, a USB replug did not recover it, and a battery pull
   (which wipes `/tmp_bt`) was required — twice. Boundary:
   **`post_session_msc_enumeration_powercycle`**.
4. Therefore Track B status at this checkpoint: **transport/descriptors/registry path
   reaches host enumeration; UVC stream open is still unproven; camera-side receipts are
   unreachable with the current USB-only log channel.** Track A remains the verified
   path (E0348/E0349).

Status: physical, partially verified. No frames, no streaming, no sensor claim.

## Artifacts

| Item | Value |
| --- | --- |
| Module | `artifacts/native/uvc-transport-e0349-fixed/usbg_video_a6400_shared_candidate.ko`, 71,960 B, SHA-256 `a1d959752d1ec665834d6f17a58e6137821bab75c9362cca75b2887c087b6692` |
| Module audit | `artifacts/analysis/uvc-transport-e0349-fixed-audit/manifest.json`, `status=offline_module_audit_passed`, mode `transport`, 117 checks, 8 documented skips, 0 failures |
| B3 selector proof | `artifacts/analysis/uvc-transport-e0349-fixed-audit/b3-selector-unicorn.json` (15/15 Unicorn cases) |
| Daemon | `camera-daemon/build/a6400-lived`, 628,000 B, SHA-256 `009f2e213d63cf42783169fd88a16fcf434501c575c5bf503b0ea7e556326238` |
| Attempt 1 receipt (open failed) | `artifacts/analysis/trackB-e0349/attempt1-open-enomem/` |
| Attempt 2/3 host logs | `artifacts/analysis/trackB-e0349/attempt2-host-capture.log`, `…/attempt3/` (`capture-attempts.log`, `dshow-list-options.log`) |

## Method and observations

**Attempt 1 (uptime ~7,468 s, loaded in MSC).** Push + readback hash verified; module
loaded (43 modules); `mknod /tmp_bt/video c 248 33`; daemon started armed
(`--arm-transport --wait-pcremote --duration 60`). The daemon failed immediately:
```
device_open path=/tmp_bt/video node_created=0
stage_failed stage=device_open code=2 reason=open /tmp_bt/video failed rc=-12
```
The module's 256 KiB `dma_alloc_coherent` window could not be allocated on the
fragmented post-boot memory (same class as E0339's second-open `-ENOMEM`; E0144 shows
256 KiB coherent succeeds three times **only on fresh memory**). Receipt preserved in
`attempt1-open-enomem/`. Module `rmmod` clean (rc 0, 42 modules restored).

**Attempt 2 (fresh boot, uptime 64 s).** Same push/load/daemon; the daemon opened the
node successfully and logged `usb_identity vid=0x054c pid=0x0ca8` (MSC state), i.e. it
was waiting for PC Remote. Operator switched to PC Remote. Host observed (5 s cadence):
`pnp_0322=3 uvc=1 ptp=1` from 16:16:02 to ~16:17:18, DirectShow `"ILCE-6400"` present;
every `ffmpeg -f dshow` capture attempt failed; after ~70 s all three devices disappeared
(session teardown). Windows then reported the camera as unknown in MSC; USB replug did
not recover it; battery pull required. `/tmp_bt` (daemon log/receipt) lost.

**Attempt 3 (fresh boot, uptime 65 s, duration 45 s, `--stats-interval 5`).** Same
behaviour with explicit capture diagnostics at 17:25:20:
`pnp0322=3 uvc=1 ptp=1`, DirectShow `"ILCE-6400"` present, then
```
[in#0] Could not RenderStream to connect pins
[in#0] Error opening input: I/O error
```
No frame file produced; session ended ~45 s later; battery pull required again;
receipt lost.

**P1 context (same day, E0349):** a foreign `GET_JPEG` on `0x0167046a` **does** return
live frames in PC Remote while the host PTP stream runs at 29.8 FPS — so the camera-side
frame source exists. The missing piece is now narrowly the UVC stream path: START /
PROBE-COMMIT / class handling in the transport build, or the host pin negotiation.

## Alternative explanations

- The `Could not RenderStream to connect pins` failure is **not** a host codec problem:
  `ffmpeg -list_devices` sees the camera as a video device; the failure is at pin/stream
  negotiation, matching the earlier E0345/E0347 transport-build symptom.
- The daemon may have failed before feeding frames (freeze/INIT/SET_PATH) and the host
  failure would be secondary. Without the camera-side log this cannot be separated; the
  enumeration of MI_00/MI_01 proves INIT/descriptor commit succeeded, but not that the
  feeder loop or START ran.
- The post-session USB failure is a known family (E0290/E0296/E0340: teardown/USB
  enumeration after liveview/UVC transitions); it is not evidence that the module
  corrupted flash (no flash writes; module RAM-only; battery pull restores 42 modules).

## Confidence and limitations

- High confidence: module loads; transport-build INIT produces host-visible composite
  `054C:0322` with both children and a DirectShow video device; DirectShow pin connect
  fails; no UVC frame; two battery pulls required.
- Low confidence on Track B root cause: no camera log for attempts 2/3. The daemon and
  module printk diagnostics were written but died with the RAM. The B3 callback fix is
  **not** the live START path in the shared build (`a6400_uvc_ptp_select_endpoint` is),
  so this test does not validate that callback's dispatch.
- The daemon has still never completed a documented session (never reached teardown with
  readable receipt). Its evidence value remains the open-failure receipt (attempt 1).

## Next experiment (in order)

1. **Persistent camera-side log channel** so a Track B session can be diagnosed without
   MSC recovery: options are a vfat-mounted SD target (user SD-write authorization
   exists for homebrew payloads; verify device association first) or a bounded
   kernel-visible channel readable after recovery. Without this, further sessions stay
   blind and destroy their own evidence.
2. **Host USB trace during the session** (USBPcap/ETW): capture the UVC
   probe/commit/SET_INTERFACE exchange on EP0 and the VS endpoint state; this can prove
   whether the camera stalls the class request or never starts the pipe, entirely from
   the host side.
3. **Offline Unicorn evaluation of `a6400_uvc_ptp_select_endpoint`** against the live
   gadget/dwc values (`gadget+0x20==3`, `dwc+0xf4` dep flags, VS endpoint descriptor) to
   determine whether the shared START path can ever return the wrapper with the shipped
   descriptor; if it cannot, that is the next module-side fix.
4. **Teardown/MSC enumeration fix**: investigate the unconfigure-first/pullup sequence
   (E0250/E0251/E0252) so a session can end with the camera returning to MSC without a
   battery pull; this also unblocks receipt retrieval.
5. Only after (1)-(3): another bounded Track B attempt with a feeder and a host frame
   check; Track A remains the shipping path meanwhile.

## Safety statement

Module and daemon were RAM-only (`/tmp_bt`): `insmod`/`mknod`/`rmmod`, no flash or SD
write, no `/dev/mem` scan, no external `/dev/stream` open, no preload/boot change. Two
battery pulls were the documented recovery and restored the 42-module MSC baseline
(final check: uptime 63.8 s, 42 modules, `usbg_video` absent, camera responsive).
