# E0005 — Image-backed kernel identity and the first filesystem request

Date: 2026-10-18. Scope: bounded interpreter execution with declared guest contracts; original application/UI entry remains unreached.

## Observed progress

The optional `brk-uname` policy reaches **3,091 original interpreter instructions**. It services the existing heap query and one image-backed `uname`, then stops at syscall 33 (`access`) for **`/etc/ld.so.preload`**, mode 4. That filesystem request is not answered.

The report records exactly seven guest memory-read events in the **release** field. No guest reads of the machine, nodename or domainname fields occurred before this boundary. Two fresh runs generated identical reports.

Earlier policies are preserved: default `stop` supplies no responses and ends at 1,183 instructions; `brk` ends at the unanswered `uname` after 2,222. Each policy has its own default report filename.

## Kernel evidence

The hash-checked `nflasha3_unpacked/vmlinux.bin` contains a structurally matching UTS record at file offset **`0x3c5a90`**. It has six null-padded 65-byte fields:

| Field | Compiled value | Runtime treatment |
| --- | --- | --- |
| sysname | `Linux` | Image-backed |
| nodename | `(none)` | Guarded; runtime value unknown |
| release | `3.0.27_nl-rt106+` | Matches independent kernel banner |
| version | `#1 SMP PREEMPT RT Mon May 27 14:09:40 JST 2019` | Image-backed build data |
| machine | `arm` | Guarded; early ARM setup can overwrite it |
| domainname | `(none)` | Guarded; runtime value unknown |

The extractor requires a matching kernel hash, one unambiguous complete record, printable terminated fields with zero padding, and a release matching the separate Linux banner. It does not infer the camera's CPU from the compiled `arm` string.

ARM kernel initialization updates the machine identity using the selected processor description. Hostname/domain can also change. Compiled defaults therefore cannot be presented as verified live-camera values. The current contract assumes default Linux personality; personality-dependent release rewriting is outside this experiment.

## Contract boundary and guards

`guest_uname.py` copies the exact 390-byte compiled record into a fully writable guest range. `guest_memory.py` checks guest mappings and permissions first, because a host Unicorn memory write alone would bypass guest page protections. Invalid, protected, wrapping or incomplete buffers return raw ARM `-EFAULT` without a copy.

Read guards track the copied bytes. A CPU read touching a runtime-unknown field stops with `unverified_identity_read`; it cannot silently use a guessed machine identity to advance the experiment. Guest writes clear provenance only from overwritten bytes to avoid stale guards when the stack is reused. The observed release-only path passes this guard.

This preflight-copy contract is deliberately bounded: it makes invalid-buffer failure atomic rather than modeling Linux's possible partial-copy side effects. This difference remains a compatibility limit. Any future host-side syscall copy into previously tracked bytes must update their provenance as well.

Path previews at unsupported `open`/`access` boundaries are bounded diagnostic guest-memory reads. They never open or resolve a Windows host path and do not supply a guest response.

## Reproduce

```powershell
.\venv\Scripts\python.exe -m tools.research.probe_interpreter --syscalls brk-uname
.\venv\Scripts\python.exe -m tools.research.probe_interpreter --syscalls brk-uname --report artifacts/execution/interpreter-uname-repeat.json
.\venv\Scripts\python.exe -m unittest discover -s tests -v
```

The launcher verifies the kernel identity source against `baseline.json`. Existing ELF and guest-layout inventories are also required. Reports: `artifacts/execution/interpreter-uname.json` and `interpreter-uname-repeat.json`.

Added checks cover identity extraction/ambiguity/hash rejection, exact copy size, guest memory bounds/permissions, no partial preflight write, release reads, unknown-field stops, provenance clearing, bounded path previews, and interpreter integration. The repository suite has 73 passing tests at this milestone.

## Primary references

- [Linux ARM syscall dispatch](https://github.com/torvalds/linux/blob/v3.0/arch/arm/kernel/calls.S): syscall 122 invokes `sys_newuname`; 33 invokes `sys_access`.
- [Linux `newuname` implementation](https://github.com/torvalds/linux/blob/v3.0/kernel/sys.c): guest copy and failure semantics.
- [UTS record layout](https://android.googlesource.com/kernel/msm/+/49c13b51a15f1ba9f6d47e26e4a3886c4f3931e2/include/linux/utsname.h): six 65-byte fields; this upstream layout is checked against the local binary record.
- [ARM processor initialization](https://github.com/torvalds/linux/blob/v3.0/arch/arm/kernel/setup.c): machine identity is updated during setup.

## Next work

Introduce a read-only guest filesystem contract using original image metadata, symlink semantics and explicit mount-state assumptions. Distinguish a verified absent path in a complete image from missing writable/runtime state. Implement guest path errors and access permissions without consulting host filesystem identity or returning generic success. Then observe the linker's next request.
