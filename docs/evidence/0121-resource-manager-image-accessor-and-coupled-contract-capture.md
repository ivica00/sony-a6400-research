# E0121 — ResourceManager, image accessor and targeted coupled capture

Date2026-11-06. Physical menu touch incomplete.

## Identified original objects

The auxiliary object69f00 is NOT an unidentified notification service: vtable706c418 has RTTI706c400/name `N5libra19ResourceManagerImplE` (name pointer6cfbac5). Original getter64b6ac4 reads its+3c, yielding69edc. That object has vtable7064ce0, whose RTTI7064d18 names `N2ux4core11DevAccessorE`; its base RTTI7064cd0 names `N5libra19ImageHandleAccessorE`. Actual camera RTTI/table reads are retained in native-auxiliary-rtti-e0121.json and native-image-handle-accessor-code-e0121.json; derived name was read directly on-camera. Base and derived class identities must not be conflated.

Virtual+8 calls6355f5e, which forwards the actual image handle to original635a170; that getter reads handle+0xc. Code checked byte-equal to actual camera libObj ELF. Original virtual+0xc and related image properties also execute in the exploratory control. No host reply is supplied.

Actual ELF section metadata identifies libObj `.got` at7082c60/39520bytes (0x9a60). All earlier module indirection reads70836d4/7087c7c/708c244/708a52c belong to this section. This supports capturing the ENTIRE bounded original GOT under the MENU freeze, instead of later per-word USB substitutions. Actual ELF dynamic symbol table was archived; nearest exported symbols do not identify these private methods.

## Separate exploratory USB control

`--auxiliary-usb-control` explicitly adds separately retained USB manager/accessor objects, source-equal code, full GOT, and callback table. It writes a DIFFERENT report `menu-activation-auxiliary-usb-control.json`, marks the input exploratory and non-atomic, and records input file hashes. Original V7 baseline is unchanged at24638 instructions/read69f3c.

Additional native frozen USB captures (all records bounded; all175 threads resumed):

- native-auxiliary-contract-usb-e0121:432 raw/472 binary/1245ms/SHA12ff9a332be3b5e317592c8b95502b3d006d094d0b916047d9143bd403d1c7eb.
- native-libobj-got-usb-e0121:39520 raw/39548 binary/1369ms/SHA8297b0c594dfe536258c6d0ad99dec8b561f12cf3bd031045871184f47445e30.
- native-image-callback-usb-e0121:260 raw/300 binary/1240ms/SHA48e81cbb8ba0dcafb4ade9e693368a6a6de104d1af19eb52ecb24e4f4c8084d7.

The global7108114 points to callback table71081d8. Original routine6356690 loads callback+60 (actual635d319) and calls it. Exploratory execution reaches25311 instructions, stops at original64b55e2 reading14bcc4. This is not coherent active-MENU success. Pointer14bcc0 comes from captured resource header+14 (including active1a2cace0), not from global710f9d8. Original64c0f1c uses710f9d8 only as a COMPARISON SENTINEL. Do not treat the zero at that address as a missing service to fabricate.

Original64b55de reads resource-backing-object+4, actual6d1bc in USB. The classes/size of these two objects are unproved; capture bounded actual prefixes, do not generalize that field layout to every resource kind.

## V8 prepared and checked

`native_layout_resource_snapshot_v8.c` adds, in the SAME CPU freeze: manager69f00/0x60 with vtable/owner guards, actual+3c accessor and table, full ELF-proven GOT7082c60/0x9a60, global7108114 and actual callback table/0x100, comparison sentinel710f9d8/16, actual active-resource+14 backing prefix/0x80 and its+4 target/0x80. All V7 data remain. No general service/heap fabrication.

Preflight rejected two unsafe assumptions before physical testing: treating710f9d8 as service pointer returned-167; applying backing+4 layout to ALL resource kinds returned-171. Each run resumed all175 threads. Corrected code follows the backing only for the actually active, already proven resource. Final preflight: status0/flags0/PREFLIGHT0,509 unused entries,3 arenas202 fastbin chunks,1953 records153788 raw,175 attached/resumed1369ms. Manifest `native-image-contract-preflight-verified-e0121.json`.

Build helper `tools.research.build_native_snapshot_observer v8` pins source/start/barrier/binary hashes in ignored build manifest. Sony libc, -Wall/-Wextra/-Werror; final binary20500bytes, SHA4b247292031d53a93cedb97e93bf61d116be918515f5277d977efd01961afcc9. Exact uploaded readback verified.

## Pending V8 PID588

PID588/start0/flags0/wait_menu0/result0 verified,104 available4096-byte blocks,3600x500ms finite wait. Manifest native-layout-resource-snapshot-v8-armed.json. Only obsolete own V6 binary removed AFTER BOTH outputs exactly matched PID3939 archives; audit native-v8-space-cleanup.json. V7 retained.

User unplugUSB/no poweroff/openMENU/hold10s/reconnect. FIRST preserve BOTH `/tmp_bt/native_layout_resource_snapshot_v8.log` and `.bin`; require IMAGE_CONTRACT, FASTBINS_END prefix_only1/result0, all frozen CPU threads resumed, SNAPSHOT/BINARY/END0 and exact binary decode. Stop `/tmp_bt/native_layout_resource_snapshot_v8.stop`.

After decoding actual PID588:

```powershell
python -m tools.research.prepare_active_menu_control pid588 --code-dependencies artifacts/hardware/native-menu-activation-dependencies-pid4015.json --code-dependencies artifacts/hardware/native-image-code-components-e0121.json
python -m tools.research.menu_activation_snapshot_probe --main-thread-control --active-state artifacts/hardware/native-layout-resource-snapshot-pid588.json
```

Do NOT use auxiliary-usb-control for the coupled V8 result. New code-dependency options import ONLY source-equal code records and validate present hashes; USB heap/GOT data are not imported by that option. Thread-count check now requires actual positive equal attached/resumed counts rather than hardcoding176. Missing code can be captured with --code-only; it stops before fetching missing data. Python files compile; actual repeated baseline24638 and exploratory25311 boundaries stable. No physical input map, UI originating thread, full activation or rendered popup proven. No application calls/RAM patches/SD writes.
