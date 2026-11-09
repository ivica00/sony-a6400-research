# E0125 — V11 original bitmap round trips and Sprite element arrays

Date2026-11-06. Physical menu touch remains incomplete.

## Complete V11 PID1020

BOTH outputs preserved FIRST as native-layout-resource-snapshot-pid1020.{log,bin,json}. Exact417184-byte binary/2867 records/382764 raw; SHAe0133cf4d6bd141b6f2e42057c409ff41feb902917f2984a5f57e84ef4d5a6e5. MENU1132/object0e1a4008; active1a2cace0/ref1/owner6c880; unused492/nonzero0/activeabsent; both packed indices;140Sprites22nonnull;3 arenas129 prefix-only fastbin chunks;509 BitmapImpl objects.176 attached/resumed1393ms; first attempt/SNAPSHOT/BINARY/END0. V11 finished, no V11 observer armed.

## Original BitmapImpl operations now execute

Initial27949 boundary was ORIGINAL pthread mutex CAS into actual BitmapImpl+24; only verified captured BitmapImpl objects entering original lock63916bc register these mutexes. Scoped writes now admit:

- pthread lock owner/users at407fbea/407fbee (mutex+8/+10).
- pthread unlock owner/users at4080d20/4080d50.
- mutex kuser CAS only LR407fbdd/4080d3d.
- original BitmapImpl counter+18 at639173a (increment) and639106c (decrement).
- embedded condition+40 kuser CAS only LR408224d/40822e7, original no-waiter broadcast branch.

No general heap writes or fake lock returns. Actual owner149 derives from captured main-thread TLS, not a host-assigned owner. No forced syscall/wakeup reply. Generic ResourceData acquisition64bdfd8/64bdfe0 now has captured-owner6c880/known-byte/positive-capacity guard and exact original +1 verification; overflowffff stops. Release positive-count invariant and exact original decrement remain. This permits new resource207900 acquisition by original code rather than forcing its count.

Observed FOUR original bitmap lock/unlock round trips across FOUR objects. Counter+18, mutex lock/owner/users+24/+2c/+34 and condition internal lock+40 ALL restored to their own captured initial values. Per-object observations and call counts in menu-activation-v11-bitmap-geometry-boundary.json. Buffer return pointer is actual bitmap+8, not supplied by host.

Original code continued through image refresh to40181 instructions. One additional16-byte type-metadata window706c0a0 was read later via USB (ELF .data.rel.ro, explicitly non-atomic);5e17dbc and631dea0 code were camera/file-equal captured. Whole input still NOT claimed atomic. V12 will capture the relevant type-table window in the same freeze.

## Precise new boundary: Sprite elements, not a parent widget

Stop PC6305f6e/read2788a7e8. This instruction is VFP `vldr s14,[r0]`, part of original two-float comparison, NOT a vtable read. Later USB memory starts with zero floats; do not interpret this as a missing vtable or infer an ancestor widget.

Source captured pointer is MENU+127f4 = first Sprite+88. Original631dea0 reads uint16 Sprite+8e, checks index<count, then computes pointer(Sprite+88)+index*0x2c and calls6306384. Original6305f6e compares first two float fields;630639c writes actual supplied two-float value only if different, then marks original object dirty. This proves bounded element stride44, not the identity/meaning of every other field.

Across retained V11 full-menu bytes:115 unique nonempty element buffers,43428 total bytes, counts bounded256. native-sprite-element-ranges-e0125.json retains exact source hash/ranges. Two separate CPU-frozen USB readability captures (NOT merged into MENU replay):

- native-sprite-elements-usb-e0125-part1:64 records23936raw/24720file,175resumed1203ms/SHA4cc36aa9801d2febc9c3a1f5599da4fb46e672c022ced80ce8f710eab1198388.
- part2:51 records19492raw/20120file,175resumed1416ms/SHA4a8a6ccb87d7b2c70861c1df26d2e5731677bac5044764c70740b4d58d30dc60.

## V12 prepared and pending

V12 adds same-freeze capture of Sprite+88 arrays sized actual uint16+8e *44, including Sprites with null image resource. Scan bound expanded to full0x90 Sprite member prefix;256 elements per candidate;4096 records/512KiB raw unchanged. Reports SPRITE_ELEMENTS and SPRITE_ELEMENT_SUMMARY. Adds actual type-table window706c090/0x80 covering the new immutable-type metadata dependency. No generated coordinates or firmware replies.

Final build Sony libc/-Werror,20608bytes, SHAb1d79a271487d92be8b55517955b824efaeb3c8c9d4f332772316605f7132e3c; exact uploaded readback verified. Final USB --preflight:509 Bitmap objects,2861 records262116 raw,175 attached/resumed1468ms/status0/flags0/PREFLIGHT0. MENU array traversal remains pending; separately retained-array addresses all readable as above. Manifest native-sprite-elements-preflight-final-e0125.json.

V12 PID1175/start0/flags0/wait_menu0/result0 verified;3600x500ms finite wait. Manifest native-layout-resource-snapshot-v12-armed.json. To preserve sufficient tmpfs capacity, only own completed helper outputs were removed AFTER exact archive equality: old V3..V10 logs, V10 binary, latest standalone bounded binary; old controller/mouse logs were additionally fully archived and second-read equality verified before removal.433436 bytes removed; audit native-v12-space-cleanup.json. V11 BOTH outputs retained. No application/SD files removed.

User unplugUSB/no poweroff/MENU/hold10s/reconnect. FIRST preserve BOTH `/tmp_bt/native_layout_resource_snapshot_v12.log` and `.bin`; require SPRITE_ELEMENT_SUMMARY0, BITMAPS0, SPRITE_RESOURCES0, PACKED_INDEX both, IMAGE_CONTRACT, FREEZE allresumed, FASTBINS_END prefix_only1/result0, SNAPSHOT/BINARY/END0 and exact decode4096 limit. Stop `/tmp_bt/native_layout_resource_snapshot_v12.stop`.

Then prepare pid1175 with --code-dependencies artifacts/hardware/native-menu-activation-dependencies-pid1020.json --code-dependencies artifacts/hardware/native-image-code-components-e0121.json --code-dependencies artifacts/hardware/native-bitmap-code-components-e0124.json. Replay WITHOUT USB controls. At next geometry write, verify actual array provenance/element boundary and exact original setter PC before admitting any external array mutation. Full activation not returned; physical event mapping/UI origin/rendered popup unproven. No camera application calls/RAM patches/SD writes. Validation: repeated40181 boundary;4 bitmap roundtrips restored; native build/readback/preflight; Python compile.571-suite prior pass retained, decoder/core unchanged.
