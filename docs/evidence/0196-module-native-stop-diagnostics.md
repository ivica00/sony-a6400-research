# E0196 — Module-native stop diagnostics

## Implementation

Added `uvc_ptp_stop_attest.{c,h}` and integrated it into the shared module builder/shim. Diagnostic ioctl **0xc020f023** accepts a versioned 32-byte request: version, declared owner, count, userspace TID array pointer, 72-byte register scratch pointer, 128-byte siginfo scratch pointer, completed count and error.

Only idle/releasable module state without pinned session/backend ownership accepts the diagnostic. It does not require or install the native route wrapper, does not touch native fops/descriptors and cannot activate USB. Existing local serialization/native reservation applies around the diagnostic and is released on idle completion/failure.

The routine validates version1/declared owner149, 1..512 positive unique TIDs, aligned nonnull pointers and overflow. It checks selected original sys_ptrace entry words at 0x6013f324, then calls that original kernel C function for GETREGS12 and GETSIGINFO0x4202 on every TID. The original syscall performs current-tracer/stop checks; returned register mode must be user16 and siginfo signal19. Error and completed count are copied back, including partial failures. No resume/detach operation is performed by this diagnostic; helper cleanup remains responsible.

## Limits

The owner149 field is declared scope, **not a native TGID/membership lookup**. Userspace scratch buffers are not an immutable kernel certificate and can be modified by another caller thread. The diagnostic intentionally grants no publication authorization or persistent attestation token. It does not discover new owners, prove kernel caller provenance or VFS/IRQ/DMA drain. Selected fingerprints are not complete live-kernel hash verification. Native sys_ptrace is a target-specific private address contract, not a new kernel export or GPL metadata change.

## Build and validation

Candidate `artifacts/native/uvc-ptp-module-e0196/usbg_video_a6400_shared_candidate.ko`: **61588 bytes**, SHA-256 **64b2518815dc08ea377ffcd39fc9a8014a3c596d4db068dc89c480b25b789347**, still49 verified imports with normal/GPL export classification enforced. Original donor init/exit and three documented reference instruction changes remain audited. Build flags still enumeration-only/probe-only/owned coherent allocation; deployable/physical_test_ready remain false.

Expanded module audit **62 checks pass** (E0182:48). New compiled ARM cases cover null request, two successful TIDs, reservation release, malformed version/scope/count, duplicate/zero TID, partial native error, nonuser registers, wrong signal, native fingerprint mismatch and rejection during ACTIVE. In this audit original sys_ptrace is an **explicit recorder** providing register/siginfo fixtures; native kernel checks are not executed here. E0183 original check_attach controls remain separate evidence, not end-to-end physical proof.

All **605 project tests pass in18.721s**. Logs: `artifacts/uvc-ptp-module-e0196-{build,audit,tests}.log`; audit manifest `artifacts/analysis/uvc-ptp-module-e0196/manifest.json`.

No camera access or upload occurred in this step. E0195 remains latest physical CPU receipt. Next build the helper-side diagnostic call and test it with the module while retaining MSC and without native route publication. Concrete full-owner membership/new-ingress exclusion and route lease integration remain open. Combined PC Remote+UVC/PTP test is not ready.
