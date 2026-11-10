# E0267 — Dispatcher switch: the liveview case is one of several remote-command handlers

Date: 2026-11-09. Offline only.

## Dispatcher entry

`InfraRemoteUsb::OsalSyncRcvMsgCb` (0xa888) dispatches the message command through a **jump table**: the bytes at 0xa8b0–0xa8e0 are table entries (objdump renders them as stray `lsls`/`movs` instructions), and the entry computes the case from the message command. The visible cases:

| Case | Code | Action |
| --- | --- | --- |
| A | 0xa904 | `ObjMsg(0x610c, 2)` then `GetCameraStatusAndMakeMsg` (0x9280) |
| B | 0xa922 | `actionControlDevice(msg, ctx)` (0x932c) |
| C | 0xa93a | reads params `0x1000`/`0x1001`; if the first equals `0xd232`, sends events to input; else `actionParsePtpCd2RemoteAppId` |
| D | 0xa9d0 | `ObjMsg(0x610c, 6)` then `GetPredictedMaxFileSize` (0x95d0) |
| E | 0xa9ee | `ObjMsg(0x610c, 24)` then `GetLiveViewStatus` (0xa2f6) |

The liveview action is case E. The table index/base and the command values that map to each case are in the entry code around 0xa888–0xa8be.

## Interpretation

The PTP liveview request posted by `libInfraPtpControl` is turned into an `MWF::ObjMsg` and dispatched by command through this table. Only the case that reaches E issues the app's `GetObject(0x1009)` request. Whether the composite configuration changes which case is taken (or drops the message) is the remaining question; the table mapping and the device-manager side are still open.

## Next

- Decode the dispatcher entry/table: command base, table entries, and the case that leads to E.
- Resolve `MrpwDeviceManager::GetLiveViewStatus` correctly (the nm address 0xcd69 falls in `MakeSupportedCodeList`; check the symbol table/Thumb boundary).
