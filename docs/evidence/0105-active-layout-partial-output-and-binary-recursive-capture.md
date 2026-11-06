# E0105 — Active layout captured, output incomplete; binary recursive capture

Date: 2026-11-05. User returned after the MENU-only capture.

## Returned V1 evidence

Retained logs `native-layout-snapshot-pid2416-after-test.log` and `-final.log`
under `artifacts/hardware` are identical110592-byte files. Native capture reports
MENU_DETECTED attempt84/object0x1a28fb90, capture result0/21records/102612 raw
bytes. Output ends inside the final100028-byte list-tab record; no END exists.
Only52117 complete bytes of that final record were retained, plus an incomplete
hex nibble. `native-layout-snapshot-pid2416-decoded.json` explicitly marks the
snapshot incomplete and retains20 full records plus the usable partial prefix.
Do not treat the declared capture result0 as complete output or pad missing RAM.

`/proc/mounts` confirms /tmp_bt is a **1MiB tmpfs**. Two obsolete observer logs
occupied820510 logical bytes. Before cleanup, both were read through the normal
debugger and compared byte-for-byte with existing complete local archives:
native-menu-state-probe-pid2176-final.log and
native-widget-probe-pid2112-after-test.log. Only these two task-created obsolete
remote logs were removed; archive hashes are in `native-observer-log-cleanup.json`.
The V1 output path did not check fwrite/stdio errors, so no write errno was
captured. The block-boundary truncation and available capacity support output
space exhaustion; do not claim a recorded ENOSPC result.

## Useful complete records and nested lookup boundary

The active layout includes view0x1a2bd1e0/key0xdfdc8ddd. Its generated alias
provider maps requested resource0xa056f604 through a widget-map key0xd10c3927.
That map entry's value is a WidgetLayoutNode at0x1a269ce8, not the list-tab
application object itself. Only160 bytes of that node were captured.

Original function0x062e018a reads wrapper+0x13c/+0x140 and uses an embedded
WidgetLayouter registry at wrapper+0x14c for the additional lookup. Those fields
and its nested registry were outside V1's160-byte geometry prefix. Capturing
this genuine nested registry is necessary; do not substitute the separately
found PAS_MenuListTab pointer as a native lookup result.

## V2 changes and validation

`native_layout_snapshot.c` now captures known WidgetLayoutNode vtable0x0705ff60
through0x18c, then recursively follows its verified embedded registry and native
layout identifier. Depth8/view128/hash/cycle/count/pointer/identity guards are
explicit; repeated views are deduplicated. The byte recorder is capped at512KiB
raw/2048records. It still performs no application calls or writes.

Raw output is now a bounded binary file `/tmp_bt/native_layout_snapshot_v2.bin`:
four32-bit header words (magic0x534c4159,version2,count,rawsize),12-byte record
descriptors and raw bytes. The short log is
`/tmp_bt/native_layout_snapshot_v2.log`. It queries statvfs at startup and before
writing, reserves32KiB, checks fwrite/fflush/fsync/fclose and records output
status. SNAPSHOT capture success is distinct from BINARY/END success. Dedicated
stop marker `/tmp_bt/native_layout_snapshot_v2.stop`.

`tools/research/decode_native_layout_snapshot.py` rejects truncation, extra
bytes, malformed headers/ranges and conflicting overlapping bytes. A positive
constructed-format control and four malformed/truncated controls passed.
Final ARM build with warnings-as-errors/original libc passed. Deployment/start
and startup statvfs numbers must be verified before a new request.

Next callback preserve **both** V2 log and binary before cleanup/rearm, require
BINARY/END result0 and exact decoded file length, then replay the native lookup
on active captured registries. Short physical sequence once running:unplug,
MENU,hold10s,reconnect; no wheel/button sequence. No SD writes, application
patches or input injection. Touch menu remains incomplete.

Deployment/start verified:11608bytes, SHA-256
f45916afe6c2a42f859988933cd196457df83bc3ca2d84be078ff3a9016dddd1,
native upload/readback equal. PID2491 running, startup log retained at
`artifacts/hardware/native-layout-snapshot-v2-start.log`: blocks256,
available204,frsize4096 (835584 bytes available), wait_menu attempt0/result0.
This validates statvfs output against the1MiB mount and confirms the observer
is waiting; it does not establish successful active-menu capture yet.
