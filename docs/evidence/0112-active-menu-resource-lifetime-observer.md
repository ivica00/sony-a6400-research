# E0112 — Pending active-menu/resource lifetime capture

Completed by E0113: both files archived/decoded, active reference count1,
176 attached/resumed threads, END0. Header+4 is the resource owner, not a
vtable; the original wording/log label below was corrected by E0113. No V3
observer remains armed. V4 coupled-state capture is described in E0114.

Date: 2026-11-06. Follow-up to E0111's observed zero-reference release boundary.

New tools/native_camera/native_layout_resource_snapshot.c preserves the V2
bounded registry/recursive-wrapper/full-ListTab binary capture, adds the resource
pointer at actual menu+0x127b4, its64-byte header and its relocated vtable+4
prefix0x90. It reports the actual16-bit count at resource+0xc, including zero;
it does not assume or force a positive value.

During capture, native_freeze.h stops all enumerated PID149 CPU threads, verifies
the thread set again and resumes each before file output. The barrier is bounded
to512 threads and a two-second attach deadline. This is CPU-thread consistency
for captured data, not DMA/hardware atomicity. Failures resume acquired threads
and are reported. The preceding one-shot helper validated175 threads/1287ms;
the new observer's MENU capture barrier is pending physical confirmation.

Built with warnings-as-errors and original Sony libc, uploaded to
/setting/native_layout_resource_snapshot.elf, and read-back compared. Deployment
manifest: artifacts/hardware/native-layout-resource-snapshot-v3-start.json.
**PID2896 is running**, launch status0/flags0; start reports174 available4096-byte
blocks, and wait_menu attempt0/result0 plus attempt20/result0 are verified.
No im.elf function is called, no application memory/register is set and no SD
write is made. The tool waits at most600x500ms, then captures within existing
2048-record/512KiB raw bounds with checked binary writes and free-space reserve.

Requested interaction: unplug USB without powering off; open MENU and hold for
10 seconds; reconnect. No wheel/button sequence beyond opening MENU is needed.
Capture can briefly pause the displayed UI while CPU threads are stopped.

On callback, FIRST preserve BOTH volatile files:

* /tmp_bt/native_layout_resource_snapshot_v3.log
* /tmp_bt/native_layout_resource_snapshot_v3.bin

Then check MENU_DETECTED, RESOURCE, FREEZE (attached/resumed equality/result0),
SNAPSHOT0, BINARY0, END0 and exact binary length through
tools/research/decode_native_layout_snapshot.py. Binary remains version2 of the
existing record format. Keep zero/failed/partial results as such. If needed stop
only this observer using /tmp_bt/native_layout_resource_snapshot_v3.stop.
Do not rearm or clean outputs before archiving them. Do not treat deployment as
successful lifetime validation or working touch. If the finite observer has
expired before interaction, preserve its log and prepare a verified new wait
before requesting another physical test.
