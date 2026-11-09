# E0198 — Native kernel thread membership physically verified

## New kernel checks

Extended the actual module stop diagnostic to validate each TID through native read-only procfs lookup `/proc/149/task/<tid>/status`. It uses normal exported filp_open/vfs_read/filp_close; actual retained export tables confirm these are normal, not GPL-only. It parses complete, unique numeric Tgid/Pid/Threads lines, requiring TGID149, PID equal to the supplied TID and current thread count equal to request.count. Missing/duplicate/malformed/truncated fields reject. The input list must contain leader149 in addition to existing uniqueness/bounds checks.

The proc read uses a bounded384-byte kernel buffer with the existing verified ARM thread_info addr_limit+8 convention. The previous address limit is restored immediately after vfs_read, before closing, including read-error paths. File open/read/close failures reject; successful opens always close. No private task_struct/refcount layout, GPL task-lookup export or module license change is introduced.

This changes owner149 from merely a declared field to per-TID native proc membership/status verification. It is still not a locked global owner snapshot or immutable kernel publication token. The first384 bytes contain required fields on the measured camera; absence in a future layout fails closed.

## Offline validation

Candidate `artifacts/native/uvc-ptp-module-e0198/usbg_video_a6400_shared_candidate.ko`, **62924bytes**, SHA-256 **989e76b3e1bb1691a83bf888b0820ba0b1afbced0c08a38cddd297e15a3f2bf1**, **52 verified imports**, no GPL-only imports. Original donor init/exit/instruction constraints remain audited. Shared mode activation remains disabled until native routing is properly published.

**79 compiled ARM module audit checks pass**, including wrong TGID/PID/thread count, missing leader, duplicate/missing fields, open/read/close errors, address-limit restoration and file-close tracking. VFS and sys_ptrace are explicit service doubles in this audit. Actual native proc/VFS/sys_ptrace behavior is covered separately by the physical test below. All **605 project tests pass in21.199s**. Logs `artifacts/uvc-ptp-module-e0198-{build,audit,tests}.log`.

## Physical test

Generalized the E0197 diagnostic runner to select build/audit directories, matching binary hash and enumeration/probe-only settings before loading. It continues using one shared host USB connection and no activation or publication command.

Exact candidate uploaded/readback verified and loaded. The existing E0197 helper opened the RAM character node and called only diagnostic0xc020f023 while tracing the Sony process. **174/174 completed, result0/error0**, **174 attached/resumed in1228ms**, all measured in ptrace_stop with SIGSTOP, TracerPid0 afterward. Module closed/unloaded successfully and its node/payload removed. `/proc/modules` byte-equal restored, debugger703 responsive. Fresh pre/post owner observations match PID149 FD85/174TIDs/errors0. Camera remains MSC; all filesystem writes `/tmp_bt` only.

Receipts: `artifacts/hardware/uvc-ptp-native-membership-e0198` (including nested cpu), `uvc-ptp-owners-{pre,post}-membership-e0198`; comparison `artifacts/uvc-ptp-owners-membership-e0198-validation.json`.

## Remaining scope

Per-TID status/count and original tracer checks now work physically, but their sequential observations do not exclude PID/TID replacement, a new device opener or future native calls. Userspace scratch can still be changed by another caller thread; no persistent publication authorization is granted. Need keep verified scope and route changes in one serialized protocol, including code lifetime and rollback, before actual native route publication. No fops/descriptor hook or USB mode change occurred. Combined PC Remote+UVC/PTP test is still not ready; leave camera in MSC.
