# E0118 — Fastbin chain bound and verified prefix capture

Date2026-11-06. Touch incomplete; no application calls/RAM patches/SD writes.

## Returned V6 PID3796

Log preserved as `artifacts/hardware/native-layout-resource-snapshot-pid3796.log` before overwrite. MENU detected attempt78/object0x0e1a4008; resource1a2cace0/ref1/owner6c880; unused list492/activeabsent/nonzero0. All five capture attempts stop -142 after1306 records/193708 bytes; all176 attached threads resume each time (1513/1156/1394/1431/1233ms). SNAPSHOT/END -142; no binary (ENOENT). Additional256 records before the limit are consistent with128 chunk header/full-chunk pairs: the original chain exceeds the capture bound. Failed state is not used as an activation input.

## Bounded prefix revision

V6 now captures up to16 original chunks per fastbin,384 total,32 arenas, prioritizing actual main TLS arena; logs every untraversed tail address with FASTBIN_PREFIX/truncated1. Captured bytes are authentic and complete for each included record, but lists are explicitly PREFIX ONLY. Alignment, exact size-class, duplicate-pointer, address/read/raw/record guards remain. No invented tails, no claim that later allocations beyond retained prefixes will succeed.

Added --preflight: same CPU freeze reads current USB resource list and TLS arena, traverses the prefixes, prints result, resumes all threads; no MENU wait or binary output. This is not active-MENU evidence. Dedicated `snapshot_start.S` passes Linux initial argc/argv; existing debug_start.S passes0/0, so first argument-mode attempt returned2 before capture. Early successful preflight produced no output due libc buffering and raw sys_exit; explicit fflush fixes that. Earlier no-output runs are NOT used as verified preflight evidence.

Final manifest `artifacts/hardware/native-fastbin-prefix-preflight-final.json`: status0/flags0/PREFLIGHT0,3 arenas139 chunks,1308 records75816 bytes,175 attached/resumed1342ms. USB unused list509 includes active-resource address (active_present1), confirming phase differs from MENU; no mixing into MENU replay. Source compiles -Wall/-Wextra/-Werror against Sony libc; exact upload/readback verified.

## Pending physical capture

Revised V6 PID3939 running, wait_menu0/result0 verified, finite3600x500ms wait. Manifest `artifacts/hardware/native-layout-resource-snapshot-v6-prefix-armed.json` contains exact final hash/size/preflight/start/log. Outputs unchanged: FIRST preserve BOTH `/tmp_bt/native_layout_resource_snapshot_v6.log` and `.bin`; decode only after SNAPSHOT0/BINARY0/END0, FASTBINS_END prefix_only1/result0, FREEZE allresumed. Stop `/tmp_bt/native_layout_resource_snapshot_v6.stop`.

User: unplug USB without poweroff, open MENU, hold10s, reconnect. Replay must use this new coupled capture; V5 or USB free-list bytes do not substitute for it.
