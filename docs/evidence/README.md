# Platform evidence

One record per hardware or software claim. Records are dated and are **not** rewritten
when a later result supersedes them: the newer record says what changed.

Current consolidated state: [README research status](../../README.md) and
[UVC/PTP status and next steps](../UVC_PTP_STATUS.md) (through **E0354**, 2026-11-11).

## Latest records

| ID | Date | Claim |
| --- | --- | --- |
| [E0354](0354-run-b-selector-accepts-084-renderstream-fails.md) | 2026-11-11 | Physical Run B/B2: the 0x84 selector accepts; RenderStream still fails; WPD cannot bind composite MI_00 |
| [E0353](0353-run-a-teardown-success.md) | 2026-11-11 | Physical Run A: unconfigure-first soft disconnect returns the camera to Mass Storage without a battery pull |
| [E0352](0352-offline-teardown-soft-disconnect-fix.md) | 2026-11-11 | Teardown root cause and clean unconfigure-first soft-disconnect sequencer (offline, Unicorn 12/12) |
| [E0351](0351-offline-renderstream-verdict-and-crash-safe-logging.md) | 2026-11-11 | RenderStream failure ranked to START endpoint selection; crash-safe SD logging and host ETW ready |
| [E0350](0350-trackb-transport-enumerates-but-renderstream-fails.md) | 2026-11-11 | Track B composite enumerates (parent + PTP + Camera) but DirectShow cannot connect the UVC pins |
| [E0349](0349-p1-foreign-get-jpeg-succeeds-in-pc-remote.md) | 2026-11-11 | P1: a foreign `GET_JPEG` sees liveview DMM frames at 29.8 FPS in PC Remote |
| [E0348](0348-uvc-monitor-architecture-probe-and-reference-client.md) | 2026-11-11 | UVC-monitor architecture, read-only MSC snapshot, safe DMA probe and reference client |
| [E0332](0332-sync-callback-delivery-first-invocation.md) | 2026-11-11 | Opt-in kernel-to-user sync callback delivery runs the original h4109 callback to completion |

## Record format

```text
ID:
Claim:
Status: unknown | inferred | verified
Firmware hash / camera configuration:
Source: artifact hash + file/offset/symbol, or recorded physical observation
Method:
Observation:
Alternative explanations:
Confidence and limitations:
Dependent implementation/scenarios:
Next experiment:
```

Do not promote source comments or log strings to verified hardware facts. Keep dumps and
large/private observations outside versioned documentation.
