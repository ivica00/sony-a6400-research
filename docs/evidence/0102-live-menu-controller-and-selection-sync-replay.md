# E0102 — Live menu controller and original selection synchronization replay

Date: 2026-11-05. User reconnected after the V2 menu-triggered test.

## Actual interaction coverage

Normal USB retained `artifacts/hardware/native-menu-controller-probe-pid2349-after-test.log`
before its own stop marker; final log is `native-menu-controller-probe-pid2349-final.log`.
The log explicitly records MENU_DETECTED attempt85/object0x0055b8d0 before scan.
Scan completed339 ranges/1846 chunks/448540672 bytes,1 candidate,0 failed
chunks/result0. Matched ViewSettingMenu object0x003fa490 has the verified table
0x15ec8270 and model provider0x160f5cec. Unlike V1, this run actually obtained
controller observations while a native menu was present.

Thirteen changed states were logged across333 attempted100ms observations.
The observer ended on identity guard result-6: the candidate no longer had the
expected vtable after menu/USB transitions. This is an observer lifetime guard,
not a native application error or proof of a crash. Final OBSERVE_END333 is
retained; subsequent ps/grep found no running controller observer.

## Observed state progression

Decoded records: `native-menu-controller-probe-pid2349-decoded.json`.

* Initial model path has first-level selection4, second-level3, third-level1.
* Sample117 changes first level to5 and second level to1. Controller+0x150=5,
  +0x154=1. Sample118 changes controller+0x168 to5.
* Samples147/181/209 follow second-level selections2/3/2, with matching
  controller+0x154. Each selected path includes the actual native node addresses.
* Sample234 changes controller+0x14c to2, +0x15c to1 and +0x208 to1; sample292
  changes +0x14c back to1. These occur in the supplied submenu/back test sequence,
  but exact causal event IDs and the activation callback are not established.
* Controller+0x10 changes through multiple values. These must not be labelled
  physical key codes without deriving the application's event/dispatch contract.

Native controller snapshots are not atomic across all application threads.
No touch input was required or injected in this capture.

## Original controller sync, executed on the trace

Live/file-equal function at viewUnified2 linked0x2068f2/runtime0x157ec8f2 reads
controller+0x1a0, follows selected children through real CmnViewSettingNode virtual
calls, and writes selection fields +0x150/+0x154/+0x158; +0x168 retains the
prior +0x150 value. Slot+0x44 retrieves the node's SR number. The third-level
value is converted to zero-based by the original subtraction instruction.
Original code/table windows: `native-controller-sync-contracts.json`.

`python -m tools.research.controller_sync_snapshot_probe` executes this function
on each of the13 captured states with the original CautionConfig method code
and real vtables. All13 executions return after195 instructions (196 for the
first state), and the three output fields match their actual controller record.
Report: `artifacts/analysis/controller-sync-snapshot-probe.json`.

Only the selected array edge is supplied at each level: the observer read that
array slot to obtain the next logged node. No unobserved sibling array contents
are invented. This reconstruction is explicit in the report. Unknown-byte reads,
unprovided code targets and unrelated writes are guarded. Mutations are isolated
emulator copies, not camera calls or patches. This is an original sync contract,
not full input processing, UI rendering, or selected-item activation execution.
The earlier1040-instruction original widget-binding replay also still passes.

## Next boundary

The live model, controller and widget selection fields are now connected by
original code and camera observations. Next derive the input/action dispatch
leading to the observed controller state transition, and original geometry /
hit-test association of displayed rows with the native setting nodes. Do not
replace the activation path with guessed event numbers or change +0x14c directly.
No new observer armed; no repeated physical test needed until a more specific
capture is prepared. No new application RAM patches, remote application calls,
input injection or SD writes. Touch menu remains incomplete.
