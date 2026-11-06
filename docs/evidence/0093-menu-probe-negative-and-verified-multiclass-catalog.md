# 0093: Initial menu probe negative; verified multi-class catalog and timed sampler

## Returned user test

After the user reported completing the unplug/MENU/wheel/touch/reconnect sequence, the native debugger retrieved `/tmp_bt/native_menu_probe.log` without service mode. Retained as `artifacts/hardware/native-menu-probe-pid1863-after-test.log`. It contains the V1 PID1863 header, sample0/28,389,376 bytes/zero candidates, and END only.

This does not locate a menu object or establish absence of touch events. V1 watched only PAS_MenuSelectMode, lacked timestamps/heartbeats/final sample count/reason, and did not distinguish expiration, stop signal or some early probe failures. Coverage of the user's actual interaction interval cannot be established from this log. Do not call it proof that the digitizer was inactive, the main menu lacked objects, or all 120 samples completed. The user's earlier negative touch-menu result remains valid independently.

## Verified class identities

The preserved view library exports separate PAS_MenuTab, PAS_MenuListTab, PAS_MyMenuListTab, PAS_MenuSelectBelt, PAS_MenuTable, PAS_MenuPopup, PAS_MenuSelectMode, PAS_MenuListPopup and PAS_MenuDataSelectBelt classes. `tools.research.native_menu_catalog` derives their vtables from exact cast/getter code and original R_ARM_RELATIVE records.

For each class it verifies that the cast compares the same type-ID GOT slot returned by its getter, uniquely identifies a primary vtable with offset-to-top zero and nearby Thumb destructors, resolves the exact on-camera cast symbol, compares the full live/file getter+cast window, and verifies the live +0x190 type-getter slot. An initial diagnostic assumption that the RTTI header word must be zero rejected every candidate; it was corrected: offset-to-top is zero, while RTTI is nonzero (MenuSelectMode header 0 / 0x92ebb8). No camera bytes were modified by either catalog attempt.

Successful live report: `artifacts/hardware/native-menu-catalog-20261105-174030/manifest.json`. All nine classes verified. Runtime vtables:

| Class | Runtime vtable |
|---|---|
| PAS_MenuTab | 0x15f18a70 |
| PAS_MenuListTab | 0x15f1f1d0 |
| PAS_MyMenuListTab | 0x15f12cf0 |
| PAS_MenuSelectBelt | 0x15f1def8 |
| PAS_MenuTable | 0x15f21ef0 |
| PAS_MenuPopup | 0x15f1e608 |
| PAS_MenuSelectMode | 0x15f14bd0 |
| PAS_MenuListPopup | 0x15f20250 |
| PAS_MenuDataSelectBelt | 0x15f14fa8 |

All nine observed mouse/mouse-hook slots point to the inherited base methods 0x0631e5c9 / 0x0631e5cf; +0x108 points to the common default-mode setter 0x0612a497. This establishes vtable identities and inherited top-level methods, **not** behavior of child widgets or event delivery. The verified target file was native-uploaded/read-back checked at `/tmp_bt/native_menu_targets.txt`.

## V2 read-only sampler and current armed state

Updated `native_menu_probe.c` uses those nine targets, monotonic start/heartbeat/end times, attempted sample count, final result/reason, SIGHUP suppression and its own session. It is bounded to 144 samples with five-second waits (approximately twelve minutes plus scanning time). It reads raw candidate words at +0x180/+0x1d8/+0x228 without treating class-specific words as validated child ownership. It tracks changes and periodically records liveness; no touch coordinates or event callbacks are hooked.

Known stream mapping at VA0x08a5f000/PA0x202e0000 was independently readable through native memory requests. V2 adds only this exact 32-MiB `/dev/stream` mapping to its previous private mappings, with at most12 ranges/80MiB total. Unknown device/MMIO mappings are excluded. A coarse min/max target check reduces scanning work; alternating samples can recheck previously found objects, while full scans continue periodically. All reads are non-atomic; the process leader is briefly ptrace-stopped, while other threads continue. Candidate matches are not proven live widget instances.

Compiled with warnings as errors and original Sony libc. Native push/read-back verified 11,888-byte binary SHA-256 `66412425652d5fcbf042e92f3b2e1df5f836661e662454b7b08ede36c25b69f2`; no service mode or startup change. It was started through native EXEC as PID **1946**. Actual initial log:

* start_ms 6484182, nine targets,144 max samples,5s interval,read_only=1.
* sample0 at6485205, scan_ms1023, range_bytes61,943,808,zero candidates,atomic=0.
* heartbeat sample0 at6485205.

Start evidence retained in `artifacts/hardware/native-menu-probe-start-pid1946.log`. This confirms execution and records an approximately one-second initial leader-stop/read interval; do not describe sampling as latency-free.

Next user interaction: unplug USB without power-off, open the actual MENU, use the wheel and touch, keep it open at least15 seconds, reconnect. Retrieve `/tmp_bt/native_menu_probe_v2.log` through **native** tools/camera_debugger.py into a fresh report; read ending timestamps/sample count/reason before interpreting coverage. Stop this sampler with its own stop marker if still running. Preserve the earlier V1 negative/ambiguous log. No further RAM patch, key injection or SD write was performed. Touch menu remains unimplemented.
