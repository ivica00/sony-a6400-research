# E0119 — Complete V6 prefix capture; resource payload-header boundary

Date2026-11-06. Physical touch incomplete.

## Preserved V6 PID3939

Both outputs archived FIRST as `artifacts/hardware/native-layout-resource-snapshot-pid3939.{log,bin,json}`. Exact213356-byte binary/1360 records/197020 raw, SHA256 `605f679a7d365ab0209bcd67e964d051cef3f83d08d15ab75cd9df3f20bf8a71`. MENU91/object1a28f940. Active resource1a2cace0/ref1/owner6c880; unused list492 nodes/nonzero0/activeabsent. Three arenas155 fastbin chunks (prefix-only, tails explicitly logged). All176 threads attached/resumed1373ms; SNAPSHOT/BINARY/END0. Helper finished; no V6 observer remains armed.

## Explicit offline replay

Prepared input tagged by PID to preserve older manifests/datasets. Older E0113 dependencies refreshed only where new capture covers; additional E0115b records contribute ONLY original source-equal code, never V5 heap bytes. Whole input remains explicitly non-atomic outside new capture.

Captured menu flag+1d8=0/cachedrow0 already selects first row. Optional direction1 would request row1 while current model still selects row0; guard rejects this mismatch (no forced model state). Correct replay uses actual state WITHOUT --native-row-entry:

```powershell
python -m tools.research.prepare_active_menu_control pid3939
python -m tools.research.menu_activation_snapshot_probe --main-thread-control --active-state artifacts/hardware/native-layout-resource-snapshot-pid3939.json
```

Original activation stops after11539 instructions at PC64c027e reading uncaptured0x27882f40. This is a NEW actual cache-dependent path, not regression proof. Captured resource record0x278e6f08 has pointer0x27882f40 at+0x10. Original64c04dc loads [r1] from that field,64c04e0 calls64c027e, which reads the pointed blob header and masks low26 bits. No later USB heap read is substituted. Report `artifacts/analysis/menu-activation-coupled-state-probe.json`.

## V7 next capture

`native_layout_resource_snapshot_v7.c` adds64-byte pointed blob prefixes for each unused resource and active resource, inside SAME freeze. Retains V6 bounded fastbin prefixes and all earlier menu/model/TLS/libc capture. No claim of capturing whole resource bodies or all heap memory.

Compiled -Wall/-Wextra/-Werror using Sony libc and snapshot_start.S. Exact uploaded readback verified. USB --preflight status0/flags0/PREFLIGHT0:509 unused entries,3 arenas171 fastbin chunks,1881 records111160 raw;175 attached/resumed1392ms. This is USB-phase validation, not MENU input. Manifest `native-resource-payload-prefix-preflight.json` includes final binary hash/size.

Only own obsolete V5 binary removed after BOTH V5 outputs exactly matched PID3119 archives; audit `native-v7-space-cleanup.json`. V6 binary retained.

V7 PID4015 armed and wait_menu0/result0 verified;3600x500ms finite wait. Manifest `native-layout-resource-snapshot-v7-armed.json`. User unplugUSB/no poweroff/MENU/hold10s/reconnect. FIRST preserve BOTH `/tmp_bt/native_layout_resource_snapshot_v7.log` and `.bin`; check SNAPSHOT/BINARY/END0, FASTBINS_END prefix_only1/result0, FREEZE attached=resumed and exact decoder. Stop only `/tmp_bt/native_layout_resource_snapshot_v7.stop`.

No application calls, camera RAM patches or SD writes. Physical event mapping, originating UI thread, full activation and rendering still unproven.
