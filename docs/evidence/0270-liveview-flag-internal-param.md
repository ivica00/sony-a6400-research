# E0270 — The liveview flag is set from an internal message param 0x1300; final-test readiness

Date: 2026-11-09. Offline only.

## `actionSetLiveViewStatus` body (0xb466)

```
push {r7,lr}
mov  r1, #0x1300
ldr  r0, [r2, #0x30]      ; r2 = third arg (message/param object)
bl   MWF::ObjMsg::GetParam(0x1300)
bl   ParamStd<unsigned char>::GetValue()
ldmia sp!, {r7,lr}
b    MrpwDeviceManager::SetLiveViewStatus(byte)
```

The FSM action reads the byte parameter **0x1300** from the message object and passes it to `SetLiveViewStatus`, which stores it in `s_LiveViewStatus`.

## What this means

- The liveview status byte is set from an **app-internal MWF message parameter `0x1300`**, not from a direct USB/PTP request. The host's USB PTP interface has no direct way to write it.
- `GetLiveViewStatus` (event 17, E0266/E0269) only **reads** the byte and reports it to the remote stack.
- The ordinary PC Remote control sets the byte (camera in its liveview state) and frames flow; in the composite session the byte is presumably 0, so the app reports no liveview and serves no frame.

## Final-test readiness

The remaining question can now be answered with a bounded physical session, no new code required:

1. **Behavioral gate check**: in a composite session (e0251 + fixed probe), observe the camera LCD: if it shows liveview but PTP frames are absent, the flag is set and the gate is downstream (Mtp/GetObject response); if the LCD is not in liveview, the camera never entered the state that sets the flag.
2. **Optional read**: `s_LiveViewStatus` is at `libInfraRemote` base + `0x20508`; if an alternate read-only channel (camera telnet/network) is available in PC Remote, read the byte to confirm 0/1. USB debugger is unavailable in PC Remote (Windows WPD owns the device).
3. **Teardown**: the 4/4 clean teardown path is established; the test must still take the receipt.

## Limits

No physical session in this step; the flag value in PC Remote is inferred, not read. The app-internal 0x1300 message source is camera-side; the host cannot set it via USB.

## Next

Approve a bounded physical composite session with the fixed probe and the LCD observation; optionally add a read-only network/telnet check for the flag. That is the final test boundary for this offline arc.
