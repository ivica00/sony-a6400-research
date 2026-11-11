# E0354 â€” Run B/B2: selector accepts 0x84 (no dep-flag rejection); RenderStream still fails; WPD cannot bind composite MI_00

Date: 2026-11-11. **Physical**, user-authorized Run B and Run B2 with the instrumented
transport module. RAM-only module/daemon. Run B ended cleanly (native 0CAA, MSC without a
battery pull); **Run B2, which added the real ffmpeg RenderStream attempt and USB ETW, ended
with "Device unknown" and required a battery pull, so its camera-side dmesg was lost.**
Host-side receipts (ffmpeg stderr, PnP monitors, 301,719,552-byte ETL) are preserved.

## Claim

1. **The live START endpoint selector accepts 0x84.** The instrumented module
   (`artifacts/native/uvc-transport-e0360-runb/usbg_video_a6400_shared_candidate.ko`,
   75,724 B, SHA-256 `f4253eddâ€¦ecec1`; transport audit `offline_module_audit_passed`,
   117 checks / 8 skips / 0 failures) logged during Run B:
   ```
   [a6400_sel] reject args dwc=689e5810 list=(null) count=0
   [a6400_sel] shared selector=00000000 count=0
   [a6400_sel] match wrapper=65c24220 raw=68a1c1c0 ep=0x84 flags=00000001 count=1
   [a6400_sel] shared selector=65c24220 count=1
   ```
   i.e. the first START dispatch had an empty list (rejected), the real one matched the
   **0x84** bulk-IN wrapper with the endpoint-enabled flag set (`flags&1`), ownership
   `wrapper+0x24 == raw`, and descriptor `7,5,0x84,bulk,512`. **The `*(dep+0x4C)&1`
   precondition did not reject the endpoint**, so relaxing that check (the conditional
   follow-up in the protocol) is **not warranted** and was not done.
2. **RenderStream still fails with the audited instrumented module.** Run B2 opened the
   composite successfully and ran one real `ffmpeg -f dshow -i video="ILCE-6400"` attempt
   while Windows USB ETW was armed; ffmpeg again reported
   `Could not RenderStream to connect pins` / `Error opening input: I/O error`. No UVC frame
   was produced. This reproduces E0350 with the fixed teardown module and proves the
   endpoint-selector hypothesis (E0351 verdict item b) was **not** the failure cause.
3. **The host PTP liveview consumer cannot bind the composite MI_00.** The PMCA WPD client
   (`GetObject 0xFFFFC002` loop) failed all 12 retries with
   `No Sony camera found on USB in PC Remote mode`, although Windows PnP showed the composite
   children (`Camera: ILCE-6400 [OK]`, `WPD: MTP USB Device [OK]`, `USB: USB Composite
   Device [OK]`). The protocol step "start host PTP stream first, confirm GET_JPEG ready=1"
   therefore could not be satisfied over the WPD path in composite mode.
   Boundary: **`composite_mi00_wpd_not_enumerable_by_pmca`**.
4. **Host-side USB trace was captured**: `artifacts/analysis/trackB-e0349/attempt-run-b2/`
   holds `usb-capture.etl` (301,719,552 B, retained) plus the orchestration log and ffmpeg
   stderr. The derived `tracerpt` XML (2,685,365,196 B) was produced for inspection and then
   removed to keep the workspace manageable; regenerate with
   `tracerpt usb-capture.etl -of XML -o usb-capture.xml`. Analysis of the trace is pending
   (offline); the ETL is the primary evidence for the EP0/probe/commit question.
5. **Regression vs Run A:** with the host ffmpeg attempt present, the camera again did not
   return to Mass Storage (Windows "Device unknown") and a battery pull was required.
   Boundary: **`runb_renderstream_attempt_breaks_msc_recovery`**. Cause unknown because the
   battery pull wiped `/tmp_bt` (dmesg `[a6400_td]` and selector logs for B2 are lost; the
   teardown may have run after the host failure, or the USB stack state after a failed pin
   connect is what breaks enumeration). E0353's clean teardown (without a host attempt) is
   not invalidated, but it is not sufficient in this scenario.

Status: physical, partially diagnostic. No UVC frame; EP0/pin root cause still open.

## Method

- Instrumentation (E0354/Run B): `printk`-only reason logging added to
  `tools/native_camera/uvc_ptp_adapter.c` (`a6400_uvc_ptp_select_endpoint`) and
  `uvc_ptp_session.c` (`shared_endpoint`); no control-flow or return-value change. Module
  rebuilt with `--shared-ptp-enumeration-candidate --composite-transport` and audited
  (`117 checks, 8 documented skips, 0 failures`).
