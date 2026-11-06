# E0107 — Retained model matches active menu; native row association

Date: 2026-11-06. Normal USB, read-only process/file captures; no physical test.

## Separate retained-model capture and binding replay

The complete E0106 list-tab has provider0x160f5cec at+0x186ac, null+0x186b0,
mode2, categorySR4/pageSR1/rowIndex0. A bounded later USB capture follows the
native model's selected child arrays, verifies every node's CmnViewSettingNode
vtable0x16c183e8, and rereads each parent prefix after reading its children.
Capture: artifacts/hardware/native-setting-node-after-layout-pid2491.json.

Selected path:0x160f5cec(count6,selected4) ->0x160efc9c(count3,selected1)
->0x160fbaa0(count6,selected1) ->0x0033b0f8(count1,selected1)
->0x0033b138(count0,selected0xffffffff). The terminal sentinel is retained as
observed, not normalized. An initial attempt stopped on the terminal sentinel
before saving; the complete bounded repeat is the retained artifact.

`python -m tools.research.menu_binding_snapshot_probe --active-layout` executes
the original binding in961 instructions and reproduces all seven E0106 fields:
counts6/3/6, SRs4/1, row/option0/0. The original1040-instruction E0099 control
also still passes. Matching fields establish compatibility of these separately
captured states; they do not make the combined snapshot atomic or prove all
other model contents unchanged since MENU.

## Original refresh association and indexed lookup

The32768-byte component0x15b90000..0x15b98000 was read in bounded chunks and
compared byte-for-byte with camera /usr/lib/viewUnified2.so. The `.bin` and
`.json` identity manifest are artifacts/hardware/native-listtab-code-component.*.

Static original refresh evidence:

* At0x15b91ab2/0x15b91afc, current category/page SRs select their model nodes
  using virtual+0x24.
* Loop0x15b91b2c calls page virtual+0x24 with rowIndex+1.
* At0x15b91c2c the same zero-based rowIndex is passed to0x15b91890.
* The latter addresses embedded row widget menu+0x9350+rowIndex*0x1118.
  Row loop stops at six. This is original display association, not a host
  replacement hit-test or a completed refresh execution.

`python -m tools.research.menu_row_snapshot_probe` executes original virtual+0x24
at0x16925bc6 on page0x160fbaa0. For indices1..6 it returns respectively
0x33b0f8/0x33b178/0x33b1b8/0x33b1f8/0x33b238/0x33b278 in47/54/61/68/75/82
instructions. Every returned object equals the corresponding captured child.
Invalid indices0/7 returnfalse/null in84/37 instructions, without model writes.
All reads require captured bytes; only stack/output writes are allowed.

These six row widgets already have original geometry replay results: x17..623,
y126..174,176..224,226..274,276..324,326..374,376..424. The tool joins the
original lookup results and the static refresh association with those geometry
records in artifacts/analysis/menu-row-snapshot-probe.json. It checks the
captured refresh-component hash and explicitly marks full_refresh_executed=false
and hit_testing_proven=false.

## Activation dependency and remaining work

New source-equal windows in native-menu-selection-transition-contracts.json
confirm0x15b92044(linked0x5ac044) stores its node argument at menu+0x186b0,
calls0x15b916fc and0x15b90fc4, queries node virtual+0x10, and either closes the
popup path or prepares embedded popup menu+0xfb20 using additional routines.
This is not an activation success: that call chain has not been fully replayed.

Next: original visibility/clipping/hit contracts and original selection-to-refresh
or popup activation execution, followed by a targeted physical comparison when
the observer is prepared. Physical event-to-action mapping is still unproven.
No observer is armed, no new physical interaction requested, no application
calls/camera RAM patches/SD writes. Main-menu touch remains incomplete.
