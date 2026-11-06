# E0100 — Original menu binding, refresh contract and controller capture

Date: 2026-11-05.

## Executed native model-to-view binding

Live/file-equal windows in `artifacts/hardware/native-menu-binding-contracts.json`
cover viewUnified2 linked 0x5ab430..0x5ab572, helper setters/predicates at
0x5aa41c..0x5aa55c and terminal no-op 0x5ab3b2. It also retains the actual
CmnViewSettingNode vtables used by the captured selected path and its children.
`native-setting-node-selected-leaf-children.json` adds the selected leaf's two
children after verifying its 64 bytes were unchanged from the retained snapshot.

`python -m tools.research.menu_binding_snapshot_probe` executes **1040 original
instructions** on merged retained camera snapshots, through real virtual calls,
and returns. Code/byte provenance and narrowly permitted write guards remain
active. The merge rejects overlapping conflicting bytes. This is a non-atomic
research context combining MENU prefix sample842 and subsequent USB model data;
it is not an atomic camera checkpoint or full UI execution.

The original function reads provider at widget+0x186ac and walks selected
children. Virtual slot+0x10 is **getCountSelectable**, not getCountAll; it checks
each child's native isItemSelectable at slot+0x8c. Slot+0x28 gets selected child;
slot+0x30 gets its selected SR number. The executed output exactly matches the
observed menu fields:

| Widget offset | Original output |
| --- | --- |
| +0x1e4 | 6 selectable at first level |
| +0x1e8 | 7 selectable at second level |
| +0x1ec | 6 selectable at third level |
| +0x1f0 | selected SR number5 at first level |
| +0x1f4 | selected SR number1 at second level |
| +0x1f8 | selected third-level SR number minus1 =0 |
| +0x1fc | selected subitem SR number minus1 =0 for mode2 |

Report: `artifacts/analysis/menu-binding-snapshot-probe.json`. The original code
performs model selection clamps and widget-field writes itself. No host helper
supplies a successful virtual-call result. Category/page/row interpretations
must still be associated with actual display geometry, especially filtering.

## Original refresh caller and application controller

The widget's live slot+0x1ac points to linked 0x5ac110. Live/file-equal caller
windows are in `native-menu-refresh-callers.json`. This method calls the verified
binding then native presentation/layout helpers; only the binding portion has
been executed here. Linked 0x5ab652 installs a non-null provider at +0x186ac,
calls binding and sets +0x200 to1. Other native paths consult +0x200 to decide
whether cached selection fields require rebinding. It is not established that
changing the model by itself repaints or activates a menu item.

Static relative-relocation/RTTI analysis identifies **ViewSettingMenu**, primary
table linked0x8e2270, runtime0x15ec8270. Actual RTTI and live table are retained in
`native-viewsetting-controller-identity.json`. The caller reads controller+0x1a0
as the widget's model provider and invokes slot+0x1ac after binding. Class-table
candidate and direct-call leads are retained under `artifacts/analysis`.
Application event handling and selected-item activation are not yet verified.

## Read-only native scan and next observer

`native_viewsetting_scan.c` compiled with warnings-as-errors and original libc,
uploaded/readback-equal:6808 bytes, SHA-256
25903709953540d247993dc70b119c34c56953fcae89dc4f872977cca2f6bf88.
PID2237 completed a single normal-USB scan:224 eligible private-anonymous
ranges,1532 chunks,392306688 bytes,0 candidates,0 failed chunks/result0.
Each chunk detaches before yielding. Retained log:
`artifacts/hardware/native-viewsetting-scan-usb.log`. Zero candidates is scoped
to those ranges and USB state; it does not establish universal controller absence.

`native_menu_controller_probe.c` is a finite extension:60-second initial delay,
one bounded scan while MENU is open, then at most1800 100ms observations of a
matched ViewSettingMenu whose provider equals the verified root. It snapshots
controller0x380 bytes and the selected native node path (up to8 levels), only
following arrays when virtual getSubNode exactly matches the verified method.
Unsupported providers/depth/read/cycle guards are explicit. Old/freed controller
identity ends observation. No application calls, RAM patches, input injection,
or SD writes. Log threshold8MiB; stop file
`/tmp_bt/native_menu_controller_probe.stop`. ARM build passed; actual deployment
and startup must be appended before requesting a physical test.

Physical sequence once armed: disconnect USB without power-off, open MENU and
hold90 seconds; then three clockwise steps with3-second gaps, one reverse step,
center on an item opening a submenu/wait5 seconds, MENU back/wait5 seconds,
reconnect. Preserve `/tmp_bt/native_menu_controller_probe.log` first on callback,
then stop via its own marker and retain the final log. Distinguish scan END from
OBSERVE_END. If scan is still in progress, retain it and allow bounded completion.
Touch menu remains incomplete.

Deployment/start verified:11196 bytes, SHA-256
bbc0a9f327d0f9de024119a7818ba080dc5c50c422540f1d590a4f30aa8df0d0,
native push/readback equal. PID2259 confirmed running, start log retained at
`artifacts/hardware/native-menu-controller-probe-start.log`, initial60-second
delay. No claim that active controller discovery has succeeded yet.
