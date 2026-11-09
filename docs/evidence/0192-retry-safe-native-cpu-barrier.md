# E0192 — Retry-safe actual CPU barrier

Changed the actual shared camera helper `tools/native_camera/native_freeze.h`, used by native captures and the USB freeze probe. No camera access, deployment, hook or mode change occurred.

## Defect and correction

Previously freeze_resume attempted DETACH against every previously attached TID on every call, including successfully detached entries. freeze_process also reset attachment bookkeeping before checking whether an earlier partial resume still retained traced threads. This could lose the record needed for recovery.

The helper now keeps owned and stopped flags per attached TID. Successful detach clears only that entry. Failed detach retains ownership for retry, and a fresh freeze rejects with -100 if any prior ownership remains. A successfully attached thread whose stop was not yet observed is polled with waitpid before detach; missing stop retains ownership. An actual waitpid exit/signaled receipt clears ownership without trying to detach a dead thread. Other wait errors do not infer that a task is gone.

`freeze_recover_process` first retries release of every remaining owned TID. Only after that succeeds does it create a fresh CPU barrier, including re-enumeration and stop confirmation. Thus an old barrier is never assumed valid after partial resume. It still targets PID149 only; it does not discover other USB owners or prove cached VFS/kernel/IRQ/DMA drain. This is a concrete helper building block, not yet the route lease's full physical barrier provider.

## Validation

`native_freeze_contract_fixture.c` includes the actual changed header with explicit ptrace/wait/directory/clock/stdio doubles. `check_native_freeze_recovery.py` compiles and executes it as ARM in Unicorn. Assertions pass for partial detach failure, refusal to discard ownership, retry skipping already-detached TIDs, complete fresh freeze, partial-resume recovery, delayed stop and actual exit receipt without detach. These are injected offline failures, not operations performed on the camera.

```
python -m tools.research.check_native_freeze_recovery --output-dir artifacts/analysis/uvc-ptp-cpu-recovery-e0192
```

Actual camera probe also builds with the original Sony libc ABI and warnings as errors: `artifacts/native/uvc-ptp-freeze-e0192/native_usb_freeze_probe.elf`, 6888 bytes, SHA-256 `127e198960a2e0a1afebf77dec93f6c8f10bc4c3f0515f51b309fc32448d6d2b`. Built only, not deployed; E0178 physical proof applies to its earlier binary.

All **605 project tests pass in 17.580s**, log `artifacts/uvc-ptp-cpu-recovery-e0192-tests-retry.log`. Initial restricted run produced four temporary-directory PermissionErrors (log preserved separately); retry with appropriate local file access passed. This suite does not itself exercise physical ptrace recovery.

Next connect this retry-safe helper to complete owner inventory/attestation and route publication without treating saved user registers as kernel completion. E0182 remains the shared candidate and combined PC Remote+UVC/PTP test is not ready. Leave camera in Mass Storage.
