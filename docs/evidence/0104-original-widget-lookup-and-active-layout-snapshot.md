# E0104 — Original widget lookup and targeted active-layout snapshot

Date: 2026-11-05. Normal USB debugger; no new physical interaction yet.

## Native registry contract

`artifacts/hardware/native-widget-layout-registry-contracts.json` retains
live/file-equal original lookup instructions. Singleton producer0x062e2228
resolves GOT0x0708be64 -> storage0x07107f34 -> instance0x0013c7a0.
The first64 instance bytes are16 hash bucket pointers. Keys hash to low4 bits;
entry identifier is +8, chain pointer +0xc. Layout entry+0x14 contains the
second16-bucket map of views, using the same key/link fields.

Read-only bounded native traversal retained11 layouts and3 current USB views
in `native-layout-registry-usb.json`. Captured controller layout ID0xaadca2c7
matches entry0x003638a8, whose view buckets are empty in this USB snapshot.
Its requested first view ID is0xdfdc8ddd; the repeated remaining identifiers
0x35cc4d2e are the original getWidget sentinel. This is a scoped native absence
in the USB registry, not proof about active disconnected MENU.

`python -m tools.research.layout_registry_snapshot_probe` executes original ARM
hash lookup functions with retained registry entries and explicit constructed
search-key ABI. All11 layout and3 view positive controls return exact captured
addresses; a missing-layout control and the USB menu-view lookup return null.
No logging/error status is fabricated or supplied as a service reply.

## Full native widget lookup in the USB snapshot

Additional read-only captures retain a live view, its widget map, resource alias
provider and exact code/GOT windows:

* native-layout-view-widget-contract.json
* native-layout-widget-map-alias-contracts.json
* native-layout-usb-widget-map.json
* native-layout-lookup-component.bin (live/file-equal original executable bytes)
* native-layout-lookup-got.json

The original WidgetLayouter::getWidget executes **403 instructions**, including
singleton, both hash maps, native virtual dispatch, generated resource alias
mapping and native widget-map lookup. Inputs are actual USB layout0xcd53a632,
view0x0a7b957f, resource0x4de964b0. It returns actual widget0x26f05758 and writes
error0. The report is `artifacts/analysis/layout-registry-snapshot-probe.json`.
Supplied-byte, code, stack/error-write and overlapping-source conflict guards
remain active. This is the actual USB display widget, not a successful MENU
lookup or activation. Earlier controller sync/action-boundary and menu-binding
probes still pass.

## Capturing the missing active-menu state

Source `devcrashday_a6400/native_layout_snapshot.c` waits up to600x500ms for
the verified native PAS_MenuListTab tree identity. After1s settling it captures
the actual layout registry chains, matching layout's views, resource providers /
virtual tables / generated alias-code windows, widget map entries and160-byte
widget state (including original local geometry fields). A verified list-tab
object additionally gets its original0x186bc-byte object prefix, covering
previously verified trailing fields and embedded widgets.

All reads are bounded:2048 records,2MiB raw storage, explicit pointer/hash/chain/
count/identity guards, five bounded capture attempts for transient state.
Output occurs after detach; raw records include address/length for independent
verification. Failures and incomplete capture remain explicit. No application
calls, patches, input injection or SD writes. Dedicated stop marker:
`/tmp_bt/native_layout_snapshot.stop`; log `/tmp_bt/native_layout_snapshot.log`.

Initial ARM build failed before compilation with WSL HCS resource exhaustion.
The sole Ubuntu distribution was confirmed Stopped before an idle WSL shutdown;
subsequent build and final rebuild passed with warnings-as-errors/original libc.
No running distribution was deliberately terminated. Deployment/start must be
verified before requesting the short MENU-only capture. Next callback preserve
the volatile log before any stop/rearm and check SNAPSHOT/END result/counts.

Next physical capture once armed:unplug without power-off, open MENU, hold10s,
reconnect. No wheel/button sequence required. Full active-menu lookup, world
geometry/hit testing and touch activation remain unimplemented/unverified.

Deployment/start verified:11340 bytes, SHA-256
7f1d5d51ecda7c492e0d3a820b376e1000f2c9a65439f4f892a84abfd45273ad,
native upload/readback equal. Running PID2416 confirmed by ps and retained
`artifacts/hardware/native-layout-snapshot-start.log`: wait_menu attempt0/result0.
This verifies the observer is waiting; active MENU capture is still pending.
