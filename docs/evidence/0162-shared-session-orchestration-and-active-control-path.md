# E0162: Shared Session, Registration, and Control Path

Date: 2026-11-08. Continuation of E0161. No camera access in this step.

## Wired Candidate

`tools/native_camera/uvc_ptp_session.{c,h}` wires the existing bridge, endpoint 82 selector, descriptor validator, and ownership lease into a shared ARM procedure. Hardware backend is not implemented in this file.

Begin preflight requires:

- Original native PC Remote HS table: `054c:0caa`, device class 0, one configuration/interface 0, PTP `06/01/01`, channels `81/02/83` with E0153 parameters.
- Verified candidate and reference interfaces 1/2, config 1, START/STOP/CLASS.
- Caller-verified reference MOD for wire 1/2 + video 82. The session helper itself does not verify callback code hash; the module/builder must ensure that.
- Caller serialization and pinned source/reference/ops lifetime.

Then executes in order: quiesce -> bridge prepare -> shadow register 1/2 -> native descriptor lease install/validate -> EP0 bind -> resume. All operations must produce real results in the future hardware backend. The original PTP descriptor is not an argument of any register/unregister operation.

End executes: quiesce -> check bridge started/in-flight zero -> EP0 unbind -> unregister 2/1/bridge retire -> native descriptor free/restore -> restore original flags/mode -> resume. If resume may be partial, a retry requires quiesce again. EP0 unbind must be idempotent even after a failed/partial bind attempt.

## Errors and Memory Retention

Any error after the first mutation goes through the same reverse cleanup path. Quiesce/unbind/restore/resume errors leave `HELD` state. In-flight or started bridge also blocks freeing: backend ack alone is not proof that native users have retired. Lease quarantine does not release template.

`session_releasable` requires `IDLE`, no pending stop/prepared/registered/hook state, no bridge magic/in-flight users, and empty lease. This is an API for future module-unload protection, not an already installed unload hook.

## What Actually Executed

Builder `build_uvc_ptp_descriptor_lease --session` links five production ARM C components and a small explicit fixture helper. No unresolved imports. Compiled session/bridge/lease/validator/selector actually execute.

Controller quiesce/resume, EP0 bind/unbind, driver register/unregister, descriptor save/free, and reference callbacks are EXPLICIT RECORD DOUBLES. They prove ordering and MOD state contract, not physical kernel acknowledgements. Each independent negative test resets the fixture; this is not on-camera recovery.

Through `ACTIVE` state, real `descriptor_reply` was also called directly over the installed independent copy fixture. Original Sony serializer/memcpy returned the 173-byte HS configuration reply. This is not proof that the live EP0 hook is installed: bind is still a recorder.

Real compiled bridge routed wire 1/2 class requests with entity 2 to the reference recorder with the same setup pointer. For START, the session's real selector received explicit DWC/raw/wrapper fixtures and forwarded the exact endpoint 82 wrapper, with the original low-byte packed count contract. No USB request was submitted. Test STOP explicitly calls bridge quiesce before test cleanup; it does not represent a native controller drain.

## Results

120 cumulative checks pass: previous 73 ownership and 47 new for the wired procedure. They include two cycles, strict ordering, registering only 1/2, reverse unregister 2/1, unchanged original PTP graph, failure of second register/save/bind/resume, held retry, forbidding cleanup while in-flight, quarantine without free, and preflight rejection of another USB mode and legacy 0/1.

Input original PC Remote graph in the check is an independent fixture derived from verified native format/parameters; it is not a copy of live kernel heap. Tests do not simulate a successful native allocator as proof of firmware. Full project suite also passes: 605 tests in 14.896s; log is `artifacts/uvc-ptp-session-e0162-project-tests.log`.

Artifacts: `artifacts/native/uvc-ptp-session-e0162/manifest.json` and linked `descriptor-lease.elf` (offline executable ELF, not a kernel module), build log `artifacts/uvc-ptp-session-e0162-build.log`.

```
python -m tools.research.build_uvc_ptp_descriptor_lease --session --input-dir artifacts/native/uvc-ptp-lease-input-e0161 --output-dir artifacts/native/uvc-ptp-session-e0162
```

## Next Boundary

Missing real backend wrappers for disconnect/controller stop/drain, address-limit save/free, flags guard on native register, EP0 hook with readback, and reconnect. Only with those can this sequence be verified as a physical session; do not replace them with recorders and call it compatibility. Native producer/DMM/JPEG transfer and Windows composite enumeration are also unproven. Camera, SD, and persistent storage were not modified.
