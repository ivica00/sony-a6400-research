# Phase 0 progress — 2026-10-18

Implemented:

- Read-only inventory command hashes all local firmware and backup files, records package versions, native library hashes, upstream HEAD revisions when available, and upstream license-file hashes. The generated `artifacts/inventory/baseline.json` is local and ignored by source control.
- Explicit `research` (default for existing callers) and `strict` modes in the preserved harness. Strict mode rejects unresolved symbols, unsupported relocation forms, unmapped accesses, MMIO, HLE services, mock Sony subsystems, host navigation, and host rendering.
- Structured event reports with PCs and details. Function execution distinguishes return, unsupported behavior, fault, timeout, and instruction-budget exhaustion. Limits are configurable and failed execution returns no success value.
- A strict-first audit command, plus software-only regression tests using actual ARM instructions for return/fault/limit/device-access cases.

First observed strict loading blocker: `libObj.so` imports `_ZTVN10__cxxabiv120__si_class_type_infoE`, which is unresolved in the current loader. This is a C++ runtime dependency to investigate, not evidence of missing camera hardware. Loading stops before screen setup; no original UI execution is claimed.

## Commands

Run from the project root:

```powershell
.\venv\Scripts\python.exe -m tools.research.inventory
.\venv\Scripts\python.exe -m tools.research.audit_execution
.\venv\Scripts\python.exe -m unittest discover -s tests -v
```

The audit defaults to strict and returns exit code 2 for unsupported behavior, saving `artifacts/execution/latest.json`. Use `--report PATH` for another report location. `--mode research` permits known substitutions and records them; it does not validate fidelity. Existing GUI commands continue to use research mode.

## Remaining work

Follow-up delivered: [platform and loader evidence](evidence/0001-platform-and-loader.md), a 474-file ELF inventory, corrections for REL symbol addends and nonzero load addresses, failed-load rollback, and strict TLS rejection. The C++ symbol is present in the extracted runtime and multiple executables; original process scope still needs investigation. Run `python -m tools.research.elf_inventory` to regenerate the static reports.

Execution follow-up: [E0003](evidence/0003-original-interpreter-boundary.md) records a separate original-interpreter probe reaching `brk(0)` without a kernel response. This does not remove the legacy harness's TLS/loader limitations or complete full-system startup.

- The inventoried environment is a snapshot, not a fresh-install lock. Confirm required dependencies, upstream origins/working-tree modifications, package/native provenance, and firmware authenticity separately.
- Audit supported relocation formulas and loader mapping/initialization behavior; accepting a relocation type does not prove correct ABI implementation.
- Inventory ELF dependencies and locate the matching C++ runtime; map original startup before selecting a backend.
- Research mode still contains legacy synthetic state and UI behavior. Events identify major substitution boundaries, not an exhaustive trace of every Python operation. Do not run indefinitely with unbounded event accumulation.
- Strict mode is a diagnostic harness, not a full-system emulator. The original guessed machine configuration remains unverified.
- Build camera baselines and complete the original-rendering evidence gate in later phases.

No device operations, firmware patches, or camera writes were performed for this step.
