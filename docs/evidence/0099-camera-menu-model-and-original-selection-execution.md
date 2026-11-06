# E0099 — Camera menu model and original selection execution on captured state

Date: 2026-11-05. User returned after the separated MENU/wheel/button test.

## Preserved interaction

Normal USB preserved `native-menu-state-probe-pid2176-after-test.log` before
creating the observer's own stop file; final retained log is
`artifacts/hardware/native-menu-state-probe-pid2176-final.log`.
END samples=1222/result=0. Subsequent ps/grep found no running observer.
Thirteen MENU_STATE records, no reported MENU_STATE errors. Menu object in this
run is 0x278676e0; this differs from the previous run and confirms why fixed
menu-object addresses must not be reused.

Observed prefix +0x1f4 changes through 1,3,2,3,1,2,1; +0x1f0 changes 4 to5;
reference zero at +0x186ac remains 0x160f5cec, with its +0x18 changing 4 to5.
The second reference is null (logged result -1, not a failed application call).
Menu disappearance/reappearance and +0x200 changes are recorded. Exact physical
button-to-record attribution is not established by unmarked pauses alone.
Do not identify every field as a cursor solely from its numeric variation.

## Actual provider, distinct from the previous generic cursor lead

`native-menu-provider-identity.json` retains the live provider object, vtable
and RTTI. The object at 0x160f5cec is **CmnViewSettingNode**, vtable 0x16c183e8
in `/usr/lib/CautionConfig.so` (base 0x1615f000). It is not the previously
investigated CmnViewMenuData object. Existing CmnViewMenuData constructed tests
remain separate evidence and are not the identified menu provider contract.

`native-setting-node-contracts.json` retains ten exported methods, all exact
live/file-equal. `native-setting-node-code.bin` retains a live/file-equal 0xd00
byte original code window at runtime 0x16925a00, covering the executed methods.

* getIndexSelectedItem reads signed node+0x18, writes it to caller output and
  returns1 if positive, otherwise returns0.
* Original getSubNode (vtable+0xf0) returns array node+4/count node+8 when valid.
* getSelectedItem treats the positive selection as one-based array position,
  clamps to count and returns that child. It may write the clamped node+0x18,
  so it must not be remotely invoked as a supposedly read-only getter.
* getIdByIndex searches child+0x20 for the requested index. It does not simply
  index the array; preserve this distinction for filtered/reordered nodes.
* setItemSelectedByIndex finds the child via native virtual methods, invokes
  its setItemSelected, unselects the old child, writes parent+0x18 and changes
  child selection states at +0x24. Node state values have distinct roles.
* getSuperItem reads node+0x10. Field+0xc is not the parent; incidental
  `native-setting-node-parent-cells.json` reads do not establish a parent chain.

Read-only native pointer/array snapshots are retained in
`native-setting-node-hierarchy-usb.json` and
`native-setting-node-selected-path-usb.json`. The broader hierarchy was limited
to100 nodes/depth3 and is incomplete. The focused selected path is root
0x160f5cec ->0x160efcc4 ->0x160f23a0 ->0x0033be28. This is a subsequent USB
snapshot, not an atomic reconstruction of every wheel/button interaction.

## Original ARM execution with actual camera state

`python -m tools.research.setting_node_snapshot_probe` executes the original
captured code and actual virtual table against retained root/child/array data.
All memory mutations are isolated emulator copies; no camera function is called.
Code, supplied-byte, stack/output and selection-write guards reject unknown
reads, unprovided execution targets or unrelated writes. At most2000 instructions
per call; return PC must reach the sentinel. Full report:
`artifacts/analysis/setting-node-snapshot-probe.json`.

Six controls pass:

| Original method / argument | Observed emulator result |
| --- | --- |
| getIndexSelectedItem | status1, output5 |
| getSelectedItem | status1, child0x160efcc4 |
| setItemSelectedByIndex(4) | status1, parent selection5->4, old child state2->1, new child state1->2 |
| setItemSelectedByIndex(5) | status1, existing selection, no writes |
| setItemSelectedByIndex(0) | status0, no writes |
| setItemSelectedByIndex(7) | status0, no writes |

No host replacement selected the child or simulated the original status. These
results establish the original model selection contract on a captured copy;
they do not prove UI refresh, submenu activation, safe application-thread call
context, or working touch menus on physical hardware.

## Next boundary

Trace PAS_MenuListTab's original use of CmnViewSettingNode: which node corresponds
to category/page/row, how the application invalidates/binds changed selection,
and what event opens the selected item. Associate hit-test geometry with those
native nodes before adding a touch handler. Current evidence supports original
selection, not direct remote function calls or arbitrary selection-byte patches.
No new application RAM patches, input injection or SD writes. No observer armed;
do not request another repeated physical test until a new targeted observer is
ready and running. Touch menu remains incomplete.
