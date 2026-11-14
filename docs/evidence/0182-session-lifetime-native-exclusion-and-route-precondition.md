# E0182 — Retaining Native Reservation Across the Entire Session

Date: 2026-11-08. Continuation of the user's E0181 changes. This step has no camera access or writes; the candidate was neither transferred nor loaded.

## Review of E0181

The mode gate and native ioctl wrapper integration added by the user in E0181 was retained. Its physical init/exit test and receipts remain unchanged. An additional lifetime issue was identified: `shared_ioctl` and `shared_release` were releasing the native guard after every call, including return from a successful session start or failed cleanup.

In a future actually published native wrapper, that would allow original command `e203`/`e204` to re-enter between MOD ioctls while shared descriptors are still active or retained. Previous per-call tests did not check that interval. This is not an observed physical race: the wrapper has not yet been installed on the kernel slot.

## Implementation Addition

`tools/native_camera/uvc_ptp_module_shim.c` now distinguishes two purposes:

- `control_gate` serializes individual MOD ioctl/release entries;
- `native_reserved` tracks reservation of `native_guard` across the entire session duration.

The first MOD entry acquires the native reservation if there is no original call. Subsequent MOD entries can reuse it under local protection, so `STOP` is also possible while `native_guard` remains `HELD`. Original entries through the wrapper are rejected between calls while the session is `ACTIVE` or `HELD`.

The reservation is released only when `session_releasable` returns true, there is no self-pin, and the backend no longer holds gc ownership. Incomplete cleanup or a guard release error retains the reservation. Real error codes are no longer replaced by a generic busy result. A lost/mismatched reservation rejects further MOD operations before hardware/callback calls.

Registration hooks additionally require an active MOD control entry and ownership of the native reservation.

## Activation Requires an Actually Connected Entry

Before `INIT` command `0x4038e000`, it is checked that native `fops` slot `0x604e5098` actually points to `a6400_uvc_native_gadgetcore_ioctl`. If it still points to original `0x602b8844` or another target, `INIT` returns `-ENODEV` (`-19`) **before** the original core ioctl. The registration hook repeats the check.

This is a necessary condition, not an installation procedure or proof of quiescence. This code does not write to that kernel slot. It is not claimed that an equal pointer alone resolves old VFS entries, owner lifetime, or direct kernel callbacks.

## Candidate and Checks

`artifacts/native/uvc-ptp-module-e0182/usbg_video_a6400_shared_candidate.ko` was built, **60708 bytes**, SHA-256 **280af3755079e0c2fcddfa1b3e16c9a80dcb020076ea86b612989b4abe1e534d**. 49 imports and checks of normal/GPL export classes were retained; original init/exit and three documented donor instruction changes remain verified.

Extended `tools/research/audit_uvc_ptp_module.py` now has **48 passing checks** (E0181: 33). New checks cover:

- rejecting `INIT` before an actual native route and releasing the idle reservation after rejection;
- an `ACTIVE` session remaining `HELD` between MOD ioctls;
- subsequent status and `STOP` entries reusing their own reservation;
- rejecting concurrent MOD calls and original native ioctls;
- lost reservation without releasing self-pin;
- `HELD`/cleanup errors that do not release the native guard;
- releasing only after an explicit completed-cleanup fixture;
- propagating and latching guard release errors.

`ACTIVE`/`HELD`/`IDLE` are explicit typed fixtures; original core ioctl/release and native gadgetcore ioctl in this audit are recorders. The kernel route slot in the test is also a fixture, not a real hook. The fault removal test is not physical recovery. Real compiled MOD code is executed, but not the original native hardware teardown.

Manifest: `artifacts/analysis/uvc-ptp-module-e0182/manifest.json`; log: `artifacts/uvc-ptp-module-e0182-audit.log`. All **605 project tests** pass in **18.871 s** (`artifacts/uvc-ptp-module-e0182-project-tests.log`).

## Current Boundary

The candidate is not physically activated, and the user's E0181 init/exit evidence is not declared proof of this new session path. Safe installation of the native wrapper, completion of EP0/gadget callbacks, shared enumeration, and recovery to original PC Remote remain open. Sensor UVC with concurrent PTP controls is not yet confirmed. Leave the camera in Mass Storage until that test is prepared.
