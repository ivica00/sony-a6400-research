# E0098 — Original cursor read contract and targeted selection-state observer

Date: 2026-11-05. User authorizes cooperative MENU/button/wheel observations.

Normal USB debugger captured live/file-equal CmnViewMenuData cursor functions:
`artifacts/hardware/native-menu-cursor-contracts.json` and
`native-menu-cursor-internal-contracts.json`. getIndexCursor delegates to
0x061248d6: with non-null model+0xc, it reads item ID at item+8, then the cursor
byte at table+3*ID. Null-table branch instead uses an associative container;
it is not covered by the constructed emulator controls. getSubItem uses a
0x28-byte item stride; child-array pointer is at item+0 and count at item+4.
cursorMoveTo validates the item/target and updates old/new selection through
additional helpers. No such mutation or function call was performed on camera.

`python -m tools.research.menu_cursor_contract_probe` executes the original
captured Thumb getter in Unicorn for explicit constructed indices 0,1,5.
All return as expected; supplied-byte and stack-write guards reject unintended
memory reads/writes. Report: `artifacts/analysis/menu-cursor-contract-probe.json`.
This is narrow original-code execution with constructed inputs, not an observed
camera model, firmware UI advance, or an invented successful menu action.

Original PAS_MenuListTab instruction windows establish fields at +0x1d8..0x200
and trailing fields +0x18694..0x186b0. Four relevant windows (linked 0x5aa1a8,
0x5ab13e, 0x5ab1c2, 0x5aa420) are live/file/preserved-image equal, retained in
`native-menu-state-field-contracts.json`. The two pointers at +0x186ac/+0x186b0
have no assigned model/controller semantics yet; an original method calls a
virtual function through the first pointer. Do not treat either as confirmed
CmnViewMenuData without tracing the provider.

`devcrashday_a6400/native_menu_state_probe.c` adds finite read-only capture of
the verified list-tab prefix (0x204 bytes), trailing 32 bytes at +0x18694 and
bounded 128-byte reads at the two referenced pointers, with explicit results.
Discovery follows the verified live widget tree rather than old fixed object
addresses. Identity/self/type/owner/cycle/range/count guards remain. Snapshot
every two 100ms samples or mouse change; detached before output. Maximum 3000
samples and 8MiB log threshold, with bounded final-snapshot overshoot. It stops
on `/tmp_bt/native_menu_state_probe.stop`. No application writes or calls.

ARM build with original Sony libc and warnings-as-errors passed. Deployment
and start must be verified before requesting interaction. Next capture should
use separated wheel steps and one submenu open/back action to correlate state,
avoiding an ambiguous mixture of wheel/touch actions. Preserve volatile log
through normal debugger before stopping/rearming. Touch menu remains incomplete.

Deployment/start verified: 11444 bytes, SHA-256
`d86be54338fb97dedb9806ad810e31a245a4c1a92876132b8948fe4e86055e8f`,
native upload/readback equal at `/setting/native_menu_state_probe.elf`.
Running PID2176 confirmed by ps and start log
`artifacts/hardware/native-menu-state-probe-start.log`. Sample zero has
MENU_STATE result0/count0 and TREE result0/count70 in USB mode, read_ms4.
Next callback preserve `/tmp_bt/native_menu_state_probe.log` first, then stop
through its own `/tmp_bt/native_menu_state_probe.stop` and retain final log.
Do not rearm on old stop files or overwrite retained logs. The physical sequence
is MENU/wait5s, three clockwise wheel steps with3s pauses, one counterclockwise
step/wait3s, center on an item opening a submenu/wait5s, MENU back/wait5s,
then reconnect USB. User can report any deviation for trace interpretation.
