# E0245 — P0 idle isolation, trials 1–3: three ordinary PC Remote switches without a reboot

Date: 2026-11-09. Physical: three bounded idle collector sessions. No `/dev/mem`, no SD write, no UVC activation. Trial 1 was recorded in E0244; this record covers the set.

## Results

| Trial | Stage uptime (s) | After uptime (s) | Delta (s) | Receipt | Reboot | Modules | usbg_video |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 4074.54 | 4374.99 | +300.45 | `IDLE_SESSION_COMPLETE result=1` | no | 42 | absent |
| 2 | 4407.73 | 4757.57 | +349.84 | `IDLE_SESSION_COMPLETE result=1` | no | 42 | absent |
| 3 | 4767.91 | 5039.72 | +271.81 | `IDLE_SESSION_COMPLETE result=1` | no | 42 | absent |

Same collector: `native_monitor_collector.elf` SHA-256 `b0402893382ce4763db2eff357d12d9eb04f375845213cec67d63e15425382af` (24,652 B), mode `--sd-idle`, PID 824/951/1078, owned `/tmp_bt` files only. Each trial: read-only preflight in MSC, stage and `MONITOR_COLLECTOR READY`, user switched to PC Remote and back to MSC, receipt recovered, postflight uptime/modules, checked cleanup (`receipt_recovered_idle_success_cleaned`). No SD journal was written; the authorized `A:/A6400J.DAT` remains absent.

## Interpretation

In three controlled ordinary switches, a staged idle collector with no `/dev/mem` access completed its bounded session and the camera did not reboot: uptime was monotonic, the module count stayed at 42 and `usbg_video` remained absent. This isolates the *idle* case: the mere presence of a staged process plus a PC Remote switch did not reproduce the earlier self-reboot.

The earlier reboot (probe-5, same build, 30 s settle, no command published) used a probe mode that opens `/dev/mem`/FSYS tables; the idle mode deliberately does not. The difference is therefore a concrete lead — the `/dev/mem`/FSYS path or a rarer condition — not a proven cause. Three trials do not prove the collector can never trigger the fault.

## Limits

Bounded idle sessions only; no journal write, UVC, module load or PTP transaction. The user performed each mode switch. Uptime deltas include the collector's wait window (~300 s) and are consistent with no reboot, not a timing measurement.

## Next

P4: a reviewed enumeration/teardown rerun with the existing enumeration-only candidate, pre/post MSC receipts, a watchdog and recoverable stage observation. The journal physical write remains a separate step.
