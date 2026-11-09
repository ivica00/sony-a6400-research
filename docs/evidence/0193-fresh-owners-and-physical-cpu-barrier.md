# E0193 — Fresh owners and updated physical CPU barrier

## Physical result

Camera remains in Mass Storage, debugger PID703 responsive, application im.elf PID149. Three fresh read-only inventories report exactly one gadgetcore owner PID149 FD85, **174 threads**, errors 0. Owner and TID sets match before/repeat/after the CPU test. The earlier 175-thread E0177/E0178 set is historical and must not be reused for current authorization.

The exact E0192 probe (6888 bytes, SHA-256 `127e198960a2e0a1afebf77dec93f6c8f10bc4c3f0515f51b309fc32448d6d2b`) was uploaded to a unique `/tmp_bt` path with verified readback. One CPU capture returned status0: **174 attached, 174 resumed, 1013ms, result0**, 174 register records matching the fresh inventory, TracerPid0 afterward. Debugger remained responsive. No module, hook or USB mode change was made. All payload/log writes were `/tmp_bt` only; these uniquely named RAM files remain there.

Physical receipts:

- `artifacts/hardware/uvc-ptp-owner-refresh-e0193`
- `artifacts/hardware/uvc-ptp-owner-repeat-e0193`
- `artifacts/hardware/uvc-ptp-cpu-barrier-e0193`
- `artifacts/hardware/uvc-ptp-owner-post-barrier-e0193`

## Reusable validation

Added `validate_uvc_ptp_owner_receipts.py`: checks complete strict records, duplicates/counts, supported PID149 owner/thread scope, leader inclusion and 512-thread bound. Receipt loading verifies artifact digests/lengths, untruncated capture, status0/flags0, im.elf identity and TracerPid0. Eight positive/negative parser controls pass. Three real receipts validate with matching observed sets (`artifacts/uvc-ptp-owner-validation-e0193.json`).

Added `capture_uvc_ptp_cpu_barrier.py`: loads a verified observation, checks current thread count/tracer, restricts payload to the exact E0192 hash, runs the bounded CPU probe, archives results and requires exact captured TID-set equality and complete attach/resume counts. The capture has no publication or activation command. A later set mismatch is reported after CPU cleanup rather than silently treated as quiescence.

## Limits and next work

This physically validates normal operation of the updated CPU helper. Retry/error injection remains offline E0192 evidence, not deliberately induced camera failure. Sequential inventories cannot exclude future opens or TID reuse. Saved user registers and ptrace stops do not prove kernel/VFS/IRQ/DMA drain. The route lease still lacks a concrete in-kernel full-caller attestation/publication provider, and no native fops slot was changed. E0182 remains the shared candidate. Combined PC Remote+UVC/PTP test is not ready; leave camera in Mass Storage.
