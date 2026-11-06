# 0086: Live touch ENODEV and original menu instruction audit

## Live diagnostic result

After the user reported reconnecting following the requested battery removal/restart, `tools/inspect_touch_camera.py` retrieved the complete 5,336-byte `/setting/touch_probe_v1.log`. Preserved in `artifacts/hardware/touch-inspect-20261105-155811/` alongside a read-back of `/etc/ld.so.preload` containing only `/setting/touch_probe_v1.so`.

The collector executed as PID 962, uid 0, process name `sh`. It successfully opened and read `/proc` entries through normal camera syscalls. `/proc/bus/input/devices` yielded no entries; `/dev/input` listed event0, event1 and event2, but all three opens returned -1 with errno 19 (ENODEV). This proves that these nodes had no usable registered Linux input devices **at the time of collection**. It does not prove their behavior in every later mode. E0084's assignment of these nodes to functioning digitizer/buttons/dials was unsupported.

The module list includes Sony `input` and `osal_uipc`. Mounts confirm `/tmp` and `/etc` are the same persistent VFAT partition `/dev/nflasha10`, while `/tmp_bt` is tmpfs. Hence `/tmp` is not inherently volatile on this camera.

The large historical input_dump.log was also read partially and timed out; it is not new diagnostic activity or proof the old hook remains active. The inspection tool now reads that historical log only with `--include-legacy-log`, after other files.

## Original firmware audit

`tools.research.touch_patch_audit` audits exact dynamic symbols from preserved originals and records source SHA-256, original bytes, disassembly, instruction boundaries and bounded original-code execution in `artifacts/analysis/touch-patch-audit-20261105.json`.

* The six-byte `98 b5 00 af 04 46` prologue appears **375 times** in executable LOAD segments of libObj.so. It is not a unique function identity.
* `InputService::setTpEventSw(bool)` is at linked address 0x3cf200 in this preserved ELF, with the argument copy at +4. It calls InfraTp::GetInstance, InfraTp::SetTpEventSw, then ReleaseInstance. Linked addresses are not validated live snapshot addresses.
* `InputService::callback_tp(int, _InfraInputEvent*)` is at linked 0x3d2e20. Its entry passes the second argument to snd_InfraInputEvent_to_InputServant and later constructs native Event data with a 24-byte parameter copy. This is a native Sony event pathway; it does not establish the earlier mod's assumed coordinate layout.
* `PAS_MenuSelectMode::setTouchable(bool)` is at linked 0x56dcb0. At +6, the original `19 b1` is a **two-byte** CBZ. It is followed by **four-byte** `d3 f8 08 31` (LDR.W of vtable slot +0x108). The old four-byte NOP patch replaces the CBZ and half the LDR.W, leaving `08 31` decoded as an ADD instruction. It destroys the virtual function load.

The bounded experiment executes original bytes with an explicitly constructed object/vtable and stops before the virtual method. Original false/true inputs pass mode 2/0 respectively. A candidate **two-byte** NOP at +6 preserves the load and passes mode 0 for both inputs. The old four-byte patch fails to reach the fixture virtual method within the instruction bound. This validates a local instruction correction, **not** working physical-camera touch navigation. No new RAM patch was deployed.

The required next boundary is the actual Sony touch event transport, original menu event consumers, and live code identity before applying any candidate patch. Native widget mode 0 alone does not prove menu interaction works.

## Analysis tooling

The dependency planner was tried with demangled and exact mangled names, but produced zero functions because its implementation supports bounded ARM ET_REL modules, not this Thumb ET_DYN library. Those empty plans are not analysis evidence. A targeted REA session was started under `artifacts/tools/rea/touch-native-20261105/` for callback_tp and InfraTp::SetTpEventSw; inspect its manifest before using any output.

No SD writes were made. The installed collector performs one-shot diagnostics only and remains configured. The touch-menu objective remains incomplete.

## Validation and next diagnostic approval boundary

The full project suite passed: 547 tests in 16.510 seconds. The original-code audit separately passed its false/true argument assertions. These results do not establish physical-camera touch functionality.

Prepared a diagnostic extension that creates a second one-shot report, `/setting/touch_probe_maps_v1.log`, with bounded copies of `/proc/uptime`, `/proc/149/comm` and `/proc/149/maps`. It neither opens `/proc/149/mem` nor attaches to or modifies the process. The collector was rebuilt successfully against Sony libc with undefined-symbol rejection. Its local binary now represents this extension, while the camera still holds the previously verified original collector. The deployment helper accepts only empty preload or the already approved exact probe entry; unrelated entries remain protected.

Automatic approval review rejected deployment of the expanded payload because prior approval covered the original probe, not this additional process-map collection. No expanded payload was uploaded. Ask the user for explicit approval before deploying this extension. Do not bypass the rejection. Live code mapping identity remains unverified.

The REA session ended with Ghidra startup/import timeout after 330 seconds. Its manifest is failed and cleanup-close completed. No procedure evidence was returned; the findings above come from exact original-byte disassembly and the bounded execution audit, not REA pseudocode.
