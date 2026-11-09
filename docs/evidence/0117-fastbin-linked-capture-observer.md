# E0117 — Same-freeze fastbin-linked capture prepared

Date: 2026-11-06. Physical touch remains incomplete.

## Evidence and change

E0116 replay stops at original malloc PC0x0431a2fc reading free chunk+4 (`0x1a2bc704`). Source-equal original code0x0431a2e4..0x0431a314 computes chunk size class and loads a fastbin head from arena+(normalizedSize/8)*4, then reads chunk+4 and chunk+8. Thus capturing the arena prefix alone omits linked heap state.

`tools/native_camera/native_layout_resource_snapshot_v6.c` retains V5's menu/resource/cache/model/TLS/libc capture and adds `capture_fastbins()` inside the same CPU-thread freeze. For every captured0x450-byte arena prefix, ten bin heads at+8+4*bin are followed. Each chunk is captured for its original size+8, covering header/payload and following boundary words. Guards:32 arenas,512 total chunks,128 per chain,8-byte alignment, exact size=(bin+2)*8, bounded address/read/record/raw limits, repeated pointer rejection. No heap values are generated. All threads resume on failure. This is CPU consistency, not DMA atomicity.

Build uses existing WSL ARM compiler, Sony libc, -Wall/-Wextra/-Werror, no modern host libc dependency. Binary16196 bytes, SHA256 `134407504f62ebe5fca6a4d820d2a516d8201c5f2ab0dfe0dcc3492c5120d3fe`. Uploaded to `/setting/native_layout_resource_snapshot_v6.elf`; exact readback verified.

## Armed physical capture

PID3726, initial `wait_menu attempt=0 result=0`, SPACE_START118 available4096-byte blocks. Finite wait600x500ms plus bounded capture attempts. Manifest `artifacts/hardware/native-layout-resource-snapshot-v6-armed.json` retains start/result/log/hash.

User: unplug USB without powering off, open MENU, leave it open10 seconds, reconnect. No wheel sequence required. FIRST preserve BOTH `/tmp_bt/native_layout_resource_snapshot_v6.log` and `.bin`. Check FASTBINS_END result0, LIBC_DATA, FREEZE attached=resumed/result0, SNAPSHOT0/BINARY0/END0; decode exact version2 binary. Stop only this helper via `/tmp_bt/native_layout_resource_snapshot_v6.stop` if needed. Do not merge later USB free-list bytes into an earlier MENU snapshot.

To make space, only obsolete own V3/V4 binaries were removed, after BOTH their logs and binaries exactly matched archived PID2896/PID2991 files. Audit `artifacts/hardware/native-v6-space-cleanup.json`. Other tmpfs files and physical SD were left alone. V5 retained.

No application calls, application RAM patches or SD writes. Capture completion and emulator replay remain pending; do not claim success from upload/start.

## Rearm after expired wait

On callback PID3726 log was archived before any overwrite. It reports all600 waits/result0, no MENU_DETECTED, SNAPSHOT/END -50, records0; binary read returnsENOENT(-2). This is expired timing, not evidence that fastbin traversal failed or touch was absent. Result manifest: `native-layout-resource-snapshot-pid3726-result.json`.

Rebuilt the same observer with3600x500ms (30min) finite wait. New binary16196 bytes, SHA256 `7276b4a984690030b6eb7c1eb4cded734953a4f77dc892a9cd75932403ef4e17`, exact upload readback verified. Fresh PID3796/start status0/flags0/wait_menu0/result0 verified; manifest `native-layout-resource-snapshot-v6-rearmed.json`. Same output/stop paths and physical steps apply. On next callback preserve PID3796 log AND binary first. No application calls/RAM patches/SD writes.
