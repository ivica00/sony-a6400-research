# Execution research implementation

The first implementation is a bounded original Linux interpreter probe. It maps the original application/interpreter and constructs explicit process-entry state. Default mode stops before all kernel responses. The optional `brk` policy supplies a tested guest-only heap contract and stops on other requests. Camera hardware is not implemented.

The `brk-uname` policy also supplies image-backed kernel identity, with guards stopping reads of runtime-unknown fields. It reaches the first filesystem request, which remains unanswered. No host kernel identity or filesystem response is substituted.

The `files` policy adds bounded read-only file contracts over hash-checked image snapshots and stops at successful stat/fstat metadata. Runtime namespaces remain unsupported. See [E0006](../../docs/evidence/0006-read-only-guest-filesystem.md) for the tested scope and current boundary.

Current modules: `images/process_elf.py`, `execution/process_entry.py`, and `execution/interpreter_probe.py`. Launch through `python -m tools.research.probe_interpreter` from the project root after generating the inventory and guest-layout reports, using the project environment.

Responsibilities (other directories remain reserved):

- `images/`: immutable input inventory and patch overlays.
- `execution/`: backend and guest startup.
- `machine/`: evidence-backed platform configuration.
- `devices/`: guest-visible hardware contracts.
- `trace/`: execution events and run reports.
- `frontend/`: display presentation and physical-input delivery.

Select interfaces after the platform investigation and backend experiment. Legacy simulation code remains outside this tree.
