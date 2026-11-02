# Evidence 0033: OpenSSL SIGILL capability probe and `/tmp` boundary

## Result and scope

`im.elf i` under `--backup-service preset-backed --urandom-open --urandom-entropy deterministic --regular-inode-rdev --readonly-image-times` (E0032 policy set) now passes the `libcrypto.so.1.0.0` CPU-capability probe and stops at a new explicit boundary.

- Previous stop (E0032 follow-up run): `UC_ERR_INSN_INVALID` at `0x533da288` (`vmull.p64`) inside `OPENSSL_cpuid_setup` (`libcrypto.so.1.0.0` file offset `0x39f80`).
- Observed original behaviour: the function installs a `SIGILL` handler through `rt_sigaction(4, ...)` (handler `0x533d9f51`, Thumb), then deliberately executes ARMv8 crypto/NEON probes (`0x533da260`, `268`, `270`, `278`, `280`, `288`) and relies on `SIGILL` to skip unsupported ones.
- Now: 5 `SIGILL` deliveries, each handled by the original guest handler, probe completes at 42,396,060 instructions.
- New boundary: `stat64("/tmp")` -> `runtime_namespace_not_supplied` (`unsupported_filesystem`). `/tmp` is runtime state and stays unsupplied.

## Contract implemented (experimental)

- `rt_sigaction` records handler/flags/restorer/mask per signal and returns the previous action in `oldact`.
- Undefined-instruction faults are delivered to a registered guest `SIGILL` handler: `r0 = 4`, SP lowered, Thumb entered through PC bit 0.
- **Limits:** no Linux signal frame and no `sigreturn`; this works only because the handler exits through `siglongjmp`. A handler that returns is not supported and is not claimed to work.
- Fail-closed guard: more than 64 deliveries stops with `signal_loop_boundary` and records PC, instruction bytes, SP, LR. Only the first 16 deliveries are recorded.

## Failure history (kept as evidence)

1. First implementation wrote CPSR.T to enter the Thumb handler. Unicorn stayed in ARM mode, the handler's Thumb `blx` at `0x533d9f58` faulted, and the loop delivered ~6.06 million signals, each appended to the report. The report grew to gigabytes and the host tool crashed. Fixed by the delivery cap, bounded recording and PC bit-0 entry.
2. `tools/research/report_summary.py` prints a bounded summary; use it instead of loading or printing raw reports.

## Not established

- `HWCAP`/`AT_HWCAP` is still 0 in the experimental stack; the real kernel value (`elf_hwcap` from `proc_info` is `0x8097` base plus VFP/NEON additions) is not yet applied. Not required to pass the probe.
- No framebuffer transaction yet; no camera behaviour is claimed.

## Follow-up: what `/tmp` is (observed, `sbin/init` sha256 `0af5724e...`)

Mount records extracted with `tools.research.mount_evidence.inspect_init`:

```text
/dev/nflasha10 /tmp vfat 0xc0ed0490 posix_attr
/dev/nflasha10 /etc vfat 0xc0ed0490 posix_attr
/dev/nflasha10 /log vfat 0xc0ed0490 posix_attr
```

`/tmp` is a read-write vfat mount of flash partition `nflasha10` (the same device as `/etc`), not a `tmpfs`. Its contents, root-inode metadata and timestamps are nonvolatile device state. No `nflasha10` image exists among the preserved inputs (only `nflasha3/5/7/15`). The strict `runtime_namespace_not_supplied` stop therefore cannot be resolved from firmware; supplying an empty `/tmp` would invent state. The boundary is kept.

Resolving it needs either an identified `nflasha10` image (read-only camera backup within the user's authorization) or an explicitly labelled experimental overlay policy whose results are not camera-faithful.
