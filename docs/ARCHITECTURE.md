# Target architecture

Status: target architecture proposed, with a bounded process-execution research slice implemented. Directory names alone do not establish implemented functionality.

Implementation update: the bounded process probe in `execution/` and `images/` now reaches the original interpreter's first syscall; see [E0003](evidence/0003-original-interpreter-boundary.md). Other architecture components remain proposed. No full-machine backend has been selected.

```text
Original or patched image + explicit device-state snapshot
                         |
                  Image/partition loader
                         |
        Execution backend + original software stack
                         |
           Guest-visible device and bus contracts
                         |
      Display output / storage / traces / other observations
                         |
        Presentation frontend and differential validation

Recorded physical inputs --> device input boundary
```

## Responsibilities

| Component | Contract |
| --- | --- |
| `images` | Hash and inventory inputs; preserve originals; construct isolated patched overlays; record partition layout and loader decisions |
| `execution` | CPU/backend integration, architectural state, execution stop reasons, guest startup, debugger integration |
| `machine` | Evidence-backed memory map, address ownership, CPU configuration, reset and scheduling |
| `devices` | Register semantics, resets, interrupts, DMA, clocks, storage, display and physical-input interfaces |
| `trace` | Structured events, deterministic ordering, unsupported-operation reports, reproducible run metadata |
| `frontend` | Present guest output; translate user actions to physical inputs; expose debugger status without inventing camera behavior |

Use typed interfaces once the backend and platform evidence are sufficient. Avoid premature device APIs based on the prototype's guessed addresses.

## Backend decision

First determine the real boot/runtime environment. Prefer a full-system backend with a custom machine model if original kernel and drivers must execute. QEMU is a candidate, not a selected or working a6400 implementation. A generic ARM board is not interchangeable with Sony hardware.

Keep Unicorn for bounded routines and dependency discovery. A user-space vertical slice may accelerate original UI research, provided substituted services are explicit and results are scoped to that slice. This does not satisfy the full-machine milestone.

Record the choice in `docs/decisions/` with evidence, alternatives, a minimal experiment, and rejection criteria. Reconsider it if the platform requires unsupported processor or device behavior.

## Invariants

- Original guest code owns application state, navigation, and rendering in fidelity runs.
- Host code may decode the actual display format, composite hardware planes according to documented device behavior, and present pixels. It must not redraw camera widgets.
- Device models own hardware state; application-specific hooks do not silently substitute results.
- Every unsupported access or service produces an explicit stop or a declared experimental approximation. Approximate runs cannot pass a strict fidelity gate.
- Reset state, nonvolatile state, clock/event ordering, external inputs, and firmware identity belong to the run definition.
- A function timeout is a distinct failure/stop reason, never a successful return.
- Models are validated at their guest-visible boundary. Instruction compatibility does not imply cycle accuracy.

## Scope boundaries

Boot compatibility, UI compatibility, update acceptance, image-output equivalence, and timing fidelity are separate claims. Sensor, lens, analog effects, proprietary processing engines, and other processors may require additional models or physical hardware. No universal exactness claim follows from a successful boot or screen.

Reference: [Unicorn's CPU scope](https://www.unicorn-engine.org/docs/beyond_qemu.html), [QEMU Arm board requirements](https://www.qemu.org/docs/master/system/target-arm.html). These explain backend boundaries, not Sony platform facts.
