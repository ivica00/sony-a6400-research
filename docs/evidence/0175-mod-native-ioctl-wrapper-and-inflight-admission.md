# E0175 — MOD Wrapper of Original ioctl and Active Entry Retention

Date: 2026-11-08. Offline implementation. Camera was not contacted. Production module E0164 was not modified.

## Code

`tools/native_camera/uvc_ptp_ioctl_guard.{c,h}` connects the E0174 atomic gate with calling the real original ioctl function. The context contains the gate, an immutable original function pointer, and a latched error. The wrapper:

1. Checks the context, original target, and previous error.
2. Enters through `mode_enter` before the original call.
3. Forwards `file/command/arg` to the original function.
4. Calls `mode_leave` only after its return and preserves the original result.
5. If leave fails, latches the error and rejects future original calls, MOD claim, and release. The original operation might have already occurred at that point: that error does not mean everything was rolled back.

This is MOD access control. It does not replace Sony's decisions nor implement recognition, video, or controls on the host. The function takes an explicit context; it is not published as a native `file_operations` callback and does not modify the camera.

## Build and Execution

`python -m tools.research.build_uvc_ptp_mode_gate --ioctl-guard --output-dir artifacts/native/uvc-ptp-ioctl-guard-e0175`

The builder compiles both MOD C parts for ARMv7 softfp without libc/imports. It executes the real compiled code and selected original kernel bodies `usb_gadgetcore_ioctl` / test-and-set-bit from SHA-verified kernel `12eeec829407595e28265f7d0db3b88c56f63a9f0fdd725c9c53c66a49643707`.

**42 checks pass**: the earlier 28 and 14 additional checks for the wrapper. An unknown original command preserves `-25`; commit while the original active bit is set preserves `-16` and its flags. Those original paths do not call controller or copy services.

The test stops at entry to the original function after the wrapper incremented the count. The actual emulated CPU context remains preserved. On a separate stack, MOD claim returns busy. After restoring context, the original function finishes, the wrapper decrements the count to zero, and preserves its result. This confirms access duration across return of the original function; it is not a physical multicore test.

A separate explicit fault-injection fixture clears the admission count while the original function is running. Leave rejects this, and the wrapper latches the error and blocks dispatch/claim/release. Null context and null original are also rejected. Fixture corruption is not an observed camera error and does not represent Sony code compatibility.

Manifest: `artifacts/native/uvc-ptp-ioctl-guard-e0175/manifest.json`; ELF: `mode-gate.elf` in the same folder; log: `artifacts/uvc-ptp-ioctl-guard-e0175.log`. The manifest contains hashes of both C/header parts, the ELF, and the kernel identity. Python syntax of the builder was verified.

## Open Boundary for Deployment

`integrated:false` remains intentional. Native slot `0x604e5098` was confirmed in E0174, but replacing its pointer alone is not proof of safe publication: an existing call could have already loaded the old address. Existing old entries, lifetime of wrapper code/context, its later removal, and all other direct USB entries must be resolved. `stop_machine` or arbitrary waiting must not be declared a completed callback drain without proof.

No function in these new files installs a hook, removes a hook, or claims that native EP0/gadget is finished. Safe publication and native callback drain remain concrete blockers to physical activation. E0164 `.ko` was not rebuilt because these parts are not yet attached to it; the last full project regression remains 605 tests, alongside the new targeted ARM checks listed above.
