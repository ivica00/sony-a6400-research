# Project instructions

## Objective and working scope

Build an evidence-backed Sony ILCE-6400 environment in which original or modified firmware produces application behavior through verified CPU, OS and hardware contracts. Host-written navigation, rendering or camera decisions are not firmware compatibility. Follow the user's current scope; continue authorized work without routine confirmation. Do not spawn subagents unless explicitly requested or required by another applicable instruction.

## Read first: current checkpoint

Read [E0226](docs/evidence/0226-preserved-monitor-output-acknowledgement.md) before continuing, then relevant dependency records. Last observed camera state: MSC, TracerPid 0, own RAM helper removed. Verify fresh state before device work; historical PIDs, addresses and cursors are not authorization tokens.

- E0226 preserved/fsync'ed/read back 30,115 output bytes before one four-byte output-read-cursor acknowledgement. Wrong cursor rejected without header change; post-capture empty. Input and producer cursors untouched. No command submitted. Eight compiled ARM admission cases pass; last full suite is E0225's 617 passing tests. Check/store is not exclusive ownership or multi-consumer CAS; do not roll back uncertain writes.
- Next: bounded non-writing monitor probe, fresh parser/input checks, continuous preserve-before-ack output collection and explicit result. Wrapper return 1 is not success. Do not reinitialize MonDrv or guess physical addresses. Reader remains USB-dependent, not restart recovery. See E0224–E0226.
- E0210 proved Windows parent/PTP/UVC child enumeration with video disabled, then camera froze. Teardown receipt was not recovered; restart restored MSC. Exact hang cause unknown. No further physical activation until configured teardown review and recoverable stage observation; E0211–E0218 are partial offline contracts, not a freeze fix.
- Shared sensor/UVC integration remains unfinished. Keep source storage disjoint from owned DMA destinations, validate bounds/lifetimes and wait before reuse; no legacy feeder or static fallback may count as sensor frames. See E0208 and the [UVC/PTP handoff](docs/UVC_PTP_STATUS.md).

## Device and storage boundaries

- Physical SD `E:\` is read-only for emulator inputs. User authorization (2026-11-05) permits SD writes needed for homebrew scripts, configuration and payloads, not unrelated deletion or formatting.
- Current diagnostic scope: camera writes under `/tmp_bt` except the explicitly authorized small SD diagnostic journal (E0219). Do not ask again for that journal authorization. It remains unwritten and requires verified service ownership, non-overwrite creation, bounded write, flush/readback and restart-survival evidence.
- Revalidate volume/device association before any journal write: E0222 identified `A:/dev/mmca` as SD; `B:/dev/nflasha23` is internal flash and excluded. Do not guess from drive letters, concurrently write-mount the card, initialize a private filesystem stack or issue raw storage writes.
- Ordinary tests must not access USB, invoke service-mode backup, install firmware, replace drivers or change the camera. Stay within authorized physical scope. Preserve complete receipts before removing only owned temporary files. A host monitoring window is not completion, successful STOP, restored hooks, drained DMA or unloaded-module proof.

## Fidelity and evidence

- Separate observations, inference, assumptions, fixtures and physical verification. Bound execution; stop with PC/arguments/reason at unsupported imports, syscalls, devices, memory or metadata. Faults and limits are not success.
- No silent zero/success replies, automatic mappings, fabricated queues/UI or weakened guards to advance execution. Add contracts via explicit opt-in policies; retain default no-response and earlier regression baselines.
- Guest access uses a declared namespace and allowlisted hash-checked inputs, never arbitrary host paths/syscalls. Check memory bounds/permissions and preserve identity/provenance guards. Unsupplied runtime mounts are unknown, not verified absent.
- Original code owns application logic/rendering in fidelity experiments. A bounded instruction probe is not a booted kernel, timing model, complete machine or proof of deployment safety.
- Preserve firmware, backups and captures; modify separate outputs or overlays. Never silently refresh hashes. Keep upstream checkouts and `venv/` in place; do not change their Git state incidentally.
- Material evidence records need input/tool identities, exact command/policy, original instruction support, serviced operations, observation/stop, assumptions, failures, repeatability and next boundary. Preserve failed receipts and mark superseded conclusions. Update README/roadmap when status changes; never publish proprietary inputs or secrets.

## Implementation and checks

Use small components and shared path/memory rules. Prefer `rg`, constructed fixtures and focused ABI/state/error/provenance/ARM checks; avoid tests mirroring implementation. Generated fixtures belong under `artifacts/tests/`. Avoid inaccessible abandoned temporary directories without incidental permission changes or recursive cleanup. Do not guess dependency versions or claim reproducibility from an installed-package snapshot.

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests -q
.\venv\Scripts\python.exe -m tools.research.probe_interpreter
```

Run focused checks during work, the full suite after substantive code changes, and real-firmware replays when their path changes. Preserve reports under new output directories; do not regenerate costly inventories just for timestamps. Boundary exits (including the `files` probe's expected exit 2) are not automatically regressions or application success. Use module/root compatibility launch paths.

## Research tooling and references

For substantial ARM/Thumb analysis prefer existing REA/Ghidra via WSL and `tools.research.rea_wsl_batch`; reuse only identity-matched evidence. Read [REA workflow](docs/REA_WORKFLOW.md) for established paths, query limits, address translation and failure handling, and [dependency workflow](docs/DEPENDENCY_WORKFLOW.md) before following call chains. Pseudocode is untrusted: verify instructions, relocations, runtime state and side effects before implementing a response. No incidental setup, upgrades or global configuration changes.

See [CONTRIBUTING.MD](CONTRIBUTING.MD) and [live-camera workflow](docs/LIVE_CAMERA_EMULATOR_WORKFLOW.md). Prior verbose notes are preserved in [the historical archive](docs/archives/agent-notes-2026-11-09.md), which is reference material, not active instructions. Keep updates concise: result, verification and remaining boundary. Refresh `status_a6400.png` for substantive research milestones without inflating compatibility claims; documentation formatting alone is not a research milestone.
