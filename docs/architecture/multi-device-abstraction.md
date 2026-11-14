# Multi-Device Abstraction & Universal Emulator Design

This document specifies how `TargetProfile` (`src/a6400/targets/`) drives both execution backends (`UnicornMachine` for L2 kernel boot, `InterpreterProbe` for L3 user-space) so any Sony BIONZ X (`CXD90045`) camera can run without hardcoded `ILCE-6400` constants.

## 1. Design Principles

1. **No implicit `a6400` fallback for another body**: Every kernel symbol address, UIPC queue ID, USB identity, boot load address, and partition layout must come from the selected `TargetProfile` (or directly from the target's decoded `vmlinux.bin` / `boot/` artifacts).
2. **Fail-closed evidence discipline**: `TargetProfile` refuses to construct any claim without an `EvidenceRef`. Unknown fields stay `None` / empty and stop execution explicitly with a `boundary` report rather than guessing.
3. **Backward compatibility**: Default CLI invocations without `--target` may default to `ilce_6400` for regression continuity, while `--target <id>` selects any registered profile from `DEFAULT_REGISTRY`.

## 2. Profile-Driven Configuration (`BootLayoutSpec` & `kallsyms`)

`TargetProfile` provides:
- `boot_layout` (`BootLayoutSpec`): `machine_id`, `page_offset`, `kernel_load`, `initrd_load`, `boot_params`, `ram_banks`, and `mmio_ranges` (defaulting to the verified `CXD90045` SoC map when declared on the profile).
- `kallsyms`: Kernel symbol addresses required by `UnicornMachine` hooks (`ret_to_user`, `do_page_fault`, `do_PrefetchAbort`, `cpu_v7_switch_mm`, `__dabt_svc`, `__pabt_svc`, `__dabt_usr`, `__pabt_usr`, `v7_early_abort`, `v7_early_pabort`) and `InterpreterProbe` / native modules (`usb_gadgetcore_ioctl`, `osal_snd_msg`, etc.).
- `uipc_queues`: Per-body OSAL queue IDs (populated from live `/proc/osal/uipc` probes; empty for offline-only profiles).
- `usb` & `modules`: Stock/observed/authored VID/PIDs and hash-pinned `.ko`/`.so` components (e.g., `devno.ko` presence/absence of `/dev/usb/video`).

## 3. Directory & Package Responsibilities

- `src/a6400/targets/bodies/<target_id>.py`: One file per camera body, imported into `src/a6400/targets/catalog.py`.
- `src/a6400/machine/`: SoC-level `CXD90045` constants (`soc_cxd90045.py`), boot contract (`boot_contract.py`), and MMU/exception primitives.
- `src/a6400/devices/`: Reusable device contracts parameterized by `TargetProfile` and explicit opt-in policies.
- `src/a6400/execution/`: `UnicornMachine.from_target(profile, ...)` and `InterpreterProbe(..., target=profile)` consume the profile instead of module-level `a6400` literals.
