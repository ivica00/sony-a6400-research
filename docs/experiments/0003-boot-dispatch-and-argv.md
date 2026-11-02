# Experiment 0003: Bootin Dispatch and Argument-Selected Startup

## Question

Which launch and forwarding requests does original `bootin.elf` issue for Task 94 phase messages, and what happens when `im.elf` starts with those recovered arguments without synthetic queue events?

## Bounded dispatch

Run `python -m tools.research.boot_event_trace` with the existing project interpreter. The tool verifies the ELF identity from the preserved inventory and executes the original callback independently for each constructed input. Stop before the `system` PLT entry or message helper; never invoke either as a host operation. For the message-layout window, state explicitly that successful allocation and a writable test buffer are constructed preconditions. Do not infer camera timing, delivery order or process availability from the isolated cases.

Expected observations: events `0x940031`–`0x940037` request `im.elf s/g/r/u/l/i/a &`; `0x940038` returns `0xfffffc06`. Additional cases expose forwarding destinations and original construction of the prefix/body words. Preserve trace, input/output registers, hashes and stop status.

## Original startup

Use `tools.research.experiment_ui_boot --argument i --stimulus none --urandom-open` with a 45-million-instruction and 240-second bound and a distinct report. This supplies a source-backed argument but not a full camera boot environment. Expect the guarded entropy stop documented in E0025; do not supply invented random bytes to pass it.

For `--argument a --stimulus none`, use a three-million-instruction and 60-second bound for diagnostics. Earlier longer exploration only repeated a futex loop. `--watch-word 0x7feffd0c` passively records at most 128 overlapping writes to investigate stack/context ownership. The watch must not alter memory, registers or syscall responses. Exhaustion is not a successful initialization.

## Controls and interpretation

Retain old experimental-event defaults and E0024's entropy baseline. Verify the Linux futex mismatch error (`EAGAIN`, not `EINVAL`) with constructed state tests. Distinguish original component log markers from actual library opens, init calls, rendered buffers and display submissions. The first guest-produced camera UI milestone remains open.

See [E0025](../evidence/0025-boot-producers-and-argument-selected-startup.md) for identities, observations, configuration history and remaining dependencies.
