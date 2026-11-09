# E0234 — Ordinary MSC→PC Remote→MSC fixed IFSYS query answered

Date: 2026-11-09. Physical observation with the E0233 prefix-acknowledgement collector. No UVC activation, no module/hook installation, no SD journal write, no filesystem write command.

## Inputs and tool identity

- Collector build `artifacts/native/monitor-sd-collector-e0233`: `native_monitor_collector.elf` 20,324 bytes, SHA-256 `8b4777efd6da10754bfde145384f5eb173bcb55962e585974859d4265cde4ec1`, equal to `manifest.json`.
- Run directory `artifacts/hardware/uvc-monitor-sd-query-e0234-run`; staged by `tools.research.run_native_monitor_sd_query stage`, recovered by `collect`, cleared by `cleanup`.
- Uploaded to fresh own RAM paths `/tmp_bt/mon_sd_20261109_170746.elf|.log|.log.receipt|.stdout`, push read-back byte-equal; READY at host 17:07:46 (PID 1167, `fixed_sd_info`). Preflight `/proc/149/status` TracerPid 0 and `/proc/modules` without `usbg_video`.
- The user performed one ordinary Mass Storage → PC Remote → Mass Storage cycle; the collector ran with admission window 180 s nominal and reply window 60 s. Host collection was at 17:10:41; the user reported the camera back in MSC before that.

## Observation (recovered receipt 25,350 bytes / stdout 6,078 bytes)

1. Launch state: 14,154 native output bytes at read cursor 17,066 of 31,220 preserved, fsync/read-back verified, then `ACK_OK` (17,066→31,220); input 10/10.
2. Forty-seven consecutive one-per-second probes were rejected with `sd_guard_stage=2`, output empty and input 10/10. The stage-2 check covers the drive table / `"/dev/mmca"` identity; the exact failing sub-check is not identified, and the receipt has no per-attempt timestamps. Their bounded cadence (≈48–49 s after launch, ending ≈17:08:35) is the last quiet interval before the switch.
3. Native output then appeared while the PC Remote application came up: 35 bytes (31,220→31,255), 3,842 bytes (31,255→3,369, wrapped), 6,213 bytes (3,369→9,582) and 292 bytes (9,582→9,874). Each snapshot was preserved and acknowledged with `--ack-preserved-prefix`; all four returned `ACK_OK`, including the wrapped and appended cases.
4. Two transient `ACK_REJECTED sd_guard_stage=0` lines occurred between the 3,842-byte ack and the next successful snapshot. The action's reject label is shared by snapshot and probe admission, so the exact outer branch is not identified; the next second's snapshot succeeded and the run continued.
5. Output empty at 9,874/9,874: `PROBE_PUBLISHED bytes=21 input_end=31 command=IFSYS_GETDRIVEINFO_A`.
6. Reply: one `QUERY_CHUNK bytes=303 input=31/31 output=9874/10177`, preserved and `ACK_OK`; then empty output at endpoint 31 with input 31/31. The 303 bytes are `IFSYS getdriveinfo A` echo plus:
   `result = 0x00000000`, `status = 0x0000`, `type = 0x8401`, `blockSize = 4194304`, `speedClass = 0x9000`,
   `id = 19 01 F9 30 05 01 50 42 47 38 44 …`, `transferRate = 80`, `filesystemType = 0x0003`, prompt `MWF>`.
7. `query_result=1`; receipt `SAMPLES_COMPLETE captured=0 query=1 result=1`; stdout `MONITOR_COLLECTOR RECEIPT_VERIFIED bytes=25350 captured=0 query_result=1 RAM_only`. The collector copied the held inode to a fresh receipt path with read-back. This is one read-only IFSYS information reply, not a filesystem write or journal result.

## Recovery and cleanup

- `collect`: both camera files re-read without truncation; completion and copy markers present; post-state TracerPid 0 and no `usbg_video`; modules file byte-equal to before. Status file differs only in process memory counters (VmSize/VmHWM/VmRSS/VmData), as expected.
- `cleanup`: helper PID 1167 `EXITED`; remote receipt/stdout re-read byte-equal to the host copies; exactly the four owned `/tmp_bt/mon_sd_20261109_170746.*` paths removed and their absence verified. A subsequent read-only `ls -la /tmp_bt` shows only pre-existing system entries, no `mon_sd_*`. Final TracerPid 0, no `usbg_video`.

## Inference and limits

- The query was answered by the live native command path with a genuine parser-style reply and `MWF>` prompt. This proves one bounded read-only IFSYS request/reply, and physically confirms the E0233 prefix acknowledgement on appended and wrapped producer data.
- Mode at publication: the receipt has no timestamps and the host did not record the switch instant (no matching Kernel-PnP events). The bounded one-per-second loop makes a pre-switch idle interval of ≈48–49 s (47 rejections) and then the output burst, prefix acks and publication; a return to MSC before publication would have required the loop to idle ~160 rejections instead of 47. Publication is therefore inferred to be in PC Remote between the switch and the 17:10:41 collection, not after the return to MSC. The exact switch time and the mode at the exact publication instant are not directly proven.
- Prefix acknowledgement remains a bounded SPSC admission check, not a multi-consumer CAS/ABA proof. `captured=0` is expected for query mode. Elapsed time alone was not used as success; the receipt/reply were.
- No SD journal write was attempted: E0219 authorization remains unused and still requires verified ownership, non-overwrite creation, bounded write, flush/read-back and restart survival.

## Next boundary

The approved small SD diagnostic journal remains unwritten. UVC/sensor/PTP-control integration is still unfinished and untouched by this test. If mode-at-publication must be proven directly rather than inferred, a future collector version should record per-event monotonic timestamps and correlate them to host time.
