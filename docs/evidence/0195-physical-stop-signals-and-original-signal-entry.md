# E0195 — Physical stop reasons and original signal entry

## Physical result

The CPU helper now records WSTOPSIG from its actual waitpid stop receipt, plus PTRACE_GETSIGINFO signal/code for each stopped TID. GETSIGINFO failure takes the existing resume/error path. All per-thread output remains deferred until after resume.

New Sony-libc probe: **11168 bytes**, SHA-256 `b81499b337b40120fbc2cb641f8f4b801bf9adeb2b8923b4a2428ccfd6417ee8`, `artifacts/native/uvc-ptp-freeze-e0195/native_usb_freeze_probe.elf`. Build with warnings as errors passed. Actual shared-header ARM recovery fixtures also pass after adding stop-signal tracking.

One physical capture: **174 attached, 174 resumed, 1434ms, result0**, exact current TID-set match, all174 wchan=ptrace_stop, all174 wait signal19 and siginfo signal19/code0. TracerPid0 afterward, debugger703 responsive. This rules out a SIGTRAP/syscall-event stop reason for these measured receipts; sender identity was not captured, so it does not independently authenticate the signal sender.

Receipt: `artifacts/hardware/uvc-ptp-stop-reason-e0195/manifest.json` and `freeze.log`. Camera remained MSC, no module/hook/mode switch, all payload/log writes unique `/tmp_bt` paths retained in RAM.

## Original kernel controls

New `probe_uvc_ptp_signal_stop_entry.py` executes original do_signal prefix at 0x601102e8. Four passing cases show saved CPSR user ARM0x10/Thumb0x30 reaching original get_signal_to_deliver, whereas supervisor0x13/IRQ0x12 return through the native mode guard. Current/task/register objects and clear flags are explicit fixtures; execution stops before get_signal_to_deliver. This does not run full signal delivery or prove physical stack provenance.

The hash-verified kernel direct ARM branch scan records three ptrace_stop call sites and five ptrace_notify sites. Manual inspection of the five notify argument sequences shows 5/0x85 or an event code with low byte5 (including0x405,0x505,0x605). These are distinct from measured signal19. The scan covers aligned direct B/BL in _stext.._etext, not indirect calls or definitive code/data classification.

```
python -m tools.research.probe_uvc_ptp_signal_stop_entry --output-dir artifacts/analysis/uvc-ptp-stop-entry-e0195
```

## Boundary

These observations narrow the measured stop reason to SIGSTOP, but do not establish its entire kernel call chain, prove that every cached old VFS target has retired or exclude a new opener. No publication authorization is inferred yet. The route lease is still unintegrated and E0182 remains the shared candidate. Full project tests were not rerun for this helper-only observation change; relevant validation is actual helper build, ARM header fixtures, original-body controls and physical CPU capture. Combined PC Remote+UVC/PTP test is still not ready; leave camera in MSC.
