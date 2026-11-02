# Experiment 0004: Thread TLS and Private Anonymous Stack Discard

## Question

Does restoring hardware TLS prevent original NPTL workers from using the main thread's unwind/stack state, and what verified boundary follows?

Use the firmware identities and commands in [E0026](../evidence/0026-thread-tls-and-stack-discard.md). Supply no synthetic queue messages for the argument-selected `a` and `i` cases. Retain the entropy read guard and original input hashes.

## Controls

- Preserve the pre-fix diagnostic report at 2,296,240 instructions; it is historical evidence of the defect, not a current baseline to reproduce with incorrect state.
- With corrected TLS and no madvise response, expect the original stack-discard syscall boundary at 2,298,610 instructions for `a`.
- Enable only `--madvise-dontneed` to answer advice 4 on fully known private anonymous pages. Stop on any unsupported ownership, advice or range. Do not supply general success for arbitrary memory requests.
- Use `--stop-worker-main-stack` to diagnose worker SP entering the initial main-stack mapping. It is a diagnostic for these NPTL allocations, not a rule for arbitrary guest clone programs.
- Use `--trace-library-activation` to observe the original dlopen call/return; never replace a failed library load or manufacture a runtime alias.

## Required observations

Preserve stop reason, original instruction tail, PC/arguments, thread state, current thread TLS, hardware TPIDRURO, software helper slot, model value, discarded ranges, library-load results and framebuffer transactions. Budget exhaustion and entry into an idle loop are not a boot/UI success.

Constructed tests must execute the ARM TLS read after alternating thread switches, verify that all TLS representations agree, and preserve helper protections. Memory tests must show discard changes later guest reads to zero while preserving neighboring bytes and permissions. Mixed, file, shared, device, initial and unmapped ranges must remain guarded without partial writes. The default madvise policy must stop without mutation.

## Interpretation

A worker's correct exit and the main event loop establish narrower startup behavior. They do not establish successful camera subsystem initialization, entropy, a complete kernel, timing accuracy or original display output. The `a` process's component log markers need independent call/return and resource-load evidence.
