# E0273 — F8-1: liveview handle translation 0xFFFFC002 → 0xFFFFC001 and the data flag

Date: 2026-11-09. Offline only.

## App request

`InfraRemoteUsb::GetLiveViewStatus` (0xa2f6) builds an `MWF::ObjMsg` with category `0x610c`, **msg id `0x1009` (GetObject)**, and params:

- `0x1000` = **`1`** (object selector; set at `0xa31a`),
- `0x1300` = the byte value taken from the incoming message (liveview status value).

So the app's own GetObject request is `(GetObject, selector=1, status)`, not the host's raw handle.

## PC Remote MTP operation

- `MtpRemotePcOperation::GetObject_cmd` (0xf800) compares the requested handle with **`0xFFFFC001`** (literal at `0xf83c/0xf840`): if it matches, it sets a global byte flag to `1` (and stores `0` to a second global); otherwise it returns the `0x2009` status path.
- `MtpRemotePcOperation::GetObject_dat` (0xf848) reads that global byte; when set, it clears it and calls `MrpwObjectManager::GetCurrentFileSize` (0x90ec), then builds the data response.
- `MrpwObjectManager::GetObject` (0xe5ec) has a matching global-byte branch at `0xe64e`: nonzero → the memcpy/size path (0xe838–0xe86a); zero → the DMA file-transfer path (`FileTransferDMAC330`).

## Chain

```
host GetObject 0xFFFFC002
  -> libInfraPtpControl handler 0x369c -> app queue
  -> InfraRemoteUsb::OsalSyncRcvMsgCb (event 17)
  -> InfraRemoteUsb::GetLiveViewStatus (0xa2f6): ObjMsg GetObject(0x1009), param 0x1000=1, 0x1300=status
  -> device manager / MTP operation: handle 0xFFFFC001
  -> GetObject_cmd sets liveview data flag
  -> GetObject_dat + GetCurrentFileSize / MrpwObjectManager -> liveview frame
```

The host handle and the internal object are different: `0xFFFFC002` (SDIO liveview object) is translated to the app-internal `0xFFFFC001` selector. The LCD liveview being on shows the frame source exists; the failure under the composite must be in the translation/dispatch/device-manager link.

## Next

- Trace where the ObjMsg `GetObject(0x1009, selector=1)` is delivered (UFW/Mtp server dispatch) and whether the composite configuration changes that delivery (remote-app activation / MTP operation registration).
- F8-2 teardown race and F8-4 runbook remain.
