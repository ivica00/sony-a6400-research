# E0197 — Physical native stop diagnostic verified

## Result

E0196 module physically loaded and its idle diagnostic ioctl executed successfully on the camera, without native route publication, activation or USB mode switch. Original sys_ptrace GETREGS/GETSIGINFO returned success for **174/174 TIDs**, completed174/expected174/error0. Helper independently captured all174 in ptrace_stop, wait19/info19/code0; **174 attached,174 resumed,1049ms,result0**, TracerPid0 afterward.

Module load/open/diagnostic/close/unload completed. `rmmod` status0, temporary character node and module payload removed, `/proc/modules` restored byte-equal to before test. Debugger703 responsive. Pre/post inventories match sole gadgetcore owner PID149 FD85 and174 threads/errors0. Camera remains Mass Storage. No SD/NAND/preload/backup/boot write; all payloads/logs `/tmp_bt` only. CPU helper and its log remain in uniquely named RAM paths.

## Exact artifacts

- Module: `artifacts/native/uvc-ptp-module-e0196/usbg_video_a6400_shared_candidate.ko`,61588bytes,SHA-256 `64b2518815dc08ea377ffcd39fc9a8014a3c596d4db068dc89c480b25b789347`.
- Helper: `artifacts/native/uvc-ptp-freeze-e0197/native_usb_freeze_probe.elf`,11360bytes,SHA-256 `1c3ca1c47d0575cd81e78720359fec941c31c97e06f79bfdb67ff4da29346cb5`. Both uploaded with verified readback.
- Physical receipt: `artifacts/hardware/uvc-ptp-native-stop-diag-e0197-retry/manifest.json`, nested `cpu/manifest.json` and `cpu/freeze.log`.
- Ownership receipts: `artifacts/hardware/uvc-ptp-owners-{pre,post}-diag-e0197`; validation `artifacts/uvc-ptp-owners-diag-e0197-validation.json`.

## Implementation and initial failure

CPU helper accepts optional `--attest-device /tmp_bt/<node>`. It opens the module before freezing, calls only diagnostic0xc020f023 while it owns the ptrace stops, always resumes after diagnostic failure/success, and closes afterward. No INIT or streaming ioctl is present in this path. Probe build manifest now includes the diagnostic ABI header.

New `run_uvc_ptp_stop_diagnostics.py` verifies the exact audited module hash, loads it, creates a unique 248:33 RAM node, invokes the helper, then unloads and checks module-list restoration. Capture runner can reuse an existing debugger connection and requires complete diagnostic counts/error receipt.

Initial orchestration incorrectly opened a second host USB connection while the first still retained the interface. It failed **before helper execution**, not in the camera's diagnostic ioctl. From a separate host process, cleanup checked TracerPid0, unloaded the unactivated module and removed its own node/payload; module list restored. This failed receipt is preserved at `artifacts/hardware/uvc-ptp-native-stop-diag-e0197`. Corrected orchestration uses one shared connection throughout and passed as above.

## Limits and next step

This is physical validation of native current-tracer checks and stop diagnostics through the module. Declared owner149 is still not a native TGID/membership lookup; user scratch is mutable, and no immutable publication certificate is issued. No new-opener exclusion, VFS cached-target retirement, route lease integration or IRQ/DMA drain is inferred. E0196's62 module checks/all605 tests18.721s remain applicable because module code did not change; new helper build and physical path passed.

Next complete kernel-side target membership/ingress ownership and bind the route lifetime protocol to that verified scope. Shared enumeration/PTP controls/sensor UVC remain untested together; combined PC Remote+UVC/PTP test is not ready. Leave camera in Mass Storage.
