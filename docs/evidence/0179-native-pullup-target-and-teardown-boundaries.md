# E0179 — Real USB Pullup Path and Hardened Backend

Date: 2026-11-08. Camera in Mass Storage. Continuation of E0178.

## Difference Between Software and Hardware Stop

Original `usb_gcw_stop` (`0x602bd834`) calls `change_gcw_state(1)` and returns 0. That is not an independent hardware confirmation. The backend already calls gadget `pullup(0)` before it; a strict check was added that real `gadget ops+0x14` points precisely to a6400 `dwc3_gadget_pullup` **0x602b1d3c**. Initial instructions of that function are included in native fingerprints.

`tools/native_camera/uvc_ptp_native_backend.c` checks that target before acquiring the backend context and again on every pullup call. Unknown targets or null ops are rejected. Changing the target during an active session retains the session and owned descriptors before any further native call; restoring the verified target allows cleanup to finish. These MOD guards were tested, not assumed from the function name.

## Execution of Original Pullup Body

`tools/research/probe_uvc_ptp_pullup_teardown.py` executes the original ARM instructions of pullup and GCW state functions from the SHA-verified kernel. **14 checks pass**.

For `pullup(0)`, the original sequence is: check busy opaque state, `stop_active_transfers`, disable EP0 out/in, possible disconnect notification, `run_stop(0)`, return its result. Endpoint arguments and propagation of `-110` error from the `run_stop` service were confirmed. Hardware services, locks, and notification are explicit replacements.

When the native busy bit remains set, the original code unlocks DWC, enables migration, and reaches reschedule before stopping transfers. No internal timeout counter was observed in that branch. Positive continuation in the test receives an **explicit external completion fixture**, not a fabricated hardware confirmation.

Therefore CPU freeze E0178 must not by itself become proof of a completed USB callback, nor may it be assumed that the entire teardown can execute while user executors are stopped. Native pullup may depend on completion of a previous request.

Report: `artifacts/analysis/uvc-ptp-pullup-e0179/manifest.json`.

## Build and Checks

Candidate `artifacts/native/uvc-ptp-module-e0179/usbg_video_a6400_shared_candidate.ko` was built, **58628 bytes**, SHA-256 `145ce31279ba172d1328d7369c74eea671fb78ce878696e854ffaca9f3b660b5`.

- **155** native backend ARM checks pass, including eight new target/retention/recovery checks.
- **29** structural and compiled module guard checks pass.
- **605** project tests pass in 14.781 s. The first attempt had four `PermissionError`s in temporary folders; the separate `...project-tests-restricted.log` was retained, and repeated tests with access to those folders passed without implementation changes.

## Bounded Physical Load Attempt

The inspected original init path registers the char device and initializes its objects; it does not register a UVC configuration. Only `insmod` was attempted without opening the video node and without an activation ioctl. The loader rejected the module: **Unknown symbol `__symbol_get`**. The init/exit cycle did not pass.

Manifest and full kernel log are in `artifacts/hardware/uvc-ptp-module-lifecycle-e0179`. The `.ko` was transferred only to `/tmp_bt` with byte-equal readback. `/proc/modules` before and after is byte-equal and the new module did not remain loaded. Debugger PID703 responds. There was no USB change or freeze cycle in this attempt.

It was established that `__symbol_get` is in the real **GPL-only** export table, even though its name and address exist in `kallsyms`. Earlier name presence checking did not check the export class. It must not be declared that all existing symbols automatically mean loadability. The fix and successful physical init/exit continue in E0180.