- Run B: fresh boot (uptime 52 s) â†’ push/readback (75,724 B `f4253eddâ€¦`) â†’ `insmod`
  (43 modules) â†’ `mknod` â†’ daemon armed (`--arm-transport --wait-pcremote --timeout 900
  --duration 120 --sd-log --sd-mount`); operator switched to PC Remote; composite
  enumerated; the host PTP attempt failed (step 3); no ffmpeg was launched (host
  orchestration bug, logged); session ended at 120 s â†’ clean `exit code=0`,
  `[a6400_td] phases=1ff failed=9 error=0 â€¦ reconnect=1`, native 0CAA, MSC without battery
  pull. dmesg selector trace from this run is preserved (claim 1).
- Run B2: same on a fresh boot with duration 150 s; ETW started with
  `logman create trace a6400usb -pf usb-providers.txt -o usb-capture.etl -ets` (rc 0);
  PTP client retried 12Ă—; one real ffmpeg attempt (30 s timeout); session later ended and
  the host showed "Device unknown" â†’ battery pull. Host logs/ETL preserved.

## Alternative explanations

- The selector trace's first `count=0` call is gadgetcore probing the function START with an
  empty endpoint list; it is not an error path that affects the real configuration START
  (which succeeded 0.3 ms later). Not the RenderStream cause.
- RenderStream may fail in the **reference class handler's probe/commit reply** (a 26-byte
  template copied for a 34-byte request â€” E0351 found this defect but E0143 tolerated it) or
  in the host's `SET_INTERFACE`/pipe start, or because the camera side never fills frames
  (no liveview consumer). The ETW trace is the discriminator.
- The battery pull after B2 may be caused by the failed DirectShow pin connection leaving
  Windows/USB stack state (the camera returned `0CAA` cleanly in Run B where no ffmpeg was
  attempted), not by the E0352 teardown sequence itself. Needs one more targeted run after
  the EP0 cause is understood.
- WPD enumeration failure may be a PMCA/filter or timing issue rather than the device:
  `MtpContext.listDevices(0x054C)` uses `PortableDeviceManager::GetDevices` and
  `parseDeviceId` is case-insensitive, so the composite child's ID format should match;
  a direct WPD device-ID dump during a session is the next check.

## Confidence and limitations

- High: selector accepted 0x84 (instrumented kernel log); ffmpeg RenderStream failed
  identically with the audited module; WPD could not bind MI_00 (12 retries); ETW captured.
- Unknown: exact EP0/pin failure point and why B2 lost MSC; B2 camera logs were lost by the
  battery pull. ETW analysis not yet performed (2.7 GB XML).
- The ETW file is large because all three USB providers ran at default verbosity for the
  whole session; a targeted retry should use a shorter window and/or filtered providers.

## Next experiment

1. **Analyze the retained ETW offline** (no camera): convert to CSV/evtx in slices, keep only
   `USBPORT` URB/control-transfer events in the Â±30 s around the ffmpeg attempt, and decode
   `SET_CUR`/`GET_CUR` (wValue 0x0100/0x0200), `SET_INTERFACE`, and endpoint-0 stalls. This
   answers EP0 vs pipe without a new session.
2. **Instrument the bridge/reference START and CLASS paths** (`printk` of bridge invoke
   result, reference START entry/return, class-handler return) in the same instrumented
   build, so a future run reports whether reference START was entered/returned and whether
   probe/commit returned 0/1/-12.
3. **WPD diagnostic during a session**: a host script that dumps all WPD device IDs
   (`PortableDeviceManager::GetDevices`, unfiltered) and attempts `Open` on the MI_00 child;
   determines whether a host PTP consumer is possible in composite mode or a different
   transport (Android raw PTP) is required.
4. **Isolate the battery-pull regression**: one bounded session with ffmpeg attempt but the
   E0352 teardown immediately after (short duration), with SD logging armed; compare
   `[a6400_td]` and host observability. Do not retry indefinitely without the SD/SD-card
   read-back working, since MSC loss destroys /tmp_bt receipts.
5. Only after (1)-(3): decide whether to keep the reference class handler (E0143-tolerated)
   or to change the descriptor/pipe path, then re-test.

## Safety statement

RAM-only module/daemon; SD writes only through the gated `--sd-log --sd-mount` path
(`/dev/mmca1`, PC Remote only, `O_SYNC`). No flash/internal-flash writes, no `/dev/mem`
scan, no external `/dev/stream` open. One battery pull was used as recovery; the camera is
back in Mass Storage with the 42-module baseline. Owned `/tmp_bt` helpers were removed where
the camera remained reachable; B2's helpers were wiped by the power cycle.
