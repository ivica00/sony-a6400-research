# 0089: Native gates applied, physical menu-touch test negative

## Physical outcome

The user tested the menu after disconnecting USB without a requested cold boot and reported no touch-menu response. The camera was subsequently found over USB. `tools/inspect_touch_camera.py` retrieved `/setting/touch_native_guarded_v3.log`, retained at `artifacts/hardware/touch-inspect-20261105-161853/setting__touch_native_guarded_v3.log`.

The report records PID 1375/uid 0, libObj base 0x05d18000, viewUnified2 base 0x155e6000, and exact on-camera exports at 0x3cf188/0x56dcb0. Both full original windows matched. It reports `BYTES_VERIFIED: two native touch gates patched; UI behavior NOT VERIFIED`, followed by END and no detach error. The source only emits that status after both writes and full post-write comparisons. This is evidence of the two guarded RAM changes at attempt time, **not** evidence of successful menu interaction or that code remained patched across any later reset.

The user then explicitly clarified: **touch autofocus works in live view; the menu does not react**. Thus the physical digitizer and at least its autofocus path operate. A hardware-input failure does not explain the complete observed result. The experiment disproves sufficiency of the two gates; it does not establish why menu dispatch fails. A cold boot is not an evidence-backed fix.

## Original menu-widget contract

`python -m tools.research.menu_widget_audit` derives the PAS_MenuSelectMode constructor vtable from original instructions/literals and ELF relocations, verifies named method slots and writes `artifacts/analysis/menu-widget-audit-20261105.json`. This is preserved-image static evidence, not live widget-state inspection.

* Constructor at linked 0x56c92c, GOT slot 0x9474e0, virtual address table 0x92ebd0.
* Virtual slot +0x108, called by setTouchable, resolves to `LayoutableWidgetBase::setDefWidgetMode`, not a touch-event callback. The mode setter stores the requested mode at object+0x180 and calls Widget::setMode unless current mode is 3.
* Slots +0x68/+0x6c resolve to inherited WidgetBase::onMouseEvent/onMouseEventHook. The preserved onMouseEvent at libObj linked 0x606640 simply returns; onMouseEventHook at 0x606646 returns one. PAS_MenuSelectMode has no specialized override in these two slots.
* The constructor creates a child GEN_GridList at object+0x228, enables its mouse-event hook, sets the parent passive region, and initializes widget mode zero. Child-list handling and upstream event dispatch must be traced before concluding the entire menu lacks touch processing.

Separate original InputService/InfraTp methods configure resource touch settings/modes and widget-use reference counts independently of setTpEventSw. Their runtime state was not supplied or modified. Do not equate a forced boolean switch with proof of valid current touch resources, event delivery or menu selection actions.

## Current state and boundary

No further RAM patch was added after the negative test. The experimental preload entry remains `/setting/touch_native_guarded_v1.so`; its binary is the third version, with a persistent O_EXCL one-shot report already present. That report suppresses reapplication, so this is not a verified persistent mod. Preserve reports and do not delete/rearm automatically. Runtime state after a future restart needs independent verification.

The next useful boundary is native touch-to-widget event dispatch and child-list selection consumption, with actual camera-version symbols/bytes. No invented tab coordinates, assumed initial tab, synthetic key train, or more hardware-on forcing is justified as a solution from this experiment. The physical touch-menu objective remains incomplete. SD was not modified.
