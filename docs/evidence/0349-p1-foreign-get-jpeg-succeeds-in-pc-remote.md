# E0349 — P1 SUCCESS: foreign GET_JPEG sees liveview frames in PC Remote without starving the PTP stream

Date: 2026-11-11. **Physical** user-authorized experiment (explicit go-ahead for the P1
foreign `GET_JPEG` probe during an active PC Remote `GetObject 0xFFFFC002` session).
RAM-only: no flash/SD/boot writes. No module loaded. Helpers in `/tmp_bt`, removed after.
The camera was switched MSC → PC Remote → MSC by the operator; uptime stayed monotonic.

## Claim

1. A **foreign userspace process on the camera** (not `im.elf`, not the host) can issue the
   Scalar DataflowInfra `GET_JPEG` transaction on queue `0x0167046a` while the camera is in
   PC Remote **and a host PTP liveview stream is running**, and it receives `err=0`,
   `ready=1` with real frame handles and a DMM frame unit — **P1 succeeds**.
2. The host stream is **not starved** in this configuration: 7,698 consecutive frames at
   **29.8 FPS** (1024×680, 123–130 KB each) across ~4 minutes that contained at least four
   foreign probe windows.
3. `im.elf` (PID 149) stays healthy: 175 threads, `TracerPid: 0`, camera responsive, no
   reboot (`/proc/uptime` 5,833 → 6,713 s monotonic), and **no probe DMM handle leaked**
   into `/proc/udm/dmm_units`.
4. New decode: the second value the original GET_JPEG handler returns (`handle2`) was
   **628 = 0x274**, and freeing it returns `-EIO(-5)`. 0x274 is the JPEG-frame DMM
   **UnitType** (E0144/E0146), not a unit handle — the earlier "additional 0x274 field"
   warning is now explained. The probe's `cleanup_complete=false` is therefore a
   conservative label, not a leak.

Status: **verified** (physical). This supersedes the P1 "unmeasured" boundary in E0348.

## Method

Pre-flight (MSC, read-only via `tools/camera_debugger.py`): `/proc/uptime`, 42 modules,
PID 149 (175 threads, `TracerPid: 0`). Then:

1. Probe pushed to `/tmp_bt/uvc_dma_probe` with readback hash verification
   (`48144 B`, SHA-256 `b32987b9…8eb66e`, equals `probes/build/uvc_dma_probe_arm`).
2. A launcher script was started in the background **in Mass Storage** (the debugger is
   unavailable in PC Remote: `MTP SendCommand failed`), running ten probe windows 45 s
   apart, each `/tmp_bt/uvc_dma_probe --poll-get-jpeg 100
   --i-understand-foreign-get-jpeg --out /tmp_bt/p1r_<n>.json`, stopping early on the
   first `"ready": 1`.
3. A first attempt (`p1_report_a/b.json`) ran before the host stream was up — it produced
   the mode-comparison baseline described below.
4. The operator switched the camera to PC Remote. A continuous host stream then ran:
   `python -m tools.research.ptp_liveview_client --source ptp --no-auto-deploy
   --frames 40000 --save-frame artifacts/analysis/p1/p1r-ptp-frame.jpg -u`
   (WPD, `GetObject 0x1009 [0xFFFFC002]`). FPS was sampled every 40 s.
5. After the probe windows the host stream was stopped, the operator returned the camera
   to Mass Storage, and the probe reports/logs were read back to
   `artifacts/analysis/p1/run2/` (7 windows) and `artifacts/analysis/p1/first-attempt/`.

## Observation

**Host stream during the probe windows** (`artifacts/analysis/p1/p1r-fps-samples.log`):

| host time | cumulative frames | last measured FPS |
| --- | --- | --- |
| 16:53:44 | 1,536 | 29.3 |
| 16:54:24 | 2,737 | 29.6 |
| 16:55:04 | 3,937 | 29.7 |
| 16:55:44 | 5,136 | 29.7 |
| 16:56:24 | 6,337 | 29.8 |
| 16:57:04 | 7,538 | 29.8 |

Final: **7,698 frames**, last line `Frame #7698: 1024x680 px | 128725 bytes |
29.8 FPS`. No gap, no reconnect, no error lines. Host frame saved: 82,637 B JPEG
(`artifacts/analysis/p1/p1r-ptp-frame.jpg`).

**Foreign probe windows** (camera uptime, 100 polls each unless stopped):

| report | uptime s | polls | err values | ready | frame metadata | exit |
| --- | --- | --- | --- | --- | --- | --- |
| `p1r_0` | 6380.35 | 65 | `{0:65}` | **1** | handle1=9089, handle2=628, size_shift=987 → ≤126,336 B, DMM open=0 phys=`0x141c0000` size=262,144, close=0, free(h1)=0, free(h2)=-5 | 2 |
| `p1r_1` | 6426.00 | 100 | `{0:100}` | 0 | none | 0 |
| `p1r_2` | 6471.73 | 100 | `{0:100}` | 0 | none | 0 |
| `p1r_3` | 6517.47 | 1 | `{0:1}` | **1** | handle1=28417, handle2=628, size_shift=1067 → ≤136,576 B, phys=`0x14080000`, free(h1)=0, free(h2)=-5 | 2 |
| `p1r_4` | 6563.17 | 1 | `{0:1}` | **1** | handle1=3029, handle2=628, size_shift=1021 → ≤130,688 B, phys=`0x140c0000`, free(h1)=0, free(h2)=-5 | 2 |
| `p1r_5` | 6608.84 | 100 | `{0:100}` | 0 | none | 0 |
| `p1r_6` | 6654.61 | 100 | `{4:100}` | 0 | none | 0 |

