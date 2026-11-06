# E0108 — Original row hit checks and separate selection controls

Date: 2026-11-06. Normal USB read-only code/vtable capture; offline execution.

## Source and live dispatch

New artifacts/hardware/native-hit-visibility-contracts.json contains source-equal
original Widget::isHit0x6305080(size218), WidgetBase::sys_isHit0x631e5fe(size8)
and Element::isVisible0x631960c(size14), plus the layer visibility function.
The latter two visibility functions have not been replayed here.

Live row vtable0x15f1d948 and list-tab vtable0x15f1f1d0 both have slot+0x8c
pointing to0x631e5ff, the Thumb base sys_isHit method returningtrue. These are
captured relocated tables, not asserted file-byte-equal tables. An attempted
raw table/file comparison differed as expected for relocation; only original
function bytes have source equality asserted. No code or table was patched.

Widget::isHit calls region routine0x63083ae, rejects nonpositive extents,
uses signed margin halfwords widget+0x130/132/134/136 and compares the supplied
point, then invokes original slot+0x8c. All these widget bytes are in the full
E0106 capture. Existing geometry harness now optionally executes this function,
retaining its original cache-write guards and architectural qualification.

## Offline original hit execution

`python -m tools.research.menu_row_hit_snapshot_probe` performs252 original hit
checks: six widgets against42 explicit points, with no returned hit result
supplied by the host. Each of the six row-center coordinates hits exactly its
corresponding row. For every row, x16 rejects, left/top corner accepts, last
interior pixel accepts, x623 rejects, bottom edge rejects, and the next
separator pixel rejects. This confirms inclusive left/top and exclusive
right/bottom for this captured state, not a universal host hit-test rule.

The original region helper and virtual hit method complete using captured
code/data; no additional missing helper response was supplied. Report:
artifacts/analysis/menu-row-hit-snapshot-probe.json. The initial smaller result
is retained in menu-row-hit-first-result.json.

## Separate original model selection

The same tool separately executes original setItemSelectedByIndex on the
retained page0x160fbaa0 for indices1..6. Each succeeds and sets the selected
index correctly in emulator memory; selecting current1 is a no-op. Invalid0/7
fail without any model writes. Existing E0099 root selection controls still
pass. The selection runner now accepts an optional actual snapshot, preserving
its default earlier capture and strict read/write boundaries.

These are deliberately separate controls: no camera event-to-selection routing
is claimed. Host orchestration of a geometric result and a model setter is not
evidence that original firmware routes physical touch through those methods.

## Remaining work

Geometric hit and model selection now execute independently on captured actual
rows. Original visibility/ancestor routing, selection refresh, physical event
mapping and full activation/popup path remain unproven. E0097 established that
menu mouse handlers are empty, so successful geometric checks alone cannot
enable menu touch. No observer armed/no physical test needed yet; no application
calls, camera RAM patches or SD writes. Main-menu touch remains incomplete.
