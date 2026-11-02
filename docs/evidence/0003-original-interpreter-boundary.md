# E0003 — Original interpreter executes to its first syscall

Date: 2026-10-18. Status: reproduced in the bounded process probe. No camera/full-system equivalence is claimed.

## Observed result

The original extracted `ld-2.11.2.so` was entered at `0x40000791` with `im.elf` mapped at its linked addresses and an explicit process stack. It executed **1,183 instructions** before reaching Thumb instruction `00 df` (`svc #0`) at `0x40010b14`.

The boundary has `r7 = 45` and `r0 = 0`. The ARM Linux EABI syscall table identifies 45 as `brk`, so this is the original interpreter requesting the current program break. The probe stopped before answering it. No syscall response, synthetic C++ object, HLE import, camera state, or UI renderer was provided.

Two independent fresh runs generated identical complete JSON reports, including input hashes, initial stack hash, boundary arguments, instruction count, and the last 32 instruction records. Repeatability applies to the stated configuration, not camera timing or an unimplemented kernel response.

## Inputs and initialization

- Application: `nflasha15_unpacked/bin/im.elf`, SHA-256 `866729eb0bc1e6f5aba04d8bf8e45491985afe89a078ccb106a1ce2476865225`.
- Interpreter: `nflasha7_unpacked/lib/ld-2.11.2.so`, SHA-256 `7c215cee6c4175079d69cb1433c6be90189e793f6e44f068ed6ac97621dd7a2c`.
- The interpreter alias is resolved using original image metadata. Application, interpreter, and filesystem-image hashes are checked before execution.
- Application ET_EXEC load bias is zero; interpreter bias is `0x40000000`. Mappings preserve segment permissions, page offsets, segment bytes and zero-filled BSS. Holes stay unmapped. Overlapping PT_LOAD pages are rejected pending an explicit policy. The original interpreter performs its own startup; no host-side dynamic relocations are applied.
- The RW, non-executable stack begins at `0x7fe00000` and spans 1 MiB. Initial SP is `0x7fefff20`, aligned to 16 bytes. Arguments, environment, terminators and auxiliary vector are explicit; AT_PHDR points to mapped application headers, AT_BASE identifies the interpreter, and AT_ENTRY identifies the application entry.
- CPU execution starts in user mode, with ISA state selected by the interpreter entry's low bit. Initial registers are reported.

## Experimental assumptions and limits

Cortex-A9 is provisional, not an identified camera CPU. ASLR is disabled. Normal arguments are unknown; this run uses only `/usr/bin/im.elf` and an empty environment. Platform `v7l`, HWCAP zero, UID/GID zero, secure-execution flag zero, clock-tick value 100, deterministic random bytes, and enabled VFP are declared inputs, not captured camera state.

The kernel is not executing. There is no kuser-helper page, VDSO, camera device model, syscall implementation, writable filesystem, IPC, or scheduler. Execution has not reached the application's entry or Sony's UI. This closes only Experiment 0001's first-boundary gate.

## Implementation and reproduction

The implementation is separate from `legacy/`: `src/a6400/images/process_elf.py` maps images; `src/a6400/execution/process_entry.py` constructs the stack; `src/a6400/execution/interpreter_probe.py` executes to a boundary. The launcher uses existing inventory/layout reports:

```powershell
.\venv\Scripts\python.exe -m tools.research.probe_interpreter
.\venv\Scripts\python.exe -m tools.research.probe_interpreter --report artifacts/execution/interpreter-probe-repeat.json
.\venv\Scripts\python.exe -m unittest discover -s tests -v
```

Reports are `artifacts/execution/interpreter-probe.json` and `interpreter-probe-repeat.json`. Exit code zero means the experiment reached its syscall boundary, not that the guest syscall or application completed.

Constructed ARM/Thumb ELF fixtures check syscall boundaries, memory protection, unmapped access, input hashes, BSS, header addresses, stack alignment/content, initial user mode, repeatability, exceptions, execution limits and refusal to resume implicitly. They do not require proprietary firmware.

## Primary contract sources

- [Linux v3.0 ELF setup](https://github.com/torvalds/linux/blob/v3.0/fs/binfmt_elf.c): process stack, auxiliary vectors and segment mapping.
- [Linux v3.0 ARM ELF definitions](https://github.com/torvalds/linux/blob/v3.0/arch/arm/include/asm/elf.h): page size and initial r0 convention.
- [Linux v3.0 ARM syscall table](https://github.com/torvalds/linux/blob/v3.0/arch/arm/include/asm/unistd.h): EABI syscall 45.
- [ARM startup register convention change](https://git.ti.com/cgit/ti-linux-kernel/ti-linux-kernel/commit/?id=8148d0952b58d0664c3a3ddffbe6ded35ad4c790): explains older r1/r2 seeding and their undefined status to libc. The selected initial values are recorded.

These upstream contracts guide the experiment; Sony kernel differences remain unverified.

## Next step

Specify and test a guest-only program-break contract against Linux semantics. Establish an initial break from application mappings, model growth/failure/address collisions, then record the next unsupported request. Retain this zero-response probe as a regression baseline. Do not replace the boundary with a constant success return or pass guest syscalls to the host.
