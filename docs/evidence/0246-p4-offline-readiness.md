# E0246 — P4-0 offline readiness: rebuilt stop-attested runner, receipt policy and strict session mode

Date: 2026-11-09. Offline only: no camera access, no module load, no UVC activation.

## Runner rebuild

- Current source `tools/native_camera/uvc_ptp_session_runner.c` SHA-256 `935dbb4caa67a7f651c007541fac76ade68794079b38241da151ab719f861fcc` (11,678 B).
- Built with the project's flags (Sony libc, `-nostdlib`, dynamic linker `/lib/ld-linux.so.3`) into `artifacts/native/uvc-ptp-runner-p4/uvc_ptp_session_runner.elf`, 16,048 B, SHA-256 `a7c1b4ea397797044877976120b626a82f38cf7d0f6307f615c1b13d2c4af47e`; manifest records the exact command and all input hashes.
- The ELF contains the current teardown markers: `STEP 3: Composite session stopped; IDLE/unpinned/no hooks/no error verified`, `STEP 4: Entry hook retired`, `SESSION_RUNNER RETAINED ... no retire/close/retry` and `SESSION_RUNNER complete result=%d`.
- The previous runner build (e0208) was stale: source `0f7a33ed…`/9,949 B vs current `935dbb4c…`/11,678 B; it is not used for P4.

## Receipt policy

- New pure module `tools/research/p4_policy.py`:
  - `evaluate_preflight`: audit passed and audit module SHA matches, identities present, `usbg_video` not already loaded, `TracerPid: 0`.
  - `evaluate_receipt`: requires `IOCTL_UVC_INIT returned ret=0`, the stop-verified STEP 3 line, the retired STEP 4 line and `SESSION_RUNNER complete result=0`, in order; rejects `SESSION_RUNNER RETAINED`, `CRITICAL ` and `FAIL `.
  - `evaluate_after`: module list byte-equal, `usbg_video` absent, uptime monotonic (reboot detection), receipt verified.
- 12 focused tests in `tests/test_p4_policy.py`: success, each missing marker, each forbidden marker, out-of-order, empty/missing receipt, preflight audit/identity/loaded/tracer failures, after module/reboot/receipt failures, uptime and module helpers.

## Strict session mode

`run_uvc_ptp_session_test.py --p4`:

- Defaults (when the historical e0206/e0206/e0208 args are not overridden): module **e0212**, audit **e0212**, runner **uvc-ptp-runner-p4**, **duration 60 s**, **MSC wait 120 s**.
- Verifies the module build manifest SHA/size and the runner build identity; verifies the audit status and module SHA; p4 preflight gate aborts before `insmod` if not clean; records uptime before/after and the four policy results.
- On cleanup, the receipt policy must pass before `rmmod`; a failure preserves the module and records `teardown_unconfirmed` (no clean-unload claim); a missing MSC reconnect prints restart instructions; success is only `p4_session_completed` when receipt and after policies pass and the module list is restored.

## Checks

- `python -m py_compile` passes for the policy and session tool.
- Full suite: **636 tests pass in 17.591 s** (624 previous + 12 policy tests).
- No camera contact; the module and runner are built but not deployed.

## Boundary

This is readiness, not a session. The P4a module load/unload smoke test and P4b 60-second enumeration/teardown run remain user-gated physical steps. The 60 s hold is an assumption for Windows enumeration (E0210 first reported the healthy UVC child at ~40.6 s); a session that does not enumerate still stops and is recorded as such.

## Next

P4a: `insmod`/`rmmod` of e0212 only, no INIT, verify module list and dmesg. Then P4b with the rebuilt runner and strict policy.
