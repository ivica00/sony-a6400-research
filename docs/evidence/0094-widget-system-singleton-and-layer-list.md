# E0094 — Native WidgetSystem singleton and layer-list observations

Date: 2026-11-05. Physical ILCE-6400 FW 2.00, im.elf PID 149.

## Returned physical-test trace

`artifacts/hardware/native-menu-probe-pid1946-after-test.log` contains 22 attempted
V2 samples, zero catalog candidates, and termination with `probe_error result=-13`.
This is the sampler's range-count/size/total guard, not an observed input error.
Coverage is incomplete; this trace does not establish whether MENU received touch.

## Direct original contracts

`artifacts/hardware/native-widget-contract-20261105-175547/manifest.json` records
live/file-equal exported functions and referenced instruction windows. No remote
function calls or application writes were performed.

* WidgetSystem::sys_getInstance at 0x06308d30 resolves GOT 0x07089e54 -> storage
  0x07108058 -> live instance 0x000956f0.
* getMousePosInFramebuffer reads halfwords at instance + 0x4a8/0x4aa,
  with record stride 0x14 selected by the device argument.
* getMouseState reads instance + 0x4b0, stride 0x14, tests the requested bit,
  returns 6 for clear and 5 for set. No higher semantic meaning assigned.
* getGestureAnalyzer returns instance + 0x20.
* getLayer's original search starts at instance + 0x484. Verified list helpers
  read first node at container + 0xc, sentinel container + 0x10, element pointer
  at node + 0, owner at +4, next at +0xc.

`artifacts/hardware/native-layer-snapshot-20261105-175535.json` follows these
contracts with owner/cycle/count guards and reads eight live layers, all with
vtable 0x07062c48. This snapshot is not atomic: only the process leader is stopped
for individual debugger memory operations. Four raw mouse records currently have
0x7fff coordinate halfwords and zero state words while USB is connected. This is
not evidence for disconnected MENU behavior.

## Next observer and current build limitation

`devcrashday_a6400/native_mouse_probe.c` prepares a finite read-only observer:
1800 samples at 100ms intervals, 80-byte records, fixed instance identity guard,
exclusive lock, detach after each read, changes and heartbeat timestamps.
No code patches or input injection. It remains **unbuilt and undeployed**.

The ARM build attempt failed before compilation: WSL reported
`HCS/ERROR_NO_SYSTEM_RESOURCES` creating its VM. A subsequent upload attempt
failed locally because the executable did not exist; no observer was installed
or started. Existing USB debugger remains usable. Do not request another physical
test until the new observer has actually been built and verified running.

Touch MENU remains unimplemented/unverified. The two earlier guarded RAM gates
alone have not produced the requested behavior. No SD writes in this work.
