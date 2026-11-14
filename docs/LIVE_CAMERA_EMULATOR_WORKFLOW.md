# Workflow: Live Camera and Executing Original Code in the Emulator

This procedure uses the physical ILCE-6400 as the source of observed state, and the emulator as the place for repeatable execution and verification of original instructions. The goal is to discover real firmware and hardware contracts. Executed instruction counts or a successful isolated call do not prove full camera functionality.

## Division of Responsibilities

| Live Camera | Emulator |
| --- | --- |
| Real widgets, models, registers, events, and thread context | Executing original ARM/Thumb instructions over preserved state |
| Checking loaded modules and their real addresses | Tracing reads, writes, calls, and the boundary where a contract is missing |
| Short, pre-planned user experiments in the menu | Repetition, edge cases, invalid indices, and result comparison |
| Final verification of behavior on the physical device | Preparing a verifiable candidate before any physical change |

USB mode changes application state: the menu may disappear from the active tree. Therefore a negative USB scan is not proof that a widget does not exist in MENU mode. A later USB capture of a model may match menu fields, but that does not produce an atomic snapshot nor guarantee that all other data remained unchanged.

## Preparation and Access

1. Read the latest entry at the top of [AGENTS.MD](../AGENTS.MD), then the referenced evidence documents. Older instructions about waiting for experiments may be superseded by a newer completed capture. Do not launch an old observer just because it exists.
2. Use the installed [native USB debugger](NATIVE_USB_DEBUGGER.md) in normal MSC mode via `tools/camera_debugger.py`. Do not repeat Senser bootstrap for routine reads. Use the existing host Python with the required USB/Crypto packages; do not assume the venv contains them.
3. Determine PID, module mapping, version, and source identity. For every function, distinguish ELF address, runtime address, module offset, and Thumb bit.
4. Prepare a narrow question: e.g., which object a lookup returns, which model belongs to a row, which fields change, or where an unsupported call appears.

Routine commands are read-only, not entering service mode:

```powershell
python tools/camera_debugger.py info
python tools/camera_debugger.py maps 149
python tools/camera_debugger.py threads 149
```

The debugger's memory read temporarily pauses the selected thread. It does not freeze all process threads and does not produce an atomic snapshot. Sessions are locked on the host; do not run concurrent camera clients simultaneously.

## Core Research Cycle

1. **Source and identity.** Read only the required code/data windows. Compare code against the corresponding ELF on the camera. If they differ, preserve both versions and differences; do not remove the check. Loaded relocation tables and runtime kernel helpers require separate qualification, not a false claim that they equal the raw file.
2. **Real state.** Preserve object, vtable, fields, and required graph edges. Check type, self-pointer, bounds, and cycles. For models, preserve real child arrays; do not zero-fill missing neighbors. Re-reading the parent can reveal changes during reading, but does not prove atomicity.
3. **Original execution.** Map only observed bytes and verified code into the emulator. Set ABI, stack, return address, and architectural state. Enable appropriate registers for VFP; a pthread path requires real TLS and thread identity. Explicitly mark constructed inputs as control experiments.
4. **Strict boundaries.** Stop on unknown code, unobserved read, snapshot conflict, unsupported system call, or unverified write. Preserve PC, registers, trace, and writes so far. A missing response is not permission for the host to return expected success.
5. **Targeted backfill.** The next read is determined by the concrete boundary from the emulator. Read the relevant code or small data window and replay from the initial state. For writes, prove the contract first: field, width, original instruction, and expected side effects. Changes in an emulator copy are not permission for the same change on the camera.
6. **Controls.** Compare the result with observed state. Add meaningful edge cases: same selection without change, invalid index without write, left/top and right/bottom edges, different execution order in a fresh emulator. Re-run prior checks whenever shared code changes.
7. **Conclusion.** Separate camera observation, static proof, original-function execution, constructed experiment, and still-unverified physical function. Record what the next boundary is and whether a physical experiment is truly needed.

## When a User Experiment on the Camera Is Needed

Build, load, read-back compare, and verify the observer first so that it genuinely waits for the real MENU object. Use a bounded duration, attempt count, output size, and a separate stop-marker. Prefer triggering on a real widget over a fixed delay. Only then ask for a short, clear user sequence: unplugging USB without powering off, MENU, required button presses or wheel turns with pauses, reconnecting.

After returning, **save all temporary logs first**, including the binary file and text status, and only then stop or clean up owned tools. Verify the end marker, result, record count, exact length, and hash. A log without END or with a truncated final object remains explicitly partial; do not fill in missing bytes. `/tmp_bt` in this research is a tmpfs of only 1 MiB.

Delete old owned logs only after verifying equality with the complete local archive. Do not delete unrelated files. The physical SD card for the emulator remains read-only; authorization for camera SD modifications is described in AGENTS.MD.

## Examples Proven Through This Cycle

| Step | Proof and Limitation |
| --- | --- |
| Active menu lookup | E0106: original nested lookup returns the real ListTab in 795 instructions; host does not substitute a separately found object |
| Geometry | E0106: 145 widgets; fresh reverse-order execution yields identical coordinates; separate narrow qualification of Unicorn IT state |
| Model and rows | E0107: all binding fields match; six original indexed lookup calls linked to statically proven row layout |
| Hit area | E0108: 252 original `isHit` checks; separate original selection controls; this is not yet physical input routing |
| TLS and activation | E0109: without TLS, wrong high address; with read main-thread context and real kernel code, passes locking; stops before unverified resource-manager write |

Examples of repeatable local checks, with previously saved private inputs:

```powershell
python -m tools.research.active_menu_snapshot_probe
python -m tools.research.menu_binding_snapshot_probe --active-layout
python -m tools.research.menu_row_snapshot_probe
python -m tools.research.menu_row_hit_snapshot_probe
python -m tools.research.menu_activation_snapshot_probe
python -m tools.research.menu_activation_snapshot_probe --main-thread-control
python -m unittest discover -s tests -q
```

`capture_menu_activation_dependencies` contacts the camera; it is not an offline-only check. Calls are bounded with `--steps`, and main-thread control is marked with a separate argument. Do not expand the allowed-writes list just to make a call finish. The main thread is not automatically proven to be the original UI thread.

## What to Keep and What to Publish

In `docs/evidence/`, record input identity, commands, experiment, results, deviations, remaining boundary, and observer state. Keep short continuation notes at the top of AGENTS.MD; update README, roadmap, and current status without rewriting old failed experiments as successes.

Git tracks source tools, tests, documentation, and summary metadata. Firmware, proprietary ELFs, raw memory, SD contents, checkpoints, and large generated artifacts stay in the private local archive per `.gitignore`. A path to an artifact in a document does not mean its contents are publicly available or that a fresh clone alone can reproduce the experiment without required private inputs.
