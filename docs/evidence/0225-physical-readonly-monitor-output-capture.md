# E0225 — Physical read-only monitor output capture

Date: 2026-11-09. Camera remained in MSC; no native command, cursor update, ptrace, camera file write, SD/NAND write or module change.

## Implementation

New `tools/research/capture_uvc_monitor_output.py` discovers current PID149 libMWF mapping, pins original ELF SHA against the inventory, verifies three original code prefixes, resolves actual global pointers through GOT, and validates both queue objects against the original topology. It translates the complete32768-byte shared buffer through exactly one existing `/dev/mem` mapping. It rejects missing/ambiguous/partial mappings, invalid cursors, short reads and changed objects.

Output copying handles ring wrap and limits each debugger read to its MAX_DATA bound. It reads queue header before and after copying and retries at most three times if header/object metadata changes. There is no write/consume or command-send operation. Equal cursors do not make the snapshot atomic: a full-wrap ABA event or other concurrency remains possible, so the report explicitly records that limit.

## Physical result

`python -m tools.research.capture_uvc_monitor_output --output-dir artifacts/hardware/uvc-monitor-output-e0225`

- Input cursors0/0; output0/30115, capacity31728.
-30115bytes copied with equal before/after header and unchanged queue objects.
- SHA-256 `b7427db135316ee1270864fcc090814cb06e496d9d0a334f3e473f6e7c6ff966`.
- Mapping/source-prefix validation passed; physical buffer0x200eb400, current source SHA `a79dc0d558e6454e31e57ea3b026364be924d0e78c1b6101015125a249f7e274`.
- No read cursor advanced, no input bytes enqueued. Existing output remains in camera memory.

Artifacts: `artifacts/hardware/uvc-monitor-output-e0225/manifest.json`, monitor-output.bin and UTF-8 replacement-decoded monitor-output.txt. The byte artifact is authoritative; monitor output includes NUL/binary material, so the text is not an exact byte-preserving rendering. Existing error text in this old output is not evidence of the timing/cause of E0210; no new operation was invoked to produce it.

## Validation

Five tests in `tests/test_uvc_monitor_output.py` cover empty/contiguous/wrapped rings, maximum occupancy, invalid cursor/capacity rejection, exact live-layout translation and absent/partial/ambiguous mapping rejection. All617project tests pass in17.965seconds. Physical capture validates a live non-wrapped case only; wrap behavior is covered by the isolated range tests and E0224's original ARM primitive tests.

## Next

Prepare controlled output consumption that first preserves copied bytes, validates current identity/cursors and handles competing-consumer changes explicitly. Do not call this reader a non-USB recovery channel: host access still uses the debugger's USB transport, and the saved old output does not make future logs survive a disconnected gadget/restart. Then validate a bounded non-writing command and explicit result collection before the already-authorized unique SD journal. No journal has yet been created. A:/dev/mmca remains the only SD candidate; B:/internal flash remains excluded.
