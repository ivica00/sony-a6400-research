# E0165 — Original USB Active Flag Is Not a Full-Transaction Lock

Date: 2026-11-08. No camera access, uploads, or writes. Candidate E0164 remains unchanged and is not ready for physical test.

## Executed Original Code

`tools/research/probe_uvc_ptp_native_serialization.py` SHA-verifies original a6400 kernel (`12eeec829407595e28265f7d0db3b88c56f63a9f0fdd725c9c53c66a49643707`) and executes original `usb_gadgetcore_ioctl` at `0x602b8844` and original ARM atomic functions `_test_and_clear_bit` and `_test_and_set_bit`. It does not replace their decisions with host code.

17 checks pass. Result: `artifacts/analysis/uvc-ptp-serialization-e0165/manifest.json`. GC, gadget, ops, old root, and two stack regions are explicit fixture data. Get-speed service is an explicit stub. Pullup and `save_desc_tbl` are boundaries before which execution stops; controller and allocator are not executed.

| Original path | Observed sequence |
|---|---|
| Commit `0x400ce203` | `test_and_set_bit(2, gc+0x68)`; if already set, `-EBUSY`; else speed, `save_desc_tbl`, `gcw_start`, `pullup(1)` |
| Disconnect `0xe204` | `test_and_clear_bit(2, gc+0x68)`; if not set, return; else `pullup(0)`, `setup_disconnect`, `gcw_stop`, `free_desc_tbl` |

Other bits remain preserved. Notably: after clearing the active bit, and before the first `pullup(0)`, `gc+0x6c` still points to the old root. In an explicit interleaving test, a second call of the original commit path on a separate stack passes `test_and_set_bit`, sets active again, and reaches `save_desc_tbl` with the old root still present.

This proves that this flag alone does not provide mutual exclusion for the entire procedure. It does not prove that Sony's physical scheduler or callers actually permit that interleaving. External serialization remains an open question. It is not permitted to declare the active bit a mutex or use it as a reservation during our entire swap.

## Original User-Space Caller

Preserved a6400 `libInfraUsbCmn.so`, SHA-256 `5338bafbb545ebc223fac15c9253a41ac9fe49c01fe32c73af40c3fb50eec0a6`, export `CUsbSvc::stop_gadget` at Thumb `0x9c55`:

- `0x9c62` prepares ioctl `0xe204`, and `0x9c72` calls ioctl PLT `0x7b20`.
- `0x9c7a` prepares ioctl `0xe202`, and `0x9c80` calls ioctl again.
- Only at `0x9c84` does it prepare `this+0xa4` and at `0x9c8e` call `pthread_mutex_lock` via PLT `0x7b94`.
- `0x9d34` calls `pthread_mutex_unlock` via PLT `0x7af4`.

PLT targets were determined from their actual ARM add/add/ldr instructions and `.rel.plt`: GOT `0x1b950=ioctl`, `0x1b974=pthread_mutex_lock`, `0x1b944=pthread_mutex_unlock`. No assumption was made that all PLT entries have equal stride (Thumb interworking veneers prevent that).

Disassembly is preserved in `artifacts/analysis/uvc-ptp-serialization-e0165/original-userspace-callers.txt`. The trailing literal pool in that raw dump is not proof of executable code. The above instructions are in the actual function body. E0166 correction: `start_gadget` `0x9ed9` submits work through **CUsb::request**, PLT `0x7b10` / GOT `0x1b94c`. Earlier label `port_init` was wrong because it was obtained by assuming constant PLT stride rather than the actual target of that entry. Its external message queue and worker thread were not executed in E0165.

Mutex `this+0xa4` does not cover the listed disconnect ioctl in this body. It must not be taken as a shared guard for the kernel module without proof of external caller, lifetime, and all other USB entry points.

## Next Steps

Trace `CUsb::request` and `CUsbSvc` message queue to the actual executor of changes (continued in E0166). Determine whether shared configuration can be installed through the same original path or all original kernel entry points must be guarded. A standalone mutex in our module, the active bit, and spinlock `gc+0x30` are not interchangeable: the last protects different register/callback fields and must not be held across sleeping operations without proof.

No new project regression tests were run because the production candidate did not change. Previous E0164 result remains 605 passing tests. The new probe passes all 17 specific checks of original code.
