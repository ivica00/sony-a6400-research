# E0097 — Actual menu tree, touch coverage and mouse-handler boundary

Date: 2026-11-05. User returned from the physical MENU/touch interaction.
Normal USB debugger retained `artifacts/hardware/native-widget-probe-pid2112-after-test.log`,
then the observer's own stop file was created and final log retained again.
END samples=651, result=0. Fifteen changed-tree snapshots, no tree guard errors;
maximum 198 widgets, compared with 70 in USB mode. No new application RAM
patches, remote application calls, input injection or SD writes were performed.

## Observed actual menu

The verified PAS_MenuListTab vtable 0x15f1f1d0 appears at object 0x0ecc6008.
PAS_MenuListPopup appears at 0x0ecd5b28. The original PAS_MenuSelectMode vtable
does not appear in these tree snapshots. This does not prove it never exists.
During stable menu snapshots PAS_MenuListTab has flags 8, mode 2, parent
0x003456e8 (mode 0), grandparent 0x0034549c (mode 0). Modes are observed numeric
values; native setTouchable's 0/2 selection is evidence for its own contract,
not proof that changing the entire tree to mode 0 will implement selection.

Eighteen active mouse samples occur at sample 375–433 while the most recently
changed tree still contains PAS_MenuListTab. Coordinates and state 1 alternate
with release-like zero-state/0x7fff records. The observer reads the tree on
each mouse-record change but suppresses unchanged hashes. These non-atomic
observations support menu interaction coverage; they do not observe callback
execution or a resulting selection action.

## Native method evidence

`native-menu-tree-mouse-slots.json` retains slots +0x68/+0x6c for all 21 unique
vtables in the 198-widget menu snapshot. Twenty types, including PAS_MenuListTab
and PAS_BtnPopup, point to WidgetBase's empty onMouseEvent at 0x0631e5c8 and
default hook at 0x0631e5ce. GEN_Button is the sole exception: onMouseEvent
0x06111a66. `native-menu-tree-typeinfo.json` retains the RTTI names read from
the actual vtables; WidgetNode, GEN_Label and GEN_Icon are distinguished from
buttons. No sampled widget has mouse-hook flag bit zero set.

`native-actual-menu-methods.json` retains the live/file-equal method windows.
The root's +0x108 method is LayoutableWidgetBase::setDefWidgetMode at
0x0612a496, storing default mode at +0x180. `native-menu-child-mouse-handler.json`
retains the original GEN_Button handler, which copies the event at +0x3a8,
updates its internal controller at +0x298 and conditionally calls 0x061119fa.
Its full event/action contract is not yet derived. Do not transplant this
handler onto another widget: object layouts are different.

`native-menu-listtab-custom-methods.json` captures live/file-equal custom
vtable targets. The low-level mouse and key slots are inherited base handlers;
application menu control must be investigated through native application
events/controller contracts. Enabling the previously targeted SelectMode or
changing mode bytes cannot be claimed to add absent list-tab callbacks.

## Reproducible analysis and next work

`python -m tools.research.decode_native_widget_probe LOG --menu-vtable 0x15f1f1d0 --output REPORT`
validates record lengths/counts and retains tree/touch associations. The actual
report is `native-widget-probe-pid2112-analysis.json`. Its menu-vtable parameter
must come from a version-matched verification, not an assumed address.

The next implementation prerequisite is the original application-level
menu selection/activation contract and widget geometry/hit-test contract.
The physical touch-menu modification remains incomplete. No observer is armed
and no further repeated interaction is required for this evidence. Do not
report a successful touch-menu implementation from these diagnostics.
