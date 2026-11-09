# E0115: V4 coupled capture archived; original resource-list unlink; libc arena boundary

- V4 PID2991 completed: MENU attempt141/object 0x4b94d8, RESOURCE_LIST 490 nodes,
  FREEZE 176/176 resumed, SNAPSHOT0/BINARY0/END0. Archived
  `artifacts/hardware/native-layout-resource-snapshot-pid2991.{log,bin,json}`;
  decoder: 1044 records, 171948 raw, 184492 file bytes, SHA3b7572bf...a379.
- `menu_activation_snapshot_probe --main-thread-control --active-state <pid2991.json>`
  previously stopped at 18990 instructions on a write to 0x1a27374c. Static
  Thumb disassembly of captured code 0x64c8300 shows an original doubly linked
  list unlink (`str next,[prev+4]`, `str prev,[next]`, then clearing the removed
  node's two link words at PC 0x64c831c/0x64c8322); loop at 0x64c858a is the
  list search. No value is invented.
- The write guard now admits ONLY those four store PCs, 4-byte size and bytes already
  captured. Result: 19068 instructions; unlink completes on node 0x2f8338.
- NEW boundary: original libc free (PC 0x431c9d0, node 0x2f8338, r2=0x43b8230)
  reads uncaptured libc data 0x43b8230 (arena/malloc state, not in V4 capture).
  Next: a native capture of that libc data page(s) with the thread freeze, then
  rerun. Do not fabricate arena contents. Activation not returned; no rendering
  has occurred; no GUI frame exists yet. No app calls/RAM patches/SD writes.

## Pending physical capture: V5 libc-data observer (PID3074)

- Cause: original libc free (PC 0x431c9d0) reads 0x43b8230. /proc/149/maps shows
  0x43b7000-0x43b8000 libc-2.11.2.so rw-p and 0x43b8000-0x43bb000 anonymous rw-p.
- `tools/native_camera/native_layout_resource_snapshot_v5.c` = V4 plus
  `capture_libc_data()`: captures those two ranges (0x1000 + 0x3000) under the same
  thread freeze, only if maps still reports exactly those mappings. Read-only, no
  app calls/RAM patches/SD writes. Output names use `_v5`.
- Built (-Werror, Sony libc, stripped) 13872 bytes, SHA256
  97f19e2659915ed08bc43d2b70caa943419cd60760edecc606a6e073c3cdbe23, uploaded to
  /setting/native_layout_resource_snapshot_v5.elf and read-back verified. Running as
  PID3074, wait_menu attempt0/result0, 95 available 4096-byte blocks.
- User action: unplug USB (no power off), open MENU, hold 10 s, reconnect.
- On callback FIRST preserve BOTH /tmp_bt/native_layout_resource_snapshot_v5.log and
  .bin; check LIBC_DATA line, FREEZE resumed, SNAPSHOT0/BINARY0/END0, decode with
  decode_native_layout_snapshot.py. Stop file: /tmp_bt/native_layout_resource_snapshot_v5.stop.
- Not atomic with DMA; arena data may disagree with the V4 snapshot in time, so
  replay must be built from the V5 capture alone.
