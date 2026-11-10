# E0268 — Dispatcher event table decoded: liveview is event 17

Date: 2026-11-09. Offline only.

## Entry

`InfraRemoteUsb::OsalSyncRcvMsgCb` (0xa888):

1. Calls `Msg2InfraRemoteEvent(msg, ctx)` (0x9660) and gets an event code in `r0`.
2. `cmp r0, #24`; if above, exits.
3. `tbh [pc, r0, lsl #1]` — a 25-entry halfword table at **0xa8b6**.

## Table (event → target)

| Event | Entry | Target | Action |
| --- | --- | --- | --- |
| 0 | 0x1d | 0xa8f0 | build `ObjMsg(0x610c, r9)` |
| 1 | 0x19 | 0xa8e8 | clear byte / build `ObjMsg` |
| 2 | 0x27 | 0xa904 | `GetCameraStatusAndMakeMsg` |
| 3 | 0x1d | 0xa8f0 | as 0 |
| 6 | 0x8d | 0xa9d0 | `GetPredictedMaxFileSize` |
| 7 | 0xb5 | 0xaa20 | `ReqFileTransfer` |
| 13 | 0x36 | 0xa922 | `actionControlDevice` |
| 14 | 0x42 | 0xa93a | param `0x1000`/`0x1001` check |
| 15 | 0x1d | 0xa8f0 | as 0 |
| 16 | 0xbb | 0xaa2c | `SetCapturedInfo` |
| **17** | **0x9c** | **0xa9ee** | **`GetLiveViewStatus`** (case E) |
| 4,5,8–12,18–24 | 0xcc | 0xaa4e | exit/default |

## Meaning

The PTP liveview request is converted by `Msg2InfraRemoteEvent` to **event 17**, which is the `GetLiveViewStatus` case. The dispatcher mapping is therefore explicit: event 17 → liveview. The remaining questions are (a) how `Msg2InfraRemoteEvent` produces event 17 from the 8-byte PTP message and whether any state affects it, and (b) the device-manager side that actually produces the frame.

## Next

- Disassemble `Msg2InfraRemoteEvent` (0x9660) and trace event 17 creation from the PTP message.
- Fix the `MrpwDeviceManager::GetLiveViewStatus` symbol mapping and inspect the frame path.
