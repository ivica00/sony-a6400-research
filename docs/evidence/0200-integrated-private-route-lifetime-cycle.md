# E0200 — Integrated private-route lifetime cycle on camera

## Integration

Linked the actual `uvc_ptp_route_lease` publish/retire/recover policy into the shared module and added `uvc_ptp_route_dryrun.{c,h}`. New diagnostic **0xc020f024** runs the kernel-owned stop verifier, then its synchronous internal consumer exercises the route lease against **one module-owned test word**. Its before/after tokens are 0x13572468/0x24681357. Neither token is a code pointer; the slot is not native fops or executable memory.

The adapter uses actual a6400_module_self_get/put, existing module control serialization and native reservation. It requires idle/releasable session/backend state. It publishes the private token, restores it and checks lease/pin/barrier cleanup before returning. HELD state is stored persistently for retry with a fresh verified scope. Temporary scope/callback pointers are cleared on every return. Foreign private-word values are preserved during recovery. Real native slot0x604e5098 is read-only checked against original0x602b8844 before/after success.

The adapter's barrier covers only this private word. **It must not be reused as the native caller barrier**: a verified PID149 scope alone does not establish global ingress/cached-caller exclusion.

## Offline validation

Module `artifacts/native/uvc-ptp-module-e0200/usbg_video_a6400_shared_candidate.ko`, **66540bytes**, SHA-256 **c621a8b5c6ad1f7a955eadcbd3cc60bbea0be83c7f46a9284434568e83adb462**. Existing export classification, donor/init/exit and enumeration-only constraints remain audited.

**94 compiled ARM module checks pass**. Added integrated private publish/retire/repeat cycles, pin failure, foreign-word HELD/retry, recovery after restoring the private expected value, invalid-scope pin suppression, ACTIVE rejection and unchanged native slot. Self-pin is an explicit recorder in this audit; actual native self-reference code executes in the physical test below. Separate E0191 policy fixtures retain broader partial-resume recovery coverage.

All **605 tests pass in19.049s**. Relevant logs `artifacts/uvc-ptp-module-e0200-{build,audit,tests}.log`. The final read-only native-slot assertions were rebuilt and module-audited after the project test run; no Python/project behavior changed in that final addition.

## Physical validation

Helper `artifacts/native/uvc-ptp-freeze-e0200/native_usb_freeze_probe.elf`,11312bytes,SHA-256 `70f5411f964abf1e3a048fbb71b6fcae335177f6c6ead8c807e1eed55b868f1c`, adds explicit `--route-shadow` diagnostic selection and receipt. Runner requires successful counts and the shadow-only marker.

Exact module/helper uploaded with verified readback. **174/174 native stop/membership checks,error0;174 attached/resumed in1348ms;TracerPid0**. The synchronous consumer physically executed the private route lease and actual native module-reference contract. Module file closed, rmmod0, temporary character node/module payload removed and `/proc/modules` byte-equal restored. Fresh pre/post observations match PID149 FD85/174TIDs/errors0; debugger703 responsive. No force-unload or reference-counter write from host was used.

Receipts: `artifacts/hardware/uvc-ptp-route-shadow-e0200` and nested cpu; owners `uvc-ptp-owners-{pre,post}-shadow-e0200`; comparison `artifacts/uvc-ptp-owners-shadow-e0200-validation.json`.

No native route/descriptor instruction was written, no USB activation/mode switch, camera remains MSC. All filesystem writes/tmp_bt only; helper/log remain in RAM. Physical error/recovery paths were not deliberately induced; those remain offline assertions.

## Next boundary

This validates composition and code lifetime for a private slot, not live interception or camera compatibility. A concrete native ingress/cached-caller exclusion provider is still required before applying the lease to actual gadgetcore fops. Shared enumeration, simultaneous PTP controls and sensor UVC remain untested together. Combined PC Remote+UVC/PTP test is not ready; leave camera in MSC.
