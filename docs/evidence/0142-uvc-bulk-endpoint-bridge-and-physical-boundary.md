# E0142: Bulk IN bridge implemented; physical transport remains unresolved

Date: 2026-11-07. All camera payload writes in this experiment targeted `/tmp_bt`. No SD, NAND, backup, preload or boot configuration writes were issued. Host drivers were unchanged.

## Corrected ABI contract

The handover premise that the a6400 callback receives `(speed, iface, config)` is not supported by the original call sites. In retained `a6400-start_interface.txt`, `602b92f0..602b9300` loads speed into r1 and the registration record's endpoint count/list into r2/r3. The `startFuncDrv` tail at `602b8ecc..602b8efc` does the same. Count is a byte at record+0xc; the word load also includes unrelated upper bytes.

Physical cycle 2 confirmed START r2 values 1754733824 and 1754733825 (low bytes 0 and 1), with r3 respectively zero and `698a39a0`. Original reference `usbg_cmn_make_ep_list` at `.text+28f8` reads only the count byte. The bridge now masks count with `0xff` before validation.

`dwc+0xdc` points to the raw USB endpoint. The reference video module expects a gadgetcore wrapper: original `ep_ctrl_create_ep` at `602ba8e4` stores the underlying USB endpoint at wrapper+0x24. Original `gcore_queue` at `602ba5d0` follows wrapper+0x24 before invoking native endpoint operations. Passing a raw endpoint as the video module's wrapper would violate this ABI.

The composite shim validates a kernel-provided wrapper against `*(dwc+0xdc)`, requires an enabled descriptor of length 7/type 5/address 0x81/BULK, and passes a one-element wrapper array synchronously to the original callback. No raw endpoint is substituted. START may originate from either shadow; matching STOP/quiescence tracks the interface that started. Non-START/STOP notifications retain the primary-only policy. Some inherited source comments still describe the earlier primary-only/alternate-setting assumption; this paragraph records the implemented behavior.

## Builds and controls

Final deployed module: `artifacts/native/uvc-bulk-bridge-e0142-count/usbg_video_a6400.ko`, 67,780 bytes, SHA-256 `23a1ab7a811a0cb22200c508e49c6eb3516fb2adeea8ddd0a606d7ceae24b71a`. All 42 undefined symbols matched retained kernel/module symbols. Original executable section prefixes remained unchanged.

53 compiled ARM bridge/original dispatcher controls passed, including secondary VS routing, matching STOP, retirement/context reuse and count padding. Reference callbacks in these controls are recorders, not original video callback bodies. Reports: `artifacts/analysis/uvc-bulk-bridge-controls-e0142-final`.

`py -3.12 -m unittest discover -s tests`: **599 passed**, 15.781 seconds. This does not prove physical streaming.

The feeder was rebuilt as a bounded 900-tick transport experiment. Removed its persistent `/log/feeder.log` fallback and the unmeasured 30.0 FPS log claim. Scheduling 900 ticks is not a hard timeout if an ioctl blocks. Its source is a static 29,452-byte JPEG copied into the preexisting experimental physical buffer; native camera-frame production remains unimplemented here.

## Physical observations

Initial camera debugger: PID 703, root, Mass Storage.

Cycles 1 and 2 registered/committed successfully, returned zero accepted frame submissions, and restored Mass Storage with STOP and buffer-unregistration results 0. Cycle 2 START diagnostics established the padded count above. Full available feeder logs and bounded kernel output were preserved under `artifacts/hardware/uvc-bulk-e0142`. Kernel output requested through exec was limited by the debugger response size; it is not a complete dmesg archive.

Cycle 3 deployed the corrected low-byte count build with verified readback. FFmpeg exceeded its 20-second host timeout without producing a JPEG. The camera did not return to Mass Storage during the subsequent 35-second reconnect window or final checks. Cycle 3 camera logs therefore remain unavailable. A blocked transfer, kernel fault or teardown stall cannot yet be distinguished. The presence of Windows device nodes does not prove live controller responsiveness or that the endpoint validator succeeded.

Final Windows readout: `054C:0322` video service `usbvideo`, audio service `usbaudio`, composite service `usbccgp`; all Status OK / ProblemCode 0. This preserves the PnP milestone but does not establish frame transport, resolved DirectShow behavior or 30 FPS.

## Required next action

Recover physical Mass Storage with a battery power cycle and reconnect USB. First retrieve surviving kernel/klog evidence and inspect current `/tmp_bt` state before any additional deployment. Investigate the first original video callback/transfer boundary reached by cycle 3. Do not start CinemaHUD or claim a live stream until a decoded host frame and measured delivery rate exist. The final experimental module must not be treated as a verified working port.
