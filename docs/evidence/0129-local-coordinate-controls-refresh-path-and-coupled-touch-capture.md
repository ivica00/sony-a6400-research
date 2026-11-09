# E0129: Coordinate controls, separate refresh path, coupled capture pending

## Original coordinate controls

`tools.research.menu_local_mouse_probe` executes original calcLocalMousePos
`0x63051f0` with its hidden output ABI (r0 output, r1 widget, r2 mouse), then
original calcWorldPos `0x63052e8`. All72 world/local roundtrips reproduce the
explicit framebuffer points exactly on retained V12 geometry. Inputs include
six actual E0128 points and six explicit row-center controls.

Source-verified original constructor/transform code runs, with only narrowly
allowed geometry-cache writes in emulator copies. Global singleton GOT slot
`0x7089e54 -> 0x7108058 -> 0x956f0` was read live. The original ELF contains an
unrelocated value at that GOT slot; do not claim the runtime pointer equals raw
file bytes. Coordinate values are explicit offline fixtures, not a new physical
capture or a live geometry claim.

Row1 maps physical point293,163 to local276,37. Feeding that local result into
Widget::isHit is a separate negative/control experiment and misses row1; feeding
the original point hits it. Do not chain calcLocalMousePos directly into this
isHit method. These controls do not prove the complete native routing path,
clipping, current visibility, or arbitrary transforms. Report:
`artifacts/analysis/menu-local-mouse-e0129.json`.

## Separate original refresh control

`menu_activation_snapshot_probe --refresh-only --main-thread-control
--active-state artifacts/hardware/native-layout-resource-snapshot-pid1175.json`
directly invokes original ListTab method15b92111; it does NOT call activation.
The retained vtable prefix does not cover virtual slot+1ac, so the method control
does not fabricate a virtual-slot read. The pending coupled capture saves512
bytes of actual ListTab vtable to cover that slot.

`capture_menu_activation_dependencies --refresh-only` maintains a separate
dependency set and only adds source-equal code/read-only original module bytes.
It stops at mutable data. Original UTF16/data/code additions were preserved in
`native-menu-refresh-dependencies-pid1175.json`, separately from activation.

Live libObj method table70546e8/64 is in a writable mapping. The separate
`capture_refresh_method_table` tool verifies ALL16 words against original ELF
REL entries: R_ARM_RELATIVE or R_ARM_ABS32 with locally defined function symbols.
No guessed function address or return is supplied. Artifact
`native-refresh-method-table-e0129.json` explicitly says mapping_immutable:false.

Refresh replay reaches1402 instructions and stops before missing data15f2bad4
at PC15738910. Report `menu-refresh-coupled-state-probe.json`. Refresh has NOT
returned; no visible feedback or physical selection is claimed. Offline TID149
context remains an explicit control, distinct from observed physical TID380.

## PENDING physical coupled geometry capture

New `tools/native_camera/native_touch_geometry.c` reuses bounded V12 registry,
model and freeze primitives. It makes NO application calls or RAM patches. It
waits at most1800x500ms for mouse0 raw coordinates without32767 sentinels and
pressed button0, then freezes all PID149 CPU threads and rechecks that condition.
It locates the menu in the native tree and captures full ListTab, registry/widget
geometry, selected model path, all four mouse records, ListTab512-byte vtable,
six row vtable prefixes and actual TID380 TLS in the SAME CPU freeze. DMA is not
stopped. This is diagnostic data, not proof of popup exclusion or menu generation.

One successful binary snapshot uses existing version2 SLAY format/decoder.
Dedicated output `/tmp_bt/native_touch_geometry.log` and `.bin`; dedicated stop
`/tmp_bt/native_touch_geometry.stop`. No boot registration or forwarding hook.

ARM build succeeded. Exact upload/readback verified. Native preflight returned0,
all175 resumed (1421ms), actual UI TLS142e5920. First combined shell receipt also
attempted unavailable `df` and returned nonzero AFTER successful preflight; the
corrected dedicated preflight receipt is authoritative. Initial free space was
73728 bytes. Own obsolete V11 binary417184 bytes was removed ONLY after exact
equality to archived PID1020 binary/SHAe0133cf4d6bd141b6f2e42057c409ff41feb902917f2984a5f57e84ef4d5a6e5.
Audit `native-touch-geometry-space-cleanup-e0129.json`; V12 remains on camera.

**PID1673 is running, WAIT attempt0/result1 verified**, normal waiting state.
Receipt `artifacts/hardware/native-touch-geometry-armed-e0129.json`. No touch
selection or hook is enabled. User: unplug USB without poweroff, open MENU, use
wheel to highlight first visible row without opening its option, then hold finger
on center of lowest visible row for5seconds; release, wait5seconds, reconnect.
One brief display pause during CPU freeze is expected.

On callback FIRST preserve BOTH log/bin before any cleanup or rearm. Verify
COUPLED, UI_TLS, MOUSE, FREEZE resumed=attached/result0, BINARY0/END0 and exact
decoded length. If no binary exists preserve log and inspect why; do not infer
absent touch. Stop only own helper if still running. Execute original geometry
and hit functions on this SAME captured mouse/menu state before choosing mapping.

599 unittest tests pass with normal host temp access; restricted run had the
known four temp-permission errors. New coordinate controls and native preflight
are additional checks. Physical touch selection remains incomplete.
