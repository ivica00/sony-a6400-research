# E0143: Physical UVC test-pattern transport verified at 720p / 29.96 FPS

Date: 2026-11-07. Camera writes were restricted to `/tmp_bt`; no SD/NAND/backup/preload/boot configuration writes or Windows driver changes were issued. This milestone verifies transport of a static JPEG, not live sensor acquisition.

## Recovery and endpoint isolation

Mass Storage debugger PID 703 was available after physical restart. Preserved the 5,153-byte current dmesg and state under `artifacts/hardware/uvc-e0143-recovery`. The old feeder log and module were absent; the E0142 stalled cycle's camera logs were not recovered.

Built a `--start-probe-only` composite that validates the endpoint without calling reference START. Physical log proved:

* `gc=68aa4ec0`, `dwc=689e5810`, raw Bulk IN endpoint `68a1c340` from `dwc+0xdc`.
* Kernel wrapper `69783260`, wrapper+0x24 equal to the raw endpoint.
* Enabled endpoint descriptor `6051b1bc`, address 0x81, type BULK.
* The 300-tick diagnostic restored Mass Storage and returned STOP/unregistration results 0.

Next executed the unmodified reference START body through a logging wrapper with frame submissions disabled. START entered with speed=0/count=1 and returned. The complete no-submit lifecycle restored Mass Storage. Thus endpoint validation and original START can complete on the camera; the earlier stall is not an inevitable START failure.

## Disjoint JPEG source and completion ordering

The inherited test feeder supplied JPEG source PA `0x20000000`, also the internal driver's first destination slot. Original `.text+0xf3c..0xf4c` writes a 12-byte UVC payload header at that destination before DMA copies the source JPEG. This aliases and corrupts the JPEG source. `tools.research.uvc_buffer_alias_probe` executes original header stores at `.text+0xf40..0xf50`: the old source loses `ffd8`; a disjoint source retains it. The probe does not execute DMA.

Moved the static 29,452-byte JPEG to PA `0x20120000`, offset `0x120000` within the existing 1,325,056-byte experimental RAM window. Both destination payload ranges, including headers, are below this source; compile-time bounds verify the source fits. The fixed-address allocator shim remains an experimental RAM-window substitution, not a verified native allocation/ownership service.

The feeder now calls `WaitVideoReadCmp` (`0xf002`) before `UpdateVideoBufEvt` (`0x4008f003`), matching retained reference `VideoEsManager::set_video_data_to_driver` ordering. These changes were applied together; no claim is made that source aliasing alone explains every E0142 stall.

## Physical decoded frame and measured cadence

FFmpeg DirectShow received and decoded a Baseline MJPEG 1280x720 frame from `USB Streaming Device`, exited 0 and wrote `disjoint-frame.jpg`. No `0x8007001F`/RenderStream error occurred in this successful capture.

A 120-frame OpenCV/DirectShow arrival measurement initially yielded **25.0057 FPS**. The relative 33 ms nanosleep accumulated work and scheduler rounding. Replaced it with ARM Linux CLOCK_MONOTONIC `clock_gettime`/absolute `clock_nanosleep` deadlines spaced 33,333,333 ns apart.

The subsequent 180-frame capture yielded **29.9592 FPS**, calculated from arrival intervals after excluding the first ten warmup frames: `(180-11)/(timestamp[179]-timestamp[10])`. Decoded shape was 720x1280x3. Raw relative arrival times are retained in `paced-measurement.json`. This is a short test-pattern transport measurement, not a long-duration stability or sensor-frame uniqueness test.

The paced session accepted 249 submissions over its 450-tick run; host capture closed after 180 decoded frames. The feeder restored Mass Storage with buffer-unregistration/STOP results 0 and debugger PID 703 responsive. Counts outside the host measurement window are not FPS measurements.

## Monitor integration

The local monitor initially failed before opening UVC because its unconditional PTP/WPD import attempted COM wrapper generation in a protected Python directory. Moved WPD imports inside the PTP class so UVC uses DirectShow without loading PTP dependencies.

Started `tools.research.ptp_liveview_client --source uvc --camera-index 0 --serve --port 8380` for a bounded smoke test. `/frame.jpg` returned a valid 35,448-byte 1280x720 JPEG; `/api/status` and the HTML page returned successfully. Saved `cinema-http-frame.jpg` and `cinema-http-verification.json`. The page contains the existing EASU/RCAS code; browser GPU rendering was not exercised. Existing camera telemetry/default GPU strings in the page are placeholders, not camera measurements. The server was stopped after the test; port 8380 no longer served the test page.

## Artifacts and validation

* Final composite: `artifacts/native/uvc-composite-e0143-final/usbg_video_a6400.ko`, 68,540 bytes, SHA-256 `a5e188076461e254fae1feb7ac1da76da439fe00bcd4c811255f08a225843ef8`. Byte-identical to the deployed `uvc-disjoint-source-e0143` module. Original executable prefixes unchanged; all 42 imports matched retained native symbols.
* Paced feeder: `artifacts/native/uvc-disjoint-source-e0143/uvc_stream_feeder_30fps`, 3,916 bytes, SHA-256 `70da5b8e10e455ea76d77a537d1c239ae909f30b8582bf6d705a05804d35aa22`. Built with `-DUVC_TEST_TICKS=450`; deployed to `/tmp_bt/uvc_stream_feeder` with verified readback.
* 53 compiled ARM bridge/original dispatcher controls pass in `artifacts/analysis/uvc-bridge-controls-e0143`. Callback recorder limitations remain explicit.
* All **599 emulator tests pass**, 16.036 seconds, after the monitor import change. Log: `artifacts/hardware/uvc-e0143-recovery/emulator-tests-with-monitor.log`.
* Full per-cycle dmesg files and feeder logs were read back using chunked reads rather than treating a truncated exec response as a complete log.

## Current boundary

Physical Bulk IN transport, decoded MJPEG and approximately 30 FPS delivery of a static test pattern are verified. Camera is back in Mass Storage, no UVC session active, debugger PID 703 responsive; the experimental module remains loaded in RAM. No battery action is required now.

The next required implementation is authentic native JPEG production and buffer ownership: resolve/validate the a6400 queue 0x01670464 receiver, DMM handle lifecycle and native image configuration before feeding actual camera frames. Do not describe this static test-pattern milestone as sensor LiveView, a completed CinemaHUD camera port, a booted emulator or general firmware compatibility.
