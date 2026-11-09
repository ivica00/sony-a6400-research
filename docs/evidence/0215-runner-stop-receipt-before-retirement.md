# E0215 — Require STOP and idle receipt before runner retirement

Date: 2026-11-09. Offline runner change only. No upload, camera access, activation or physical verification.

## Problem and behavior

Previously a returned STOP error only printed a warning before the runner proceeded to freeze PID149 and attempt entry-hook retirement. Later close/exit could invoke release and retry cleanup. A failed INIT could also leave partial state yet skip the explicit STOP phase.

The runner now marks INIT attempted before issuing it and performs the STOP check on either successful or failed INIT. The shared permission helper requires STOP result0, then status ioctl `0x8010f022` result0 and all four status fields zero: phase IDLE, module/session pin absent, descriptor hook mask empty, retained error absent. This receipt is permission to proceed to the separate native entry-hook retirement; it does not claim that hook has already been retired.

On failure the runner prints a RETAINED record, attempts its fresh RAM receipt copy, keeps the device FD open and waits without retiring the hook, closing the device or retrying cleanup. This is deliberate quarantine, not successful recovery. Killing/restarting that process would implicitly close the FD and remains outside this guarantee. Signals handled by the existing stop handler do not escape the retention loop. A blocked STOP or status ioctl never reaches this decision point: no timeout/cancellation is claimed, and the E0210 freeze is not fixed by this change alone.

Final `complete result=` output now agrees with whether INIT succeeded; a failed INIT no longer prints a misleading zero result.

## Validation

`uvc_ptp_runner_stop.h` is the actual policy included by the runner. New `probe_uvc_ptp_runner_stop.py` compiles and executes it as ARM with STOP/status scenario recorders. Eight cases pass: idle success; STOP error without subsequent status call; status error; ACTIVE; HELD; pin remaining; descriptor hooks remaining; retained error. Exactly one STOP and at most one status request are checked.

This verifies the compiled permission helper, not physical teardown, blocked calls, signal/FD lifetime or recovery receipt delivery. Source inspection verifies the retention branch precedes the runner's freeze/retire/close path. The full runner builds against Sony libc with warnings as errors. All612 general tests pass in17.186seconds.

Artifact: `artifacts/native/uvc-ptp-runner-e0215/uvc_ptp_session_runner.elf`,16048bytes, SHA-256 `2722e8229650c092e8a722ea70f6b94a1691eeccf8f078eced162ed0ca9bca6f`. Policy receipts: `artifacts/analysis/uvc-ptp-runner-stop-e0215/manifest.json`; regression log: `artifacts/uvc-ptp-runner-e0215-tests.log`. Build manifest includes the policy header hash.

## Outstanding

E0212 enumeration-only video-control rejection and E0211 stage traces remain offline. Need an observation path independent of a disconnected USB gadget and further callback/lock analysis before repeating a configured physical session. The camera last verified recovered MSC. No sensor or PTP control-transaction proof added.
