# Experiment 0002: Guarded urandom Open and Read Boundary

## Question and policy

Can the original `libssp` constructor open the static image's verified `/dev/urandom` node and reach its first read without supplying unknown entropy?

Run `tools.research.experiment_ui_boot` with `--urandom-open`, 45,000,000 instructions and a 240-second execution timeout, preserving a unique `--report` path. This opt-in supplements the `threads` policy; it does not alter the default Package H namespace contract. Use the preserved image/kernel hashes recorded in E0024. The same injected messages and process-entry assumptions as E0023 apply; authentic camera boot is not claimed.

## Expected observation and stop

A verified old-encoded 1:9 character inode permits the exact read-only open. Original code then reaches `read(fd, guard_pointer, 4)`. The host must stop before returning from that read or copying bytes. Report `entropy_state_not_supplied`, buffer/count, zero bytes supplied, input identities, syscall PC and original instruction tail. Expected observed count: 41,955,226 instructions, 601 supplied syscall responses, zero framebuffer transactions.

No arbitrary random bytes, host device reads, manufactured EOF/error, writable mount, or framebuffer defaults may be added to select a later camera path. Unsupported device metadata and operations remain explicit stops.

## Controls

- Run without the option: preserve E0023's 41,953,485-instruction namespace boundary.
- Repeat the opted-in run with a separate report and compare status, count, syscall responses, arguments/PC and instruction tail.
- Use constructed unit fixtures to reject wrong device identity, missing provenance, wrong node type, write flags, unknown paths/aliases, exhausted descriptors and unsupported operations. Execute actual ARM open/read syscalls and verify unchanged target memory at the read stop.
- `tools.research.entropy_trace` separately executes the original kernel's open/read wrapper windows with constructed inode/file/stack inputs. These windows do not boot the kernel or supply its entropy pool.

## Interpretation

Reaching the read establishes a specific library dependency and a bounded open contract. It does not establish random-device output, complete linking, display initialization, UI behavior or physical-camera equivalence. See [E0024](../evidence/0024-urandom-dispatch-and-read-boundary.md) for observations and limitations.
