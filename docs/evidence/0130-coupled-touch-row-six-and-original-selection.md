# E0130: Coupled physical touch maps to row6

## Capture archived before analysis

Native read-only geometry observer PID1673 completed successfully. BOTH outputs
were preserved FIRST as `artifacts/hardware/native-touch-geometry-pid1673.log`
and `.bin`, receipt `.receipt.json`, then decoded to `.json` using the existing
version2 SLAY decoder. Exact file108068 bytes,61 records,107320 raw bytes;
SHA256 `b094f9fdae77df29baf0c61db329b7d0531b61f8b6a0726d7d4ac9f9987decd0`.

Held touch was detected at attempt194. During the SAME CPU freeze:

- framebuffer300,413; raw300,413; button state1;
- actual menu26fb3050, provider160f5cec, mode2, focus0, cached row0;
- UI TID380 TLS142e5920; captured pthread identity words confirm TID380/PID149;
- all176 CPU threads attached/resumed, result0,1228ms;
- COUPLED/BINARY/END all result0; no truncated output.

Helper terminated naturally; no hook or observer is armed. It made no application
calls, application RAM patches, SD writes or boot changes. The freeze did not
stop DMA. No cleanup/rearm was necessary on callback.

## Original geometry and selection controls

`python -m tools.research.coupled_touch_geometry_probe` checks captured touch,
menu type, singleton data, current model path, actual thread identity, and rejects
conflicting imports from older geometry helpers before original ARM execution.
Report: `artifacts/analysis/coupled-touch-geometry-e0130.json`.

The original six row world bounds are x17..623 and y126..174,176..224,226..274,
276..324,326..374,376..424. Original isHit returns exactly ONE hit for the actual
captured point300,413: **row6**. No scaling correction was introduced. This is
now a contemporaneous CPU-state point/menu control, unlike E0128's six releases
compared against older V12 geometry. Those older requested-vs-observed tap labels
remain unresolved historical observations, not a reason to invent scaling.

Current page160fbaa0 selected1. A SEPARATE original ARM
setItemSelectedByIndex(6) control on that captured model succeeds, changing1->6
and original selection flags in emulator copies. No model/cursor write was sent
to the camera. This is not yet an integrated physical selection/refresh result.

The newly captured512-byte ListTab vtable proves actual slot+1ac=15b92111,
matching the prior direct refresh-method control. This closes the old missing
virtual-slot evidence, without inventing table bytes.

## Original refresh dependency progress

`capture_refresh_icon_import` verifies viewUnified2 slot15f2bad4 using its actual
unique R_ARM_JUMP_SLOT22, original imported name `_ZN8GEN_Icon8setImageEjb`, and
defined libObj symbol. Runtime target60f96f1 and target code match the original
files. Artifact `native-refresh-icon-import-e0130.json` is used only by the
separate refresh control. No guessed external return was supplied.

Source-equal original helper6116a50 was added through the bounded read-only
dependency collector. Refresh replay reaches1419 instructions, stopping at
read709a38c/4, PC6116a5c. The helper reads a mutable global; nearby original setter
6116a68 writes it at6116a7a. A later USB read is NOT admitted as coherent MENU
state. Refresh has not returned; report `menu-refresh-coupled-state-probe.json`.
The actual global need not be emulated to call original refresh naturally on the
camera, but offline replay must keep this boundary honest.

## Remaining work and validation

No further physical gesture is currently requested. Do not repeat full resource
captures merely to restate this proven point-to-row mapping. Next build native
bindings on natural UI thread380, obtaining current ListTab/model through the
original registry; enforce popup/inactive-context exclusion and lifetime
invalidation, then invoke original selection/refresh. The limited adapter still
does not need full option/popup activation. Physical touch selection remains OFF.

599 unittest tests pass with normal host temp access. The new complete-capture
decoder, six original geometry/hit calls, original model selection and captured
thread/vtable checks pass. No physical visible-refresh success is claimed.
