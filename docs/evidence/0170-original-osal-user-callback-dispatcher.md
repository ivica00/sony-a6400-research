# E0170 — Original OSAL User Callback Dispatcher

Date: 2026-11-08. Offline continuation of E0169. No camera access or production module changes.

## Sources and Execution

The new `tools/research/probe_uvc_ptp_osal_dispatch.py` executes the original registration path in a6400 `libosal_uipc.so`, the original callback worker, and the original registered USB callback from `libUsbControl.so` in a separate address region. Both libraries and ELF relocations were verified before execution.

| Source | SHA-256 |
|---|---|
| libosal_uipc.so | b6ded35add9582413b401cf4db78ec2c9a201b632e78c2731d6bbb379249b3eb |
| libUsbControl.so | 70cd5742fde9eea78c60905e4015531b4c3ab2668d2cb85c934531f451f1211f |

## Sony Notification Registration

Original `osal_reg_msg_queue_cb` at `0x4301` checks bit `0x8000` of the ID. For the actual static ID from E0169, `0x00e942cd`, the bit is not set: the original code goes to `u_osal_reg_msg_queue_cb` at `0x2749`, rather than the local callback-list path.

That path prepares ioctl `0x80000008`: the outer pair is `{queue_id, pointer_to_stack_fields}`, and the inner data is `{output_handle_pointer, callback_pointer, user_argument, 0}`. The test verifies the exact ID, callback, argument, and packet layout, and stops before the ioctl service. Kernel registration and worker thread creation were not executed.

Negative local ID and local ID with a null callback return `0xfffffc00` from original guards. These are separate negative checks; they do not represent an error on the real Sony ID.

## Worker

Static inspection of the original path at `0x1c58..0x1c66` prepares `pthread_create` and computes start routine `0x2031`. The actual PLT relocation for `pthread_create` and the literal yielding the start address were verified. `pthread_create` itself was not executed and there is no confirmation of a physical TID.

Original routine `0x2031` requests work via ioctl `0x8000000d`. The pair passed to the ioctl is `{0, pointer_to_16_byte_descriptor}`. The returned descriptor has the layout:

| Offset | Originally Used Field |
|---|---|
| +0 | callback function |
| +4 | callback r1 |
| +8 | callback r0 |
| +12 | worker index, given at startup |

For an explicit kernel-output fixture, the worker calls the real USB callback `0x131a5` from the other library with exact arguments. The callback loads `{operation=1, status=-5}`, passes them to the message builder (explicit service replacement), and then passes the original message to `osal_free_msg` (explicit replacement) for ID `0x00e942cd`. Only after the callback returns does the original worker re-enter ioctl `0x8000000d`. The second ioctl is the stop boundary.

The test also verifies the original retry branch on `-1021`: the callback does not execute before a successful second receive, the worker index remains preserved, and a new wait request follows after the callback.

The original worker can therefore execute the callback independently of the `Main` loop from E0169. This is proof of an intended separate executor in code, not proof of the current distribution of physical threads, a single worker, or complete protection of USB mode changes.

## Kernel Boundary for Further Verification

Static inspection of original a6400 `osal_uipc.ko` (previously retained SHA-256 `3743275bc964a2804b80cde4f589f60876b795fbeeccd3cbf2c18a0da2dc8567`) identifies `__k_4u_wait_cb` at `.text+0xe8c`. The next wait call processes the previous callback recorded in the per-worker slot, followed by new work. In that path there are branches toward `wake_up_process` or `finish_callback`. `unreg_msg_queue_cb` and a helper at `.text+0x27a0` use additional callback flags and waiting. These kernel bodies were not executed in E0170: it must not be assumed that unregister automatically means a completed callback or that merely removing the user pointer is sufficient.

## Result and Boundaries

**16 checks pass**. Manifest: `artifacts/analysis/uvc-ptp-osal-e0170/manifest.json`; log: `artifacts/uvc-ptp-osal-e0170.log`.

The kernel ioctl response, file descriptor 17, worker index 3, and message are explicit fixture data. Naming/cancellation/memset, `ObjMsg` builder, and free services are explicit replacements. Original libraries decide branches, argument layout, callback return, and retry. Guards reject unexpected execution and writes. There is no physical registration, scheduler, or kernel cleanup in this test.

The next concrete check is kernel confirmation of completion of the previous callback and unregister behavior while a callback is active. E0164 remains unloaded and `physical_test_ready:false`. There is no new sensor UVC evidence; the last full project regression remains 605 tests because the production module was not modified.
