# E0266 — The app dispatcher issues the liveview GetObject itself

Date: 2026-11-09. Offline only.

## Consumer chain

- PTP queue `[this+0x1c]` → `OsalSyncRcvMsgCbUsb` → `MWF::ObjMsg` → `SndASyncMsgToMe` (0x9e74) → `osal_snd_msg([this+0x18], msg)` → sync queue `[this+0x18]`.
- The sync queue callback is `InfraRemoteUsb::OsalSyncRcvMsgCb` (`0xa888`, resolved from the GOT relocation at `0x19954`).

## Dispatcher behavior (`OsalSyncRcvMsgCb`, 0xa888)

The dispatcher handles message types and, for the liveview-related branch, builds a new `MWF::ObjMsg` (category `0x610c`, id `24`) and calls `InfraRemoteUsb::GetLiveViewStatus` (0xa2f6). That wrapper constructs an `MWF::ObjMsg` with category `0x610c`, **msg id `0x1009` (PTP GetObject)** and param key `0x1000` (the object handle), then returns it; the dispatcher sends it onward via `SndASyncMsgToMe` and checks the return (`-1` on failure).

So the app-side remote stack **itself** issues the liveview GetObject on the device-manager path, rather than the PTP interface handler directly returning a frame. The interface handler (E0260) queues the incoming request; the dispatcher turns it into the app's `GetObject(0x1009)` request message.

## Remaining gate

The dispatcher's head (0xa888–0xa9a0) selects the branch by message type/state; that selection, plus the device-manager side, is the remaining gate. A first attempt to disassemble `MrpwDeviceManager::GetLiveViewStatus` at nm value `0xcd69` landed inside `MakeSupportedCodeList`, so the symbol mapping needs correction before relying on that address.

## Next

- Disassemble `OsalSyncRcvMsgCb` from its entry and map the message-type table/state checks that lead to the liveview branch.
- Resolve `MrpwDeviceManager::GetLiveViewStatus` correctly (check symbol/Thumb boundaries near 0xcd68) and find the liveview state/frame source.
