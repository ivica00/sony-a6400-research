# E0199 — Kernel-owned stop snapshots and synchronous scope

## Implementation

Stop diagnostic request **version2** now requires the old registers/siginfo fields to be zero. Original sys_ptrace writes GETREGS/GETSIGINFO directly into kernel-owned stack buffers under a narrowly scoped target addr_limit override, restored on every return including native errors. User memory holds only the initial request/TID array and final receipt. TIDs are copied once before verification; later userspace mutation does not change the verified list. Legacy version1 is rejected by this candidate. Older module/helper artifacts retain their own version1 ABI.

Added `a6400_uvc_with_stops(argument,consumer,context)`. After all native membership/count/tracer/mode/signal checks succeed, it synchronously invokes the internal consumer with a const owner/count/kernel-TID scope. That scope expires when the call returns; no reusable userspace token is created. Diagnostic ioctl still supplies a null consumer, so **no native route is published**. The internal consumer API prepares same-call composition but is not yet wired to route lease or an ingress exclusion provider.

Kernel snapshots are explicitly initialized. The native snapshot adapter is noinline and has memory barriers/volatile addr_limit access around the native call. Initial ARM audit detected an incomplete optimized code path before physical execution; compiled control-flow/recording checks caught it. The corrected executable path passes native-call/return tests. This does not claim a general compiler defect diagnosis.

## Offline checks

Candidate `artifacts/native/uvc-ptp-module-e0199/usbg_video_a6400_shared_candidate.ko`: **63084bytes**, SHA-256 **cb55c58f3908e10919cc0c9d93c0432a1b89282f822d79b02af1de62235f7ab2**,52 verified imports/no GPL-only imports. **85 compiled ARM audit checks pass**. New checks assert native destinations are kernel-stack addresses with the expected temporary limit, restoration on failure, rejection of user scratch/version1, input-TID mutation survival, synchronous consumer scope values, consumer error propagation and invalid-scope consumer suppression. VFS/native ptrace are explicit recorders in these offline checks; the consumer is a typed MOD fixture.

All **605 tests pass in18.920s**. Logs `artifacts/uvc-ptp-module-e0199-{build,audit,tests}.log`.

## Physical test

New helper `artifacts/native/uvc-ptp-freeze-e0199/native_usb_freeze_probe.elf` uses version2 with zero scratch pointers:11312bytes,SHA-256 `c31bc37880138416f0b581ae9c8de1575b532f06b6f5b49315e848c7bf6a7fa1`. Runner accepts an explicit matching probe build.

First physical attempt stopped at device open with ENOMEM (errno12), **before any freeze or diagnostic**. Module/node/payload cleanup succeeded and module list restored. No allocator policy or camera configuration was changed. A single retry with identical binaries passed: **174/174 native checks,error0;174 attached/resumed in1369ms;allSIGSTOP;TracerPid0**. The module and temporary node/payload were removed; module list byte-equal restored, debugger703 responsive. Pre/post owner and TID observations match PID149 FD85/174threads/errors0.

Receipts: failed early-open `artifacts/hardware/uvc-ptp-kernel-scope-e0199`, successful `artifacts/hardware/uvc-ptp-kernel-scope-e0199-retry` and nested cpu; owners `uvc-ptp-owners-{pre,post}-scope-e0199`; comparison `artifacts/uvc-ptp-owners-scope-e0199-validation.json`.

Only the null-consumer diagnostic was exercised physically, not consumer-driven route publication. Camera remained MSC with no hook/activation/mode change. All writes/tmp_bt only; CPU helper/log remain in RAM.

## Remaining work

Need concrete global ingress/owner exclusion and route lease composition that retains code lifetime through publication/retirement and error recovery. Sequential proc membership/count is still not an atomic global snapshot, and no full VFS/IRQ/DMA drain is certified. Combined PC Remote+UVC/PTP test remains not ready; leave camera in MSC.
