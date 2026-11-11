# Execution research implementation

Bounded clean-room execution and hardware-contract modules for the Sony a6400 (ILCE-6400)
and the shared BIONZ X `CXD90045` platform. The first implementation was a bounded original
Linux interpreter probe; the tree has since grown into the execution backend, the device
contract models and the multi-device target registry.

Launch the probe through `python -m tools.research.probe_interpreter` from the project root
after generating the inventory and guest-layout reports, using the project environment.

## Current modules

- `execution/`: the original-code interpreter/runner (`interpreter_probe.py`) plus the
  opt-in contracts it can serve — OSAL/UIPC messaging, MWF `ObjMsg` wire format, USB
  gadgetcore/otgcore/buspower/event, USB video, GPES/GRM, filesystem/flash namespaces,
  VFAT/EXT2 metadata, threads/TLS and the syscall layer. Every contract is opt-in and
  fails closed at its evidence boundary.
- `targets/`: `TargetProfile` schema, fail-closed evidence validation and the multi-device
  registry (`ilce_6400` verified, `zv_e10` reference chain, explicit stubs for other
  bodies). See [ADDING_A_BIONZX_CAMERA](../../docs/ADDING_A_BIONZX_CAMERA.md).
- `visualization/`: the treemap status renderer and its data provider.
- `images/`: immutable input inventory and patch overlays.
- `machine/`: evidence-backed platform configuration.
- `devices/`: guest-visible hardware contracts.
- `trace/`: execution events and run reports.
- `frontend/`: display presentation and physical-input delivery.

Legacy simulation code remains outside this tree; host-written navigation or rendering is
not firmware compatibility.

## Probe policies

The `brk` policy supplies a tested guest-only heap contract and stops on other requests.
`brk-uname` adds image-backed kernel identity with guards stopping reads of runtime-unknown
fields. The `files` policy adds bounded read-only file contracts over hash-checked image
snapshots and stops at successful stat/fstat metadata. Runtime namespaces remain
unsupported; see [E0006](../../docs/evidence/0006-read-only-guest-filesystem.md) for that
tested scope and boundary. Every later contract follows the same rule: an explicit policy,
a recorded boundary, and no silent success replies.
