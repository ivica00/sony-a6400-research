# Experiment 0001 — Original interpreter to first unsupported boundary

Status: first-boundary gate implemented and reproduced; [E0003](../evidence/0003-original-interpreter-boundary.md) records 1,183 original interpreter instructions ending at `brk(0)`, with no response supplied. Kernel-contract and application-entry gates remain open. Scope: original Linux process startup research, not full-system or camera fidelity validation.

Follow-up: [E0004](../evidence/0004-guest-brk-contract.md) adds an optional tested guest heap contract. The original linker now reaches `uname` after 2,222 instructions. The no-response baseline remains available; application-entry and full-system gates remain open.

Further progress: [E0005](../evidence/0005-guarded-kernel-identity.md) adds guarded, image-backed `uname` and reaches the unanswered `access` check for `/etc/ld.so.preload` at 3,091 instructions. Runtime-unknown identity fields cannot silently advance execution.

Filesystem progress: [E0006](../evidence/0006-read-only-guest-filesystem.md) adds read-only image file contracts, reaches 5,078 instructions and stops at `stat64` success for `/lib`. Application-entry and full-system gates remain open.

## Question

Can the extracted guest interpreter begin executing for `im.elf` from an ABI-correct process-entry state, and what is its first required host/kernel interaction?

This avoids substituting a C++ runtime vtable or adding another success stub. Use the guest interpreter to perform its own relocation/TLS work once the required process and syscall contracts are available.

## Inputs and preconditions

- Verify original `im.elf`, interpreter, and candidate-library hashes from the inventory.
- Resolve guest paths using original image metadata, not guessed Windows filename aliases.
- Keep all original images read-only. Any future guest write target must be isolated and declared.
- Recover the relevant ARM Linux process-entry contract from primary ABI/kernel sources before implementing the stack/auxiliary vector. Include program headers, interpreter load bias, application entry, page size, arguments, environment, alignment, and any required platform/feature values. Do not claim a CPU feature configuration solely because the ELF says ARM.
- Record a provisional CPU selection as an experiment assumption, not verified camera hardware.

## Implementation boundary

1. Build a separate headless process-entry harness; do not reuse Python menu/state rendering or HLE service trampolines.
2. Map the application and original interpreter according to ELF program headers, permissions, file sizes, zero-fill, and alignment constraints. Leave the interpreter responsible for guest dynamic linking.
3. Construct explicit process-entry state and start at the original interpreter entry point.
4. Trap all syscalls/exceptions before emulating their results. Record syscall number, arguments, PC, instruction-set state, and the fault/stop reason. Do not execute guest syscalls on the host.
5. Set instruction and wall-time limits; all stops produce a structured report.

## First exit gate

A run must demonstrate an original interpreter instruction path from the specified entry, reproducible initial state, and one explicit boundary report. It must not reach a convincing UI through a host fallback. Returning success for unsupported kernel operations is a failure of the experiment.

## Subsequent gates

After documenting the first boundary, implement only evidenced Linux syscall contracts using an isolated guest VFS and bounded guest memory access. Track opens/maps, signal/TLS setup, allocation, and original linker progress. Treat camera-driver `ioctl`, IPC, threading, and scheduler dependencies separately; stop on unsupported behavior.

The immediate follow-up target is original interpreter transfer to the application's entry, not UI rendering. A successful process slice does not close the full-machine boot milestone. Device/process startup requirements found here inform the later full-system backend choice.

## Remaining research

Normal `im.elf` arguments, loader search policy/symbol versioning, selected database entries, writable persistent state, display/input contracts, and original thread/service behavior are unresolved. The static plan's zero missing references does not imply a runnable process.
