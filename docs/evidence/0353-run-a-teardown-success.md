# E0353 — Run A physical success: unconfigure-first soft-disconnect returns the camera to Mass Storage without a battery pull

Date: 2026-11-11. **Physical**, user-authorized bounded Track B Run A (teardown test, no
DirectShow open). RAM-only module/daemon from `/tmp_bt`; no flash or internal-flash write.
Battery-pull recovery was available and was **not needed**. First successful physical run of
the camera-side daemon (compare E0350's two sessions that ended "Device unknown").

## Claim

1. With the **E0352 unconfigure-first soft-disconnect** module
   (`artifacts/native/uvc-transport-e0352-teardown/usbg_video_a6400_shared_candidate.ko`,
   74,276 B, SHA-256 `9da57a33…d687`) and the E0351 SD-logging daemon, one bounded session
   ran cleanly end to end:
   - `device_open` on a fresh boot: **OK** (DMA `dma_alloc_coherent` 262,144 B at
     `phys 0x00700000`; the first attempt on fragmented memory had failed `-ENOMEM`, E0350);
   - `IOCTL_UVC_INIT`, `MOD_QUERY_DMA`, `REG_BUF`, `ENABLE`: **rc 0**;
   - `DMM rule 5`, `SET_PATH reset/start (30 fps, 1280, level 5)`: **status 0**;
   - Windows enumerated the composite: **parent + MI_00 (PTP) + MI_01 (Camera)** for ~52 s;
   - 60 s streaming loop: **1,800 GET_JPEG polls, all `ready=0`** (expected — no host
     PTP/DirectShow consumer was opened; see finding 3);
   - teardown: `uvc_unreg rc=0`, **`uvc_stop verified=1 state=0,0,0,0`**, freeze 181 TIDs,
     **`hook_retire rc=0 completed=181 error=0`**, resume rc=0 → `exit status=clean code=0`.
2. The kernel trace is exactly the designed sequence (dmesg, captured before cleanup):
   ```
   [a6400_td] done phases=1ff failed=9 error=0 ep=1 list=00000000 id=0 count=1 desc=1
              root=69863bc0 retired=1 shadow=0 reconnect=1
   ```
   `phases=0x1ff` = all nine phases, `failed=9` = none, `reconnect=1` = the explicit
   `gcw_start`/EP0-arm/`pullup(1)` reconnect ran; `list=0` proves the endpoint list was
   released; `retired=1`/`shadow=0` prove the shadow drivers were unlinked.
3. **Mass Storage returned after a plain camera-menu switch, with no battery pull and no
   reboot** (`/proc/uptime` monotonic 96 → 614 s; `rmmod usbg_video` rc 0; 42-module
   baseline restored; camera responsive). This is the first Track B session that did not
   require a power cycle to recover — the E0350 non-recoverability is not reproduced when
   the E0352 teardown runs.
4. Crash-safe logging worked: the daemon mounted `/dev/mmca1` for the session
   (`sd_log_teardown mounted=1 receipt_written=1`, 63 SD lines), unmounted in teardown
   (`rc=0 still_mounted=0 errors=0`), and the final receipt records the observed values
   (`device_ok=1 verified=1 sentinel_ok=1 sync_mode=1 open_rc=0`). A later receipt rewrite
   reports `mounted=0` because the unmount already happened — by design.
5. Two defects found and one fixed:
   - **FIXED:** the receipt JSON ended with one extra `}` (two trailing top-level counters
     were closed by a doubly-counted brace), so strict JSON parsers rejected it. Format
     corrected in `camera-daemon/src/main.c`; rebuilt daemon
     **629,592 B, SHA-256 `95cc3cf3…9752a`** (host tests 399/399).
   - **Recorded (not a defect):** without a host liveview consumer the Scalar
     `GET_JPEG` poll returns `ready=0` for every poll (1,800/1,800). Frames appeared in P1
     (E0349) only while a host PTP `GetObject` stream was actively consuming liveview.
     Consequence for Run B: the UVC push path needs the host stream attempt (or a parallel
     PTP consumer) to make the producer emit frames.

Status: **physical success for teardown + daemon lifecycle.** No UVC frame, no
DirectShow open, no RenderStream retest in this run.

## Session receipts

| Item | Value |
| --- | --- |
| Module (deployed) | transport e0352-teardown, 74,276 B, `9da57a33…d687` |
| Daemon (deployed) | E0351 SD-log build, 629,592 B, `aa2c1cb0…0ec6` |
| Module audit | `offline_module_audit_passed`, transport, 117 checks / 8 skips / 0 failures |
| Host enumeration | `pnp_0322=3, MI_00=1, MI_01=1` from 18:02:00 to 18:02:52; after teardown the
  host showed **native `054C:0CAA`** (PC Remote), not "unknown device" |
| Daemon result | `status=clean, stage=complete, exit_code=0`; dmesg `[a6400_td] phases=1ff failed=9 … reconnect=1` |
| Camera after | uptime 96 → 614 s monotonic; `rmmod` rc 0; 42 modules; MSC responsive |
| Logs/artifacts | `artifacts/analysis/trackB-e0349/attempt-run-a/` (stdout, jsonl, receipt, dmesg, PnP monitors) |

Timing note: the first Run A arming used a 180 s PC-Remote wait and the operator's mode
switch happened after it expired, so the daemon exited cleanly at `stage=wait_pcremote`
(receipt preserved) **without INIT**; that run also recovered MSC without a battery pull
because no overlay had been installed. The successful run used a 900 s wait.

## Alternative explanations

- "MSC recovered because no UVC overlay was ever installed in this run": **not applicable to
  the successful run** — the composite enumerated (INIT committed the UVC descriptor set),
  and the camera still returned to MSC after the E0352 teardown. The first 180 s-timeout run
  is the no-overlay control, and it recovered too (as expected).
- The composite enumeration could in principle come from stale descriptors; the host PnP
  showed the correct MI_00/MI_01 split and disappeared exactly at teardown, and `[a6400_td]`
  reports `desc=1` (restored) and `reconnect=1`, which matches a real descriptor swap and
  reconnect rather than a stale table.
- The no-frame result is not a transport failure: `reg_buf_rc`/`enable_rc`/`set_path` were 0
  and `transport_errors=0`; the poll simply reported empty 1,800 times, consistent with the
  producer being demand-driven by the host liveview consumer (E0349).

## Confidence and limitations

- High confidence in: daemon lifecycle, stop attestation, teardown phases, SD mount/unmount
  behaviour, and battery-pull-free MSC recovery (all directly observed).
- Not covered by this run: UVC stream open / DirectShow RenderStream / any frame; host USB
  ETW capture; parallel PTP consumer; long soak; repeated sessions (single successful
  session). The SD file content was written but not read back from the card (camera MSC does
  not expose the SD as a Windows drive in this setup); mount/sentinel/unmount receipts are
  the evidence for durability.
- `hook_published` reads 0 in the final receipt because the publish state is cleared on
  retire; the publish itself succeeded (`init_attempted=1`, freeze 181 TIDs, INDENT/retire
  rc 0).

## Next experiment

1. **Run B** — same module/daemon (use the receipt-fixed daemon build `95cc3cf3…`), plus the
   host capture armed: open one `ffmpeg -f dshow -i video="ILCE-6400"` attempt while the
   session is active, with Windows USB ETW (`tools/research/renderstream_capture.ps1`,
   selected stack = ETW on this host) and, if needed, a parallel host PTP `GetObject` stream
   so the producer emits frames. Success criteria: `[a6400_td] phases=1ff … reconnect=1`
   again, MSC without battery pull, and either a captured UVC frame or an ETW trace showing
   exactly where the pin/probe/commit sequence fails.
2. **Run C** — mode switch to MSC with capture armed, only if Run B still leaves the host in
   "unknown device": the ETW trace decides between stale EP0-answered descriptors and a
   descriptor-content cause.
3. Read the SD `A6400LD.LOG`/`A6400RCPT.JSON` from the card on a future run (card reader)
   to confirm the durable copy's content.

## Safety statement

RAM-only: module/daemon/FIFO/logs in `/tmp_bt`; SD writes only through the gated
`--sd-log --sd-mount` path (`/dev/mmca1`, PC Remote only, `O_SYNC`, never internal flash);
no flash/SD-external/boot write, no `/dev/mem` scan, no external `/dev/stream` open. Owned
helpers removed after receipts were copied; camera left healthy in Mass Storage with the
42-module baseline.
