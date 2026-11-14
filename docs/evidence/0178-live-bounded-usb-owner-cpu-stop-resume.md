# E0178 — Physically Bounded Stop and Resume of USB Owner CPU Threads

Date: 2026-11-08. The camera remains in Mass Storage mode. Debugger PID703 available. No shared module loading, USB change, hook, application call, or writes to Sony application memory. New payloads and logs are only in `/tmp_bt`.

## Tool and Build

`tools/native_camera/native_usb_freeze_probe.c` uses the existing `native_freeze.h`, previously physically verified on PID149, and the existing Sony libc/startup toolchain. The reproducible builder is `tools/research/build_native_usb_freeze_probe.py`. The tool requires `--capture-once`; without arguments it only prints preflight and returns 2.

Final ELF: `artifacts/native/uvc-ptp-freeze-e0178-fixed/native_usb_freeze_probe.elf`, **6796 bytes**, SHA-256 `04953d3bba73841700889e49125d50ce191aef8f3a59c791432bd216ae90368b`. The interpreter is `/lib/ld-linux.so.3`, and the only `DT_NEEDED` dependency is `libc.so.6`; linking uses the retained Sony libc.

The tool enumerates and attaches to all PID149 threads, re-checks the set, reads `PTRACE_GETREGS` within a total 2000 ms limit, and immediately detaches all attached threads. Printing of individual registers happens **after** resuming all threads. Every read CPSR must indicate user mode. These are saved user registers, not kernel stacks.

The first physical preflight did not start a freeze: it returned 2, but stdout was not flushed before the custom startup `SYS_exit`, so the host guard refused to continue. That attempt remains archived in `artifacts/hardware/uvc-ptp-freeze-e0178`. Explicit `fflush` was added to both preflight and error output; the failed freeze was not repeated because the freeze had not even started then.

## Physical Result

The final ELF was transferred to a separate timestamp path in `/tmp_bt` with byte-equal readback. Preflight correctly printed `freeze=0`, after which one capture cycle was executed:

```
FREEZE threads=175 attached=175 resumed=175 result=0 elapsed_ms=1346
END result=0 captured=175 expected=175 saved_user_regs_only=1
```

All 175 register records were saved. All CPSRs are in user mode, and all 175 PCs belong to executable ranges of the previously read real maps. No host-reconstructed CPU frame or fake thread ID was used.

Host run `status=0, flags=0`; the full log is 11926 bytes, SHA-256 `5462bb489e906a4daef584ec186b3ea244bc3e28e3918c4a62b3068e7a8e3011`, without truncation. Final `/proc/149/status` has `TracerPid=0`. The debugger responds before and after the capture.

A repeated native owner inventory **after** the freeze cycle confirms the same set of `OWNER/TASK` records as before: one gadgetcore owner PID149/FD85, 175 threads, `errors=0`. This physically confirms recovery of this CPU capture cycle, without a USB configuration change.

Artifacts: `artifacts/hardware/uvc-ptp-freeze-e0178-fixed/{manifest.json,freeze.log,status-before.txt,status-after.txt,debugger-before.txt,debugger-after.txt,owners-after-freeze.log,post-freeze-manifest.json,register-map-analysis.json}`. The build manifest includes hashes of the source, `native_freeze.h`, startup, Sony libc, and ELF.

## Exact Scope of Evidence

It is confirmed that the observed process holding gadgetcore can in this state be briefly completely stopped and resumed with complete receipts. It is not confirmed that this fact alone drains already-started kernel ioctl calls: a saved user PC is not proof of a complete kernel stack. Kernel workers, IRQs, DMA, and EP0/gadget callbacks were not stopped by this procedure.

Therefore E0178 does not declare swapping the `fops` pointer alone safe and does not grant confirmation for PTP/UVC activation. A separate contract is needed for installing the wrapper and finishing kernel callbacks. The camera remains in Mass Storage, with no active observer/hook or ptrace attachment. The shared E0164 module is still unloaded; the PC Remote + UVC/PTP test is not yet ready.
