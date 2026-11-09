# E0226 — Preserved output acknowledged on camera

Date: 2026-11-09. Camera remained in MSC. No monitor command/input byte, SD/NAND write, native filesystem call, mount, ptrace or UVC activation occurred. This step **did change one monitor output RAM cursor**, as described below.

## Procedure and result

Fresh read-only capture verified current code prefixes, GOT/topology/mapping and stable queue metadata. The30115-byte output was written to a new host artifact, fsync'ed and read back byte-equal before any acknowledgement. The helper was uploaded only to its own unique `/tmp_bt` pathname with byte-equal readback.

1. A deliberately wrong expected read cursor was rejected with exit7 and `ACK_REJECTED no_write`. The complete live queue header remained equal to the preserved snapshot.
2. Correct expected cursors0/30115 passed two header checks plus live object/global checks. Helper performed exactly one four-byte pwrite to the output read cursor at physical buffer+8, advancing it to30115. It does not write the producer cursor, input cursor or queue data.
3. Receipt: `ACK_OK physical=200eb400 previous_read=0 preserved_end=30115 input=0/0 output=30115/30115`.
4. Independent capture then found zero remaining output bytes. All old output bytes remain preserved in the host artifact. Helper RAM file removed; PID149 TracerPid0. No monitor command was submitted.

Artifacts: `artifacts/hardware/uvc-monitor-ack-e0226/`, especially preserved-output.bin, capture-before.json, rejection-fixed.txt, ack-receipt.txt, remaining-output.bin and manifest.json.

## Helper and validation

`native_monitor_output_ack.c` rediscovers the process's current libMWF text mapping, checks Getchar prefix, resolves monitor globals through GOT, checks queue topology and finds a complete backing `/dev/mem` mapping. It requires bounded/equal expected output cursors and empty input; repeats the header/object/global checks; refuses changes rather than retrying an uncertain write; and verifies the resulting read cursor. An already-empty queue causes no write.

Eight compiled ARM admission cases pass: valid, empty, wrapped, pending input, changed read cursor, changed write cursor, bad input bound and bad output bound. Those tests exercise the real compiled admission function, not MMIO/pwrite or concurrency. Full helper compiled with warnings-as-errors against Sony libc and its rejection/acknowledgement paths were physically executed.

Final binary:10868bytes, SHA-256 `9197d48c6ce081685c38f08b6d1f939bae37d16779744b5c1d53044cd7d2cd81`, `artifacts/native/monitor-output-ack-e0226/native_monitor_output_ack.elf`.

An initial rejection returned7 correctly but lost its buffered stdout because the minimal startup exits without libc flushing. The host assertion stopped before acknowledgement. Fixed helper sets stdout/stderr unbuffered; both physical paths were rerun. Earlier6540-byte binary SHA8a525accde414efd4ea76973f3c5102bcb67606e5c5aeb1e154c57e44ccb921c is retained as helper-before-output-fix.elf with its failed receipt metadata. No failed-attempt cursor change is claimed or hidden.

## Parser preflight and limits

Read-only post-check of actual relocated parser globals observed cmdBufPtr0 and cmdLineMode0; there was no pending partial command at that instant. These are snapshots, not permanent command-send authorization.

Acknowledgement uses the original single-consumer cursor protocol with pre/post validation; it is **not** a multi-consumer CAS or proof of exclusive consumer ownership against all other actors. A competing consumer can race the final check/store. No rollback is attempted after uncertain writes because rewinding over another consumer would be unsafe. The physical successful cycle demonstrates the observed controlled case only. This is unrelated to USB endpoint/IRQ/DMA quiescence and does not make UVC teardown safe.

Next: establish and validate a bounded non-writing monitor probe with explicit input/parser checks and continuous preserve-before-ack output collection. Never infer command success from wrapper1. SD journal remains authorized but unwritten; A:/dev/mmca is the SD candidate and B:/internal flash remains excluded. Last full suite is E0225's617passing tests; this step ran the eight new compiled admission cases and physical checks.
