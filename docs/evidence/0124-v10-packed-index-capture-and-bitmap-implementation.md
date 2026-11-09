# E0124 — V10 packed indices and nested BitmapImpl

Date2026-11-06. Main-menu touch remains incomplete.

## Complete V10 PID888

BOTH outputs archived FIRST as native-layout-resource-snapshot-pid888.{log,bin,json}. Exact350224-byte binary/2447 records/320844 raw; SHAbb3eb2f6b0477f5ded345e0c5a2225d3c64dfb87e4ac162f8d83ef327989784d. MENU431/object004b94d8. Resource1a2cace0/ref1/owner6c880; unused492/nonzero0/activeabsent. Both packed index prefixes verified7016/14040 and750/1508;140Sprites22nonnull;3 arenas174 prefix-only fastbin chunks.176 attached/resumed1586ms; first attempt/SNAPSHOT/BINARY/END0. V10 helper finished; no V10 observer armed.

## Correct main-arena free guard

First replay stopped at18976/PC431c9ca because host guard unconditionally tried reading a nonmain heap header at(chunk&~fffff). Actual freed node362f8/chunk362f0 has original size flags11: this is libc MAIN arena. Original code at431ca4a loads PC-relative literal431ca7c, adds PC431ca50 and branches back to431c9ca, yielding actual43b8230 (already in V10 libc BSS capture).

Guard now distinguishes original chunk NON_MAIN_ARENA bit4, deriving nonmain arena from captured heap header, or main arena from the source-equal original literal/PC expression. Both must match actual original r6 and captured mutex bytes; existing exact CAS caller/store guards remain. No arena/return value is injected and no camera writes occur. This corrects an instrumentation assumption; original firmware did not perform an invalid page0 read.

Repeated V9 negative boundary still25987/read21baa830; V10 now reaches27902, beyond BOTH packed indices and decoded cached-resource prefix, without any exploratory USB input flags. Actual new boundary at original6392cfa reads nested object3437e8. Report menu-activation-v10-coupled-replay.json retains selected register/CPSR/provenance observations. Whole input outside captured CPU subset remains explicitly non-atomic.

## Proven nested image object

Captured resource207900+18 returns decoded object3956a8. Original635b0f0 loads decoded+18 ->3437e8, calls6392ce0, which dispatches virtual+44. Actual vtable7066cf0 has RTTI name `N3grm3bmp10BitmapImplE`. Actual slot44=63916bd. Metadata native-bitmap-type-e0124.json retains table and RTTI/name pointers.

Separate CPU-frozen USB native-image-backend-usb-e0124 capture: objects3437e8/256 and2198f0/128,384 raw424 file,175 resumed1114ms/SHA9b08f56d8e67b21680f0be341decf178b2266f3277ae6588ccc03552303d789a. NOT merged into V10 replay. Resource first word2198f0 is not established as a type descriptor/vtable; do not use it to classify all decoded objects.

Source-equal original lock code63916bc (512bytes compared to actual camera libObj ELF) uses embedded mutex+24 and condition+40, checks readiness via6391564, increments bitmap+18, and returns bitmap+8 through the output pointer. These are original methods, not a host graphics model. Lock/condition state must be captured; do not force success or return an invented buffer.

## V11 prepared

V11 inspects only bounded decoded-data+18 pointer candidates from unused cached resources and Sprite resources; accepts nested objects ONLY when their actual first word equals RTTI-verified BitmapImpl vtable7066cf0. Other data kinds/unreadable candidates are not assumed Bitmap objects. Captures each unique matched object128bytes (including original embedded mutex/condition), plus its table prefix256bytes. Bound1024 Bitmap candidates;4096 records/512KiB raw caps unchanged. Prefix capture is not pixel storage or DMA atomicity.

Final native USB preflight:509 resources/509 matched BitmapImpl objects,2872 records262036 raw;3 arenas151 prefix-only fastbin chunks;175 attached/resumed1634ms/status0/flags0/PREFLIGHT0/BITMAPS result0. MENU Sprite traversal/second backing still await physical capture. Manifest native-bitmap-preflight-final-e0124.json. Final Sony-libc/-Werror binary20608 bytes/SHAfe06a9109ec925463aa2f06319667b71ef9242773fc300cd91fabcadd5beee66; exact uploaded readback verified.

## Pending physical capture V11 PID1020

V11 PID1020/start0/flags0/wait_menu0/result0 verified;3600x500ms finite wait. Manifest native-layout-resource-snapshot-v11-armed.json. Only own obsolete V9 binary and V2-layout binary were removed AFTER BOTH associated outputs exactly matched PID713/PID2491 archives; audit native-v11-space-cleanup.json. V10 binary retained.

User unplugUSB/no poweroff/openMENU/hold10s/reconnect. FIRST preserve BOTH `/tmp_bt/native_layout_resource_snapshot_v11.log` and `.bin`. Require BITMAPS result0, PACKED_INDEX for actual backings, SPRITE_RESOURCES0, IMAGE_CONTRACT, FREEZE allresumed, FASTBINS_END prefix_only1/result0, SNAPSHOT/BINARY/END0, exact decode4096 bound. Stop `/tmp_bt/native_layout_resource_snapshot_v11.stop`.

Then prepare pid1020 with --code-dependencies artifacts/hardware/native-menu-activation-dependencies-pid888.json --code-dependencies artifacts/hardware/native-image-code-components-e0121.json --code-dependencies artifacts/hardware/native-bitmap-code-components-e0124.json. Replay WITHOUT USB exploration flags; use actual row state rather than blindly adding native-row-entry. No full activation/physical input mapping/originating UI thread/rendering proven. No app calls/RAM patches/SD writes. Validation this round: original main/nonmain replay controls and native build/readback/preflight;571-suite prior pass retained, core decoder unchanged.
