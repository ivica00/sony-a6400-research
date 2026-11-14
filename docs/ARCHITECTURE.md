# Target Architecture

See [docs/INDEX.md](INDEX.md) for the complete documentation map.

The platform models the **Sony BIONZ X (`CXD90045`)** camera family across 13 bodies and 9 kernels ([PLATFORM_MODEL.md](PLATFORM_MODEL.md)), driving both full-system kernel boot (**L2**, `UnicornMachine`) and user-space process execution (**L3**, `InterpreterProbe`) from evidence-backed `TargetProfile` definitions.

```text
Original / patched image + TargetProfile (src/a6400/targets/)
                         |
           Machine & Boot Contract (src/a6400/machine/)
                         |
     Execution Backend: L2 UnicornMachine / L3 InterpreterProbe
                         |
       Guest-visible Device & OSAL Contracts (src/a6400/devices/)
                         |
     Display (OSD A/B) / Storage / Traces / Differential Validation
```

## Package Responsibilities (`src/a6400/`)

| Component | Contract |
| --- | --- |
| `targets/` | Per-body `TargetProfile` definitions (`targets/bodies/`), fail-closed `EvidenceRef` validation, and `DEFAULT_REGISTRY` |
| `machine/` | `CXD90045` SoC memory/MMIO layout (`soc_cxd90045.py`), `UpdaterBootContract`, `ATAGS`/`kemco`, `EXBL`, and `MachineDescriptor` |
| `devices/` | Guest-visible hardware and kernel contracts (PL011 UART0, GICv1, CXD Timer, CRCDC, OSAL/UIPC, DWC3/USB, GPES/GRM, VFAT/eMMC) |
| `execution/` | L2 full-system kernel runner (`unicorn_machine.py`) and L3 user-space process runner (`interpreter_probe.py`) + checkpointing |
| `images/` | Hash-checked input inventory, ELF process mapping, partition layouts, and isolated patched overlays |
| `trace/` | Structured execution events, deterministic ordering, and explicit boundary reports |
| `frontend/` | OSD A/B presentation (`640×480` RGBA4444) and physical-input delivery without host-invented UI |
| `visualization/` | Treemap and research status SVG rendering |

## Deep-Dive Technical References

- [Multi-Device Abstraction](architecture/multi-device-abstraction.md) — how `TargetProfile` configures `UnicornMachine` and `InterpreterProbe`
- [L2 Kernel Boot & MMU](architecture/l2-kernel-boot-and-mmu.md) — `EXBL`, `kemco`/ATAGS, `UC_TLB_VIRTUAL`, abort delivery, Thumb `ret_to_user`
- [L3 User-Space & IPC](architecture/l3-userspace-and-ipc.md) — `im.elf`, OSAL/UIPC bit-15 local queues, `MWF::ObjMsg`, `--thread-timeslice`, `stella` heap bug
- [Hardware & Partitions](architecture/hardware-and-partitions.md) — `nflasha` map, GPES `SMAPH-S30` BAR `0xF1000000`, DWC3 EP0

## Invariants

- Original guest code owns application state, navigation, and rendering in fidelity runs.
- Host code may decode the display format (`640×480` RGBA4444) and present pixels; it must not redraw camera widgets.
- Device models own hardware state; application-specific hooks do not silently substitute results.
- Every unsupported access or service produces an explicit stop (`boundary`) or a declared opt-in experimental policy.
- Models are validated at their guest-visible boundary; instruction compatibility does not imply cycle accuracy.

## Scope Boundaries

Boot compatibility, UI compatibility, update acceptance, image-output equivalence, and timing fidelity are separate claims. Sensor, lens, analog effects, and proprietary DMP `SMAPH-S30` GPU rasterization require hardware or additional models.
