# E0183 — Original ptrace ownership and inactive contract

## Scope

Continued preparation for safe native gadgetcore wrapper publication. This step is offline only: no camera upload, hook, module load, mode change or filesystem write. E0182 remains the current module candidate; the combined PC Remote/UVC/PTP test is not ready.

## Original kernel evidence

Hash-verified retained a6400 kernel SHA-256 `12eeec829407595e28265f7d0db3b88c56f63a9f0fdd725c9c53c66a49643707` contains `ptrace_check_attach` at `0x6013edac`.

The original body requires nonzero target ptrace flags (`task+0x14`) and compares target tracer (`task+0x110`) against current task from the actual ARM thread-info expression (`SP & ~0x1fff`, then `+0xc`). With ignore_state zero, it checks stopped state bit 8 under the target signal lock, handles the group-stop exclusion flag, and calls `wait_task_inactive(target, 8)` at `0x6013ee98`. A zero result from that service produces `-ESRCH` (-3); successful inactivity permits return 0.

Original `sys_ptrace` at `0x6013f324` looks up and retains the target, calls this check at `0x6013f664`, and invokes `arch_ptrace` at `0x6013f680` only after successful checking. The original request expression at `0x6013f654..664` computes ignore_state true only for request 8 (PTRACE_KILL). Request 12 (PTRACE_GETREGS) and 17 (PTRACE_DETACH) use zero. This is relevant because a future control helper could retain normal tracer ownership and provide a real userspace register buffer; no private task-ref implementation has been added.

## Executed controls

`tools/research/probe_uvc_ptp_ptrace_barrier.py` executes the original ARM check body with explicit task/current fixtures. Six cases cover untraced target, wrong tracer, running target, stopped/inactive success, failed inactivity and the ignore_state bypass. Three additional cases execute the original sys_ptrace request expression for GETREGS, KILL and DETACH. All **9 checks pass**.

Command:

```
python -m tools.research.probe_uvc_ptp_ptrace_barrier --output-dir artifacts/analysis/uvc-ptp-ptrace-barrier-e0183
```

Manifest: `artifacts/analysis/uvc-ptp-ptrace-barrier-e0183/manifest.json`.

Locks, migration/preemption services, warnings and wait_task_inactive are explicit service doubles. This establishes the original body's decisions and required service call, not actual scheduler inactivity in the emulator. Task lookup/refcount and arch_ptrace are not executed by this probe. No new module code was changed, so the existing 605-test E0182 result is retained as historical validation, not reported as rerun here.

## Remaining boundary

The E0178 physical all-thread freeze is still CPU lifecycle evidence only. Neither a saved userspace PC nor successful ptrace checking establishes syscall completion, absence of cached VFS targets, or IRQ/EP0/DMA quiescence. A complete owner/thread-set check, publication lifetime/self-pin protocol, and separate USB callback drain are still required. No native fops slot is written by this work. Leave the camera in Mass Storage pending the actual combined-test procedure.
