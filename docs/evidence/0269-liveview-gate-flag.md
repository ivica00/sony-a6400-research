# E0269 — The liveview gate is `MrpwDeviceManager::s_LiveViewStatus`

Date: 2026-11-09. Offline only.

## The flag

- `MrpwDeviceManager::GetLiveViewStatus` (0xcd68, 24 bytes) loads a GOT-indirected pointer and executes `ldrb r0,[r3,#0]`. The GOT slot `0x198e0` resolves by `.rel.dyn` to **`_ZN17MrpwDeviceManager16s_LiveViewStatusE`** (1 byte, value 0x20508). So the status getter returns that byte.
- `MrpwDeviceManager::SetLiveViewStatus(unsigned char)` (0xccf4, 116 bytes) is the writer: it takes a lock (`UFW::Sem`), stores the byte/state, walks a 0x668-stride table for code `0xd221` and writes the status into the matching entry, then unlocks.
- `InfraRemoteUsb::actionSetLiveViewStatus(UFW::Fsm*, int, void*)` (0xb466) is the FSM action that tail-calls `SetLiveViewStatus`.

## Why it matters

`InfraRemoteUsb::GetLiveViewStatus` (E0266) reports the `s_LiveViewStatus` byte to the dispatcher. If the byte is 0, the remote stack reports "no liveview" and the app-side frame path does not serve a frame. In the no-module control the byte is set (the camera is in its ordinary PC Remote liveview state) and frames flow; in the composite session it is presumably never set, because the app does not enter that liveview state.

## Next

- Find the events/callers that trigger `actionSetLiveViewStatus` (FSM action table or remote command) and what condition sets `s_LiveViewStatus` in ordinary PC Remote.
- Compare that trigger/state with the composite configuration: does the camera enter PC Remote liveview only for the single-function PTP descriptor/device class, or does it require an explicit host start command?
