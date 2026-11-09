# E0122 — V8 coupled image path and Sprite references

Date2026-11-06. Physical main-menu touch remains incomplete.

## V8 PID588 returned complete

Both outputs preserved FIRST as native-layout-resource-snapshot-pid588.{log,bin,json}. Exact298404 bytes/2015 records/274208 raw. SHA256 `f89e8d576f7483390d49c475c65c96c094787e497b87b72d4dffc72f5aaf057e`. MENU272/object0e1a4008, active1a2cace0/ref1/owner6c880; unused492/nonzero0/activeabsent; IMAGE_CONTRACT valid; three arenas231 prefix-only fastbin chunks.176 attached/resumed1420ms, first capture successful, SNAPSHOT/BINARY/END0. No V8 observer remains armed.

Prepared from this capture plus ONLY source-equal original code dependencies. WITHOUT auxiliary-usb-control, original activation passes E0121 manager/accessor/GOT/callback/backing reads and reaches25447 instructions. Original allocation/resource/list behavior still verified. New boundary PC64c0518 reads26e46910. Report menu-activation-coupled-state-probe.json includes boundary pointer provenance and selected call-register/CPSR observations.

## Actual next resource, not an interpreter workaround

Original getter6359720 uses Sprite+0x48. MENU contains Sprite subobject at+127fc (0e1b6804), whose+48 is resource26e46900; its payload view is resource+10=26e46910. This resource is in use and absent from the unused-resource list, so V8 did not capture its header. New requested ID205cc10 is observed from original code, not used as a guessed physical key/action ID.

An apparent argument-register mismatch was investigated before changing CPU semantics: entry64c33b8 actually receives26e46910;64c33bc copies it to r4,64c33c6 copies r4 to r1, and pop restores the caller's r4. CPSR1f3 has no IT bits. The call is correct; NO stale-IT patch or register forcing was added.

RTTI for vtable70640e0 identifies `N2ux6gfxeng6SpriteE` (RTTI70640c8). Bounded scan of the already captured full menu yields140 vtable-matching subobjects and17 UNIQUE nonnull resource addresses. native-menu-sprite-references-e0122.json retains every offset/reference and source capture hash. These are capture candidates validated against original type/getter/owner; no host menu decisions are substituted.

## Targeted V9 capture

V9 captures every matching Sprite's nonnull resource64-byte header (owner must equal6c880), pointed blob prefix+10/64 bytes and decoded-image prefix+18/64 bytes in the SAME MENU CPU freeze. Null slots are retained as observed. Same-address records deduplicate. Limit256 Sprite candidates; full menu bounds required. Prefixes are not whole image/GPU buffer snapshots.

V8 was already2015 records, near2048. V9 and decoder now allow4096 records while keeping512KiB raw bound, record/user-address bounds, exact binary length and conflicting-overlap rejection. Version2 layout is unchanged; maximum envelope573456 bytes fits600000-byte callback archive cap. Five decoder tests verify4096-record roundtrip,4097 rejection, conflicting overlaps, truncation and user-address rejection. Full571 unittest tests pass with normal host temp access.

## Verification before physical test

Native V9 --preflight (USB mode, NO MENU Sprite traversal) passed:509 unused entries,3 arenas226 fastbin chunks,2001 records155252 raw,175 attached/resumed1353ms/status0/flags0/PREFLIGHT0. Manifest native-sprite-resource-preflight-e0122.json explicitly marks Sprite-menu traversal unexercised.

Separately CPU-frozen USB reads verify all17 retained Sprite reference addresses have owner6c880 and all17 distinct nonnull decoded-image prefixes are readable. These later-phase bytes are NOT merged into active-MENU replay:

- native-sprite-reference-headers-usb-e0122:17 records1088raw/1308file,175resumed1251ms, SHA02b534983bb973f0f642207629c0bc3b5bd58d02648d8e85b8da9366df074380.
- native-sprite-image-prefixes-usb-e0122:17 records1088raw/1308file,175resumed1394ms, SHAcc9111791123e4745bb8cdf2020e97bc0aa597205abf91c6c111ab1d5d88f73c.

V9 compiles with Sony libc/-Werror,20500bytes, SHA2feabedbce3da06ac89012a2be577fe4c54cdd9cc805cc7644ef47634f4707b2. Exact uploaded readback verified.

## Pending physical capture PID713

V9 PID713/start0/flags0/wait_menu0/result0 verified;3600x500ms finite wait. Manifest native-layout-resource-snapshot-v9-armed.json. Only own obsolete V7 binary removed AFTER BOTH outputs exactly matched PID4015 archives; audit native-v9-space-cleanup.json. V8 binary retained.

User unplugUSB/no poweroff/MENU/hold10s/reconnect. FIRST preserve BOTH `/tmp_bt/native_layout_resource_snapshot_v9.log` and `.bin`, require SPRITE_RESOURCES result0, IMAGE_CONTRACT, FASTBINS_END prefix_only1/result0, FREEZE allresumed, SNAPSHOT/BINARY/END0; decode exact version2 binary with revised4096 limit. Stop `/tmp_bt/native_layout_resource_snapshot_v9.stop`.

Then prepare pid713 with --code-dependencies artifacts/hardware/native-menu-activation-dependencies-pid588.json and --code-dependencies artifacts/hardware/native-image-code-components-e0121.json. Replay actual capture WITHOUT auxiliary-usb-control; no native-row-entry needed if actual flag0/row0. No application calls/RAM patches/SD writes; physical event mapping, originating UI thread, full activation and rendering still unproven.
