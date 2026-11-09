# E0113 — Active reference confirmed; full cache must share its capture phase

Date: 2026-11-06. User returned from the E0112 MENU-only test.

## Complete V3 capture preserved first

Both `/tmp_bt/native_layout_resource_snapshot_v3.log` and `.bin` were archived
as artifacts/hardware/native-layout-resource-snapshot-pid2896.* before any
cleanup. Log is1310 bytes; binary104828 bytes,30 records/104452 raw bytes.
MENU_DETECTED attempt472/object0x278676e0; RESOURCE object0x1a2cace0/count1;
FREEZE176 attached/176 resumed/result0/1403ms; capture attempt0/result0;
SNAPSHOT0/BINARY0/END0. Exact-length decoder and overlapping-byte checks pass.
Binary SHA256:
`3e2f2b314efafb4c250e11d7765150d0c166cc98225cae55ff98d0b1b66ea141`.
PID2896 finished naturally; it is not an armed observer now.

The seven binding fields match E0106 exactly:6/3/6/4/1/0/0. Both menu captures
hold the same resource pointer at+0x127b4. Of20 previously observed header bytes,
only the reference byte at0x1a2cacec differs: later USB0, active MENU1. The entire
new64-byte header is retained, not a guessed patched counter.

**Correction:** header+4 is owner/manager0x6c880, not a vtable. V3's historical
log labels it `table` and captured that owner's0x90-byte prefix. Its first word
is the owner's actual vtable. E0112's original interpretation of this field was
wrong; the bytes remain useful. V4 uses the correct label and dereference.

The configurable active_menu_snapshot_probe replays original lookup on the new
registry and returns actual0x278676e0/error0; original geometry succeeds for all
145 widgets. Report: artifacts/analysis/active-menu-v3-snapshot-probe.json.

## Narrow original reference-release control

prepare_menu_resource_header_control.py verifies successful capture/resume,
matching seven binding fields and identical resource identity. It refreshes
only the actual64-byte header into a separate E0113 control; the one differing
overlapping byte and source hash are recorded. No counter value is fabricated.
The whole older-menu/model/heap/USB combination remains explicitly non-atomic.

Original0x64be068 now takes actual count1 and executes its decrement to0, with
native return0 and an exact-PC two-byte write at0x64be08c. The probe checks the
arithmetic. This verifies that reference-release primitive with observed input;
it does not validate global cache ownership or full activation.

Further exploration exposed the global mismatch: active owner+0x4c has head
0x27881b78; the older USB list has head0x26e6cb98 (tail0x0017da68 in both).
That older469-node list still contains resource0x1a2cace0 at node0x26e3ee50.
Original getter0x64bab7c reads the same16-bit reference count, and acquisition
uses it to decide whether to remove a resource from this list. Thus refreshing
only the reference header is insufficient evidence of a valid full cache state.
Do not promote an exploratory run on mixed phases into activation success.

The explicit `--menu-resource-header` control now stops after the original
reference function returns, at caller0x64bbde4, after20,951 instructions. It
reports control_complete for the primitive only. The unrefreshed E0111 control
still stops at the zero-reference invariant after20,938 instructions. Earlier
exploratory accounting/malloc boundaries remain in the dependency history; they
are not a validated end-to-end operation. History now labels this control
explicitly; older rows without that field remain historical.

## Supporting bounded snapshot tool

native_bounded_snapshot.c accepts at most64 user-memory ranges/128KiB from a
read-back-verified request, stops/checks/resumes process threads and emits the
existing version2 record format with checked writes/free-space reserve. It
does not call im.elf functions or set application memory/registers. The host
capture_bounded_native_snapshot tool archives output/manifest, checks requested
ranges and refuses to overwrite an existing evidence label.

A main-thread libc arena prefix0x1a200000+0x480 was captured with175 threads
attached/resumed/result0,1254ms,1180-byte output. SHA256:
`b81fef6a88d22cd0b2dc4d262ca63300ea9d583ed89da56269454739abecf7d3`.
This is a coherent CPU subset, not an atomic whole application or DMA snapshot;
it has not repaired the separate active-cache ownership mismatch.

Regression: new145-widget geometry and existing252 hit/page-selection controls
pass. Source builds pass warnings-as-errors. Main-menu touch/activation remain
incomplete; no application calls, RAM patches or SD writes. E0114 prepares one
capture of the coupled menu/resource-list/model/allocator state.
