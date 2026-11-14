# E0180 — Module Reference Fix and Successful Physical Init/Exit

Date: 2026-11-08. Camera remains in Mass Storage. All new payload/log writes on the camera only in `/tmp_bt`.

## Removed Unavailable Dependency

The E0179 loader rejected `__symbol_get` because it belongs to the GPL-only kernel export table, and the donor module does not have a GPL-compatible license tag. The donor's license tag **was not modified** and there is no direct call to a GPL-only function via a hardcoded address.

The new `tools/native_camera/uvc_module_self_ref.{c,h}` implements a targeted native module-get inline contract and uses the normally exported `module_put` for release. The `file_operations` owner remains `__this_module`. Get may only be called from an already module-owned file operation when the module is `LIVE`.

From original kernel code, `thread_info` preempt `counter+4` and `CPU+0x14` as well as `module refptr+0x138` were verified. Get temporarily disables preemption through the native count contract, checks `LIVE`, CPU number, pointer, and overflow, increments the local per-CPU increment count, restores preempt count, and calls the normally exported `preempt_schedule` if needed. Three native instruction guards bind the layout to the target version. This is not a generic Linux `struct module` layout.

This MOD code **does not call** `__symbol_get`. It imports `module_put`, `preempt_schedule`, `__per_cpu_offset`, and `nr_cpu_ids`; all are in the normal export table. Legacy anchor/self-export was removed from the shim. Cleanup still retains the reference until the session is completely cleaned up.

## Execution Check of Reference

`tools/research/build_uvc_module_self_ref.py` compiles the helper and executes it together with the **real original `module_put` body**, using explicit module/thread_info/per-CPU fixture data. **17 checks pass**: CPU0/1, release on another CPU, `LIVE`/`COMING`/`GOING`, null storage, overflow, preservation of nested preemption count, and reschedule order. The scheduler is an explicit recorder, not emulated real scheduling.

Manifest: `artifacts/native/uvc-module-self-ref-e0180/manifest.json`. The physical init/exit below does not activate a session, so self-get itself is not yet claimed to be physically executed.

## Export Check Now Distinguishes Classes

The new `tools/research/kernel_export_contract.py` reads the actual value/name pairs from the normal and GPL export ranges of the SHA-verified original kernel. The builder rejects GPL-only imports that are unavailable to the actual license metadata tag. It also supports `DATA` exports that text-only `kallsyms` inventory did not contain. Headers of new C parts are also included in the build hash manifest.

This replaces the earlier insufficient name-presence-only check. The fixed candidate has **49 imports**; there is no `__symbol_get`/`__symbol_put` and no GPL-only kernel imports.

## Candidate and Checks

`artifacts/native/uvc-ptp-module-e0180/usbg_video_a6400_shared_candidate.ko`:

- **58728 bytes**;
- SHA-256 **adba4ea1e435c018de1a4f41fa0c7010ee249621e9bc8332b3ebc99807ad3917**;
- exact native vermagic, original init/exit preserved;
- **30** module guard/structural ARM checks pass;
- **605** project tests pass in **15.199 s**.

The native backend change of E0179 remains covered by its 155 checks. No new project tests were fabricated that would merely mirror the implementation.

## Successful Physical Cycle Without USB Activation

The candidate was transferred to a timestamp path in `/tmp_bt` with byte-equal readback. `insmod` returned 0. `/proc/modules` confirmed:

```
usbg_video 46090 0 - Live 0x5f57f000 (P)
```

The video node was not opened, no activation ioctl was executed, no shared configuration was registered, and no feeder was started. Then `rmmod usbg_video` returned 0. Final `/proc/modules` is byte-equal to initial: the new module did not remain loaded.

Debugger PID703 responds before and after the cycle. Final PID149 status: sleeping, `TracerPid=0`, `Threads=175`. Camera remains in Mass Storage. Physical receipts and kernel log: `artifacts/hardware/uvc-ptp-module-lifecycle-e0180`.

## What Is and Is Not Ready Now

Real loading and unloading of this kernel candidate are confirmed. This closes the loader/import blocker that could not be proven by offline checks alone.

Shared enumeration PC Remote + UVC/PTP has not yet been tried. Mode gate/original ioctl wrapper E0174/E0175 have not yet been installed on the native entry, and active native gadget/EP0 callback drain and recovery of the shared session remain open. The build therefore still retains `physical_test_ready:false` for **shared mode activation**, despite the separately successful init/exit test. There is no sensor UVC or control during stream.