Interpretation of the columns:
- Windows 0, 3, 4 ran while the camera was in PC Remote and the host was streaming →
  **foreign frames visible**. Windows 1, 2, 5 show `err=0, ready=0` (accepted transaction,
  no frame at that instant) — the ring can be empty between host consumption and the next
  produced frame, which is expected.
- Window 6 ran **after the camera had returned to Mass Storage** and shows the `err=4`
  mode-dependent rejection seen in the first attempt (`p1_report_a/b.json`: 100× `err=4`),
  confirming `err=4` is the non-PC-Remote state, not a transport failure.
- `size_upper_bound` values (126–137 KB) bracket the host-observed frame sizes
  (123–130 KB), consistent with the same liveview MJPEG producer.
- Frame physical addresses `0x14080000` / `0x140c0000` / `0x141c0000`, 256 KiB DMM units —
  inside the `0x14000000` JPEG frame region recorded in E0148, and disjoint from the
  probe's own memory.

**Stability checks:** PID 149 after return: `State: S`, `TracerPid: 0`, `Threads: 175`,
`VmRSS: 52,832 kB` (baseline 52,048 kB). `/proc/udm/dmm_units` read: 49 entries; handles
9089 (`0x2381`), 28417 (`0x6f01`), 3029 (`0x0bd5`) and `0x274` are **absent** — the probe's
close/free path did not leak the frame unit. `/proc/uptime` monotonic; no reboot; camera
responsive in MSC after the session.

## Alternative explanations

- **Could the frames have been generated by the probe rather than by the liveview stream?**
  The probe sends no `SET_PATH` and performs no allocation; frames appeared only while the
  camera was in PC Remote with the host liveview active. The size/unit/address match the
  liveview producer. So the frames are the liveview producer's, not probe-created.
- **Could the foreign poll have stolen host frames?** Host throughput stayed at 29.3–29.8
  FPS over the whole window with no dips; both consumers received frames. Whether they are
  the *same* ring slot/epoch cannot be decided from handles alone (see limits).
- **`err=4` in MSC** is a mode-dependent rejection, not evidence of failure: the same probe
  got `ready=1` in PC Remote.

## Confidence and limitations

- High confidence that P1 succeeds (four independent ready=1 events across three windows,
  with DMM metadata and zero host-FPS impact).
- Medium confidence on frame identity/duplication: the probe does not copy JPEG bytes
  (no `/dev/mem` build), so there is **no SOI/EOI validation of the foreign frame**; only
  the size upper bound and DMM unit metadata tie it to the liveview producer.
- The `handle2=628=0x274` / free `-EIO` observation is a strong decode but should be
  confirmed by reading the original handler's free path (the feeder also frees handle2 and
  would get the same error).
- Session length was ~4 minutes and 7 probe windows; this is not a soak test, and one
  window (`p1r_0`) was stopped early by the probe's deliberate ambiguity exit after the
  first ready frame.
- The debugger is unavailable in PC Remote, so probe scheduling was blind (scheduled before
  the switch). The first attempt missed the overlap for this reason and is retained.

## Dependent implementation / scenarios

- **Track B is now unblocked on its frame source**: `camera-daemon/` can use the same
  foreign `GET_JPEG` transaction (already implemented in `camera-daemon/src/frame_hook.c`)
  and copy the returned DMM unit into the UVC transport slot.
- Next blockers are the two already-identified module defects: B3 (START bridge matches
  EP 0x81 while the composite descriptor's VS endpoint is 0x84) and B5 (transport builds
  cannot pass `audit_uvc_ptp_module.py`), then one bounded physical Track B session.

## Next experiment

1. Offline: apply B3 fix, add B5 transport audit mode, rebuild and audit the transport
   module (`artifacts/native/uvc-transport-e0349-fixed`).
2. Physical RAM-only Track B stage 2/3: `insmod` audited module from `/tmp_bt`, `mknod`,
   run `camera-daemon --arm-transport --wait-pcremote --duration N`, operator switches to
   PC Remote, host captures a UVC frame; teardown to receipt, `rmmod` only with verified
   stop, verify 42 modules / no `usbg_video` / monotonic uptime.
3. Optional P1 hardening: a probe build with `PROBE_ENABLE_DEVMEM=1` to copy ≤64 bytes of
   the foreign frame and verify SOI/SOF without a bulk scan; and a 30-minute soak with
   periodic windows to measure any long-term DMM/ring drift.

## Safety statement

The only camera-side writes were RAM files in `/tmp_bt` and the operator's two USB-mode
switches. No module, no flash/SD write, no `/dev/mem` access (the probe binary was built
with `PROBE_ENABLE_DEVMEM=0`), no bulk scan, no external `/dev/stream` open. Owned helpers
were removed afterwards; camera left healthy in Mass Storage.
