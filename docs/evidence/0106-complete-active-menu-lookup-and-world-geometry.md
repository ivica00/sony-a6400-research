# E0106 — Complete active-menu lookup and original world geometry

Date: 2026-11-06. User reconnected after the MENU-only capture.

## Complete physical capture

Preserved `artifacts/hardware/native-layout-snapshot-pid2491.log`, `.bin` and
decoded `.json` before any cleanup. The observer detected MENU on attempt117,
object0x10f61008. Capture attempt0 returned0, 28 records/104244 raw bytes.
BINARY returned0 with104596 bytes and END returned0. The decoder accepts the
exact binary length and overlapping bytes. Binary SHA256:
`b8c6056a1925949a20abc55240aeb441a89c61ff8d49b7616b7caf6e6248eff5`.
This is a complete bounded capture, not an atomic process snapshot. PID2491
completed naturally; no new observer is armed and no new physical test is needed.

## Original lookup, including nested wrapper

`python -m tools.research.active_menu_snapshot_probe` executes the original
WidgetLayouter lookup on captured registries and generated alias code. It returns
the actual PAS_MenuListTab0x10f61008/error0 in795 ARM instructions. It does not
substitute a separately located list-tab object.

The outer layout/view keys are0xaadca2c7/0xdfdc8ddd. Resource0xa056f604 aliases
to key0xd10c3927, returning wrapper0x27804578. Its embedded registry at+0x14c
resolves nested layout0x5c239777/view0x7f3ae7ef and resource0xa056f604 to the
actual menu. Both generated512-byte alias windows were compared with camera
viewUnified2.so; retained verification is in active-menu-lookup-first-result.json.

## Geometry execution and architectural qualification

The native child/sibling links and self-pointer checks expose145 widgets in the
captured menu tree. Original getWidth/getHeight and calcWorldPos execute for all
145, using local points(0,0) and(width,height). Root world corners are(0,0) and
(640,480). Results are in artifacts/analysis/active-menu-snapshot-probe.json.
The86,016-byte original libObj component at0x6305000..0x631a000 was captured and
file-compared; additional source-checked helpers, GOT entries and data are in
native-widget-worldpos-contracts.json under artifacts/hardware.

The harness enables Cortex-A5 VFP and resets CPU context for each call. It
rejects uncaptured reads and unknown code. Original world-cache updates are
allowed only to captured four-byte fields of verified widgets: offsets44,48,
5c,60,64,68,78,7c,80,90,94,98,9c. These510 writes affect emulator copies only.

Unicorn retains stale Thumb IT state at four verified ends of complete IT blocks
in helper0x63197e0:0x631983a/984c/9862/986c. The harness clears only stale CPSR IT
bits at those boundaries, following the existing interpreter workaround. The run
records102 corrections; original instructions and function results are not
replaced. This qualification matters for interpreting the replay.

A fresh emulator replay in reverse widget order returns all145 with exactly
equal local sizes and world corners, zero differences,510 cache writes and102
IT corrections. See artifacts/analysis/active-menu-geometry-order-check.json.

## Remaining contract

World corners are not yet proven hit bounds: clipping, visibility, transforms,
native row-to-model association and input/action routing remain to be joined.
Do not infer a valid touch target from every tree widget or reuse a previous
controller/model snapshot as if contemporaneous with this capture. Next work
must connect actual list-tab geometry to original selection and activation.
Main-menu touch remains incomplete. No application calls, camera RAM patches or
SD writes were made in this continuation.
