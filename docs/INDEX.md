# Documentation Index

Central navigation map for the Sony BIONZ X (`CXD90045`) universal emulator and reverse-engineering platform.

## 1. Architecture & Multi-Device Platform

| Document | Purpose |
| --- | --- |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Layered system architecture (`targets/`, `machine/`, `devices/`, `execution/`, `images/`, `trace/`, `frontend/`) and L0–L3 emulation levels |
| [PLATFORM_MODEL.md](PLATFORM_MODEL.md) | Cross-model `CXD90045` evidence across 13 bodies and 9 kernels (`E0477–E0489`) |
| [ADDING_A_BIONZX_CAMERA.md](ADDING_A_BIONZX_CAMERA.md) | Step-by-step L0–L3 guide for adding support for a new camera body |
| [architecture/multi-device-abstraction.md](architecture/multi-device-abstraction.md) | How `TargetProfile`, `BootLayoutSpec`, and `kallsyms` drive `UnicornMachine` and `InterpreterProbe` without hardcoded `a6400` constants |
| [architecture/l2-kernel-boot-and-mmu.md](architecture/l2-kernel-boot-and-mmu.md) | L2 full-system kernel boot (`EXBL`, `ARM-CXD900X0`, `kemco`/ATAGS, `UC_TLB_VIRTUAL`, ARMv7 aborts, Thumb `ret_to_user`) |
| [architecture/l3-userspace-and-ipc.md](architecture/l3-userspace-and-ipc.md) | L3 user-space `im.elf` execution, OSAL/UIPC queues, `MWF::ObjMsg`, `--thread-timeslice`, and `stella HeapAllocator` findings |
| [architecture/hardware-and-partitions.md](architecture/hardware-and-partitions.md) | `nflasha` flash partition layout, GPES `SMAPH-S30` BAR `0xF1000000`, OSD A/B display, and DWC3 EP0 USB gadget notes |

## 2. Current Status & Workflows

| Document | Purpose |
| --- | --- |
| [CURRENT_STATE.md](CURRENT_STATE.md) | Active checkpoint across all four tracks (L2 Boot, L3 App/GUI, Track B UVC/PTP, Multi-Device) |
| [REPOSITORY.md](REPOSITORY.md) | Repository layout, module launch paths, and structural CI checks |
| [LIVE_CAMERA_EMULATOR_WORKFLOW.md](LIVE_CAMERA_EMULATOR_WORKFLOW.md) | Safe read-only live camera observation and emulator handoff workflow |
| [NATIVE_USB_DEBUGGER.md](NATIVE_USB_DEBUGGER.md) | Native USB debugger protocol and safety rules |
| [REA_WORKFLOW.md](REA_WORKFLOW.md) | Ghidra / WSL reverse-engineering workflow (`tools.research.rea_wsl_batch`) |
| [DEPENDENCY_WORKFLOW.md](DEPENDENCY_WORKFLOW.md) | Dependency and call-chain tracing workflow |
| [VALIDATION.md](VALIDATION.md) | Differential validation and fidelity rules |

## 3. UVC / PTP & Feature Workstreams

| Document | Purpose |
| --- | --- |
| [UVC_PTP_STATUS.md](UVC_PTP_STATUS.md) | Detailed status of Track B UVC/PTP composite transport |
| [CONTRIBUTING_UVC_PTP.md](CONTRIBUTING_UVC_PTP.md) | Contributor guide for UVC/PTP work |
| [ARCHITECTURE_UVC_MONITOR.md](ARCHITECTURE_UVC_MONITOR.md) | UVC monitor architecture (hash-pinned by `E0348`) |
| [UVC_HANDOVER_PLAN.md](UVC_HANDOVER_PLAN.md) | UVC/PTP handover plan |
| [CINEMAHUD_STOCK_PTP.md](CINEMAHUD_STOCK_PTP.md) | CinemaHUD stock PTP reference |
| [ROADMAP.md](ROADMAP.md) | Long-term project roadmap |

## 4. Evidence, Decisions & Archives

| Directory / File | Purpose |
| --- | --- |
| [evidence/](evidence/) | Dated, hash-pinned evidence records (`0001`–`0489+`) |
| [decisions/](decisions/) | Architectural decision records (ADRs) |
| [archives/agent-notes-2026-11-13-e0210-to-e0476.md](archives/agent-notes-2026-11-13-e0210-to-e0476.md) | Complete verbatim archive of `AGENTS.md` experiment logs `E0210–E0476` |
| [archives/agent-notes-2026-11-09.md](archives/agent-notes-2026-11-09.md) | Earlier `AGENTS.md` historical notes (prior to 2026-11-09) |
| [archives/research-status-through-e0298.md](archives/research-status-through-e0298.md) | Archived README status narrative through `E0298` |
