# E0123 — V9 Sprite capture and packed resource index

Date2026-11-06. Physical menu touch incomplete.

## Complete V9 PID713

BOTH outputs archived FIRST as native-layout-resource-snapshot-pid713.{log,bin,json}. Exact300872-byte binary/2040 records/276376 raw; SHAb5e9f531805b84c53de86a355ac41d3ea07b1656c136b1aa5c0fe6f88e5850d3. MENU352/object0dc6a008. Resource1a2cace0/ref1/owner6c880, unused492/nonzero0/activeabsent.140 Sprite candidates/22 nonnull slots/17 unique resources; three arenas219 prefix-only fastbin chunks.176 attached/resumed1394ms; first attempt/SNAPSHOT/BINARY/END0. No V9 observer remains armed.

Coupled replay WITHOUT USB controls passes the Sprite26e46900 header and image accesses, reaches25987 instructions at PC64b54e0 reading2 bytes at21baa830. Report menu-activation-v9-coupled-replay.json. All prior allocation/ref controls still pass.

## Packed-index contract, not allocator metadata

Original64b55c6 returns backing+10 ->21ba9008. Functions64b5456/5462 read header offset (byte0&7c) and encoding(byte0&3);64b5486 reads count(word+4&1fff).64b5476 reads data offset((word+4>>11)&7ffc).64b5492 returns base+headerOffset;64b54a0 returns that plus dataOffset, delimiting the index before payload. Encoding0 lookup64b54b6 reads uint16 table[index], returns entry*4; out-of-range orffff returnsffffffff. The current query index0xc10 is within count7016; missing address21baa830 equals tableStart+2*0xc10. This is an original packed resource index; do not label it an allocator/free-list bitmap.

All17 Sprite resources' captured+14 backing pointers are14bcc0 or150c08. Later CPU-frozen USB metadata (NOT merged into baseline) confirms:

- 14bcc0+10 ->21ba9008, encoding0/header8/count7016/table14032/exact prefix14040.
- 150c08+10 ->17797008, encoding0/header8/count750/table1500/exact prefix1508.

Backing capture native-packed-resource-backing-usb-e0123:175resumed1280ms/256raw/296file/SHA689adbeb1a9cc79b44e1889ab32db5b24f10ac3450d26ac16adb0ebf0650b4da. Header capture native-packed-resource-index-headers-usb-e0123:175resumed1330ms/32raw/72file/SHAc89e701780c8c3e52d93f6e45413274b012099b967df66ca7fded2f61c80c872. Exact two-prefix capture native-packed-resource-indices-usb-e0123:175resumed1214ms/15548raw/15588file/SHA4055c7a8a116c54f2f984bcd448f805fbf2f043942f9c1321e32c664a9910af7.

`tools.research.packed_resource_index_probe` executes original lookup on both real USB tables:15 valid/invalid/absent controls pass with no writes outside scratch stack. This is a separate scalar control, not MENU activation.

## Explicit exploratory index control

`--packed-index-usb-control` supplies ONLY the explicitly identified later USB index captures, marks/report hashes, and writes separate menu-activation-packed-index-usb-control.json. It cannot combine with auxiliary-object USB control. Main V9 baseline remains unchanged. Exploratory run reaches27602 instructions, stops at PC635b096/read3956b4. Original generic resource getter64be0f2 returns decoded payload3956a8 from resource207900+18; that unused cached resource header is captured but its decoded-object prefix is not. No later heap bytes are substituted.

## V10 prepared

V10 extends V9 with exact packed-index prefixes derived from each Sprite backing descriptor, under the SAME MENU CPU freeze. Encoding0/count/header/table guards fail closed for unproved encodings. Full capture stays bounded4096 records/512KiB raw; no arbitrary64KiB memory fill. It also captures64-byte decoded-object prefixes from unused ResourceData+18 (original getter contract), anticipating further original cached-resource reuse rather than one missing object per test. Type/owner/getter values are not fabricated.

Compiled Sony libc/-Werror;20500bytes/SHA3c62efc79b219859143c6d337c9d2903081feeedb7f90e05d6fb6223fcf6b54b. Exact uploaded readback verified. Final USB --preflight:509 resources, packed index7016/14040 captured,3 arenas156 fastbin chunks,2372 records197204 raw,175 attached/resumed1394ms/status0/flags0/PREFLIGHT0. Manifest native-packed-index-cache-preflight-e0123.json. MENU Sprite traversal/second backing await real capture; separately read headers and prefixes are validated above.

## Pending V10 PID888

V10 PID888/start0/flags0/wait_menu0/result0 verified;3600x500ms finite wait. Manifest native-layout-resource-snapshot-v10-armed.json. To provide sufficient tmpfs space, only own obsolete V8 binary and old partial PID2416 log were removed AFTER exact archive equality (V8 both outputs; V1 partial full log equality). Audit native-v10-space-cleanup.json. V9 binary retained; no SD changes.

User unplugUSB/no poweroff/MENU/hold10s/reconnect. FIRST preserve BOTH `/tmp_bt/native_layout_resource_snapshot_v10.log` and `.bin`; check PACKED_INDEX for both actual backings, SPRITE_RESOURCES0, IMAGE_CONTRACT, FASTBINS_END prefix_only1/result0, FREEZE allresumed, SNAPSHOT/BINARY/END0, exact version2 decode4096 cap. Stop `/tmp_bt/native_layout_resource_snapshot_v10.stop`.

After decode, prepare pid888 with --code-dependencies artifacts/hardware/native-menu-activation-dependencies-pid713.json and --code-dependencies artifacts/hardware/native-image-code-components-e0121.json. Replay WITHOUT any USB exploration flags. Repeated baseline25987 and exploratory27602 boundaries stable;15 original index controls pass; Python files compile. Existing571 suite passed E0122; no core/decoder change this round. No original UI originating thread/input mapping/full activation/rendering proven; no application calls/RAM patches/SD writes.
