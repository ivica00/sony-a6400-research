# E0220 — Native file API contracts and live volume table

Date: 2026-11-09. User authorization for a small SD journal persists (E0219). No SD/NAND write, native filesystem call, mount, UVC activation or module change occurred.

## Static source evidence

Ghidra12.1.4 queried exact original libInfraFsys.so bodies, SHA75f24fd03f4a187563622d6320f0690108fa6e231ac6e84cbda9303b8dc9af2c. Static evidence is retained under `artifacts/tools/rea/fsys-journal-exact-e0220`, `fsys-volume-e0220` and `fsys-path-exact-e0220`. Ambiguous name queries initially matched PLT and actual functions; retries used exact body addresses. Retain failed batch manifests; the two successful volume queries preceding that batch's failure remain separately recorded.

- `Fsys_Open(path, out_handle, flags)` returns status; the handle is written separately. An uninitialized service returns0x80000010. Create flag branch0x04 can reopen an existing file after already-exists status0x80000022; it is **not** O_EXCL. Truncate and create+truncate are separate modes. Never map guessed POSIX flags directly onto this API.
- `Fsys_WriteAndFlush(handle, buffer, size)` checks service state, buffer, nonnegative size, live handle/drive membership, device state, writable flags and device locks before lower writes. Its name alone does not prove power-loss durability.
- `Fsys_Flush` invokes lower fsync and then buffering; the decompiled original body does not use the lower fsync return directly when deciding final status. Do not treat returned0 as a complete lower-storage durability certificate without tracing/validation.
- `fsys_GetDriveInfoFromPath` recognizes normalized drive-letter prefixes and a separate device-path form. Successful resolution acquires and retains the device lock for the caller; it is not a harmless standalone path lookup.
- `Fsys_GetMountDrives` reads a native drive-pointer bitmask under a global mutex. It does not return Linux mount paths. `Fsys_GetDriveLetter` depends on existing device identity and locking.

These are static reconstructed contracts, not all tested positive paths or complete C prototypes. No private filesystem instance was initialized.

## Original ARM rejection checks

New `tools/research/probe_uvc_sd_fsys_guards.py` loads the hash-pinned original ELF with explicit GOT fixture resolution and executes nine original Thumb API guard cases: Open uninitialized/null path/null output/rejecting drive lookup; WriteAndFlush uninitialized/null buffer/negative size; Flush and Close uninitialized. Expected error codes and output-handle preservation/clearing pass. Logs and rejecting lookup are explicit service doubles; no successful open, write, lock, mount or flush is synthesized.

Manifest: `artifacts/analysis/uvc-sd-fsys-guards-e0220/manifest.json`. This isolated tool did not change runtime module/runner code; last full612general tests remain E0215.

## Physical read-only observation in MSC

Read PID149 maps, native status,26drive pointers and a16-byte Fsys_Open prefix through the existing debugger. Correct load bias is0x04cde000; the data segment has a different file-offset/vaddr relationship, so naive start-minus-file-offset on every map gives a false alternative bias. The observed Open prefix matches source. This is prefix verification, **not** full live-library hash equality.

`g_fsysStatus=1`, all26letter-drive pointers zero in this sequential MSC snapshot. That means no letter volume was observed then, not that SD is absent, globally unused, or unavailable in shooting/PCRemote. The memory debugger temporarily attaches/detaches the leader for reads; no function call or memory write was issued. Follow-up `/proc/149/status` confirms TracerPid0,175threads. Artifacts: `artifacts/hardware/uvc-sd-volumes-e0220/`.

## Next

Observe native volume registration during ordinary PCRemote/shooting and identify existing service ownership before creating the one authorized, uniquely named journal file. Establish a non-overwrite contract, bounded size and flush/readback validation. Do not call native path lookup just to discover a name while ignoring its retained lock, use a separate uninitialized filesystem stack, or mount the card for writing alongside Sony. Persistent logging is still not ready; no new configured UVC test was performed.
