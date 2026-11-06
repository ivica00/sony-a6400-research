# E0103 — Original action route, selected-node helper and geometry primitives

Date: 2026-11-05. Read-only normal-USB code captures; no new physical test.

## Original selected-node execution

`tools/research/controller_sync_snapshot_probe.py` now also executes original
ViewSettingMenu helper linked0x207c4a/runtime0x157edc4a against all13 E0102
records. It follows three native getSelectedItem virtual calls and returns the
third-level node, matching the recorded path in every case. First execution150
instructions; others149. No unobserved array siblings supplied; each selected
edge comes from the observer's actual logged traversal. Existing13 sync and
1040-instruction widget-binding controls still pass.

## Original action route, with explicit dependency stop

Live/file-equal captures in `native-viewbase-event-action-contracts.json` and
`native-viewbase-action-dispatch.json` establish:

* ViewBase::Action at0x06103ef0 calls object slot+0x94 (ProductAction).
* ViewBaseProduct::ProductAction at0x158d7350 calls slot+0x100.
* ViewSettingMenu's slot+0x100 points to linked0x21355e, a guarded action-index
  TBH dispatch table. Action1 goes through wrapper0x213548 to0x2127e8.
* For controller+0x14c values1/2, the latter performs ViewBase::getWidget with
  resource ID0xa056f604. If lookup and selected-node lookup succeed, static
  continuation calls widget method0x5ac044 and updates controller+0x14c from
  the native result. That continuation has not yet been executed successfully.

The emulator takes actual E0102 controller sample209 and an **explicit
caller-supplied action1 control**. It executes39 original instructions through
the real table and stops at the declared ViewBase::getWidget PLT boundary,
runtime0x15735328, controller0x003fa490/resource0xa056f604. No service result is
supplied, no model/UI success is invented, no non-stack writes occur. Report
`artifacts/analysis/controller-sync-snapshot-probe.json` records returned=false.
This does not prove physical center-button -> action1 mapping, thread context,
native activation completion or working menu touch.

## Event-ID distinction

The original ViewBase::GetEventId does **not** simply read controller+0x10.
It reads event context through +0x14 and other native conversions. This pointer
is zero in the retained controller records. Neither physical key IDs nor the
full originating event can be reconstructed from the +0x10 changes alone.
The Action pre/post helpers captured at0x06103ee4/0x06103eea are no-ops and do
not establish who writes +0x10. Do not relabel that field without writer evidence.

## Native widget lookup and geometry

`native-menu-lookup-geometry-contracts.json` captures original ViewBase::getWidget
at0x06104320. It iterates up to six view identifiers at controller+0x80 onward,
uses controller+0x74 and the requested resource identifier, and calls native
WidgetLayouter::getWidget. These fields are identifiers, not established raw
object pointers. The native function rejects ambiguous multiple widget matches.
The original layout registry/state needed to execute that lookup for the active
menu is not in the retained controller prefix snapshots.

`native-menu-layout-lookup-contracts.json` captures WidgetLayouter::getWidget at
0x062e27de and its internal call targets0x062e2228/0x062dec04, not yet executed.

Primitive geometry contracts are live/file-equal:

* Widget::getWidth/getHeight address its region at widget+0x30, then read region
  +0x58/+0x5c, i.e. widget+0x88/+0x8c. Preserve their original value/ABI semantics.
* Widget::getLocalPos delegates to gfxeng::Element::getLocalPos; the actual latter
  at0x06319698 returns region+0x1c, i.e. widget+0x4c. Capture retained in
  `native-element-localpos-contract.json`.

These establish local geometry storage, not framebuffer hit bounds. Parent
transforms, scale, clipping and native hit testing must still be followed.
Do not substitute guessed screen rectangles for native widget geometry.

## Next work

Derive the original WidgetLayouter registry/access contracts and capture only
the required live active-menu registry/widget geometry. Complete lookup before
continuing native0x5ac044 and refresh/activation. No new observer armed, no
application RAM patches/calls, no key injection and no SD writes. Touch MENU
remains incomplete.
