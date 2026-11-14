# Project instructions

## 1. Objective and working scope

Build an evidence-backed, multi-device Sony BIONZ X (`CXD90045`) environment in which original or modified firmware produces application behavior through verified CPU, OS, and hardware contracts. Host-written navigation, rendering, or camera decisions are not firmware compatibility. Follow the user's current scope; continue authorized work without routine confirmation. Do not spawn subagents unless explicitly requested or required by another applicable instruction.

## 2. Standing authorizations and hardware safety boundaries

- **Read-only camera observations (authorized 2026-11-10):** `tools/camera_debugger.py exec`, native read-only probes, `/proc`, `/sys`, bounded single-page (4 KiB) `/dev/mem` reads, and process-memory reads are always allowed. No writes, mode switches, SD changes, or teardown without explicit scope. Keep complete receipts, remove only owned helpers, and verify camera responsiveness (`/proc/uptime` monotonic, debugger responsive, `/tmp_bt` clean).
- **SAFETY NOTE (`E0454`, 2026-11-10):** Bulk `/dev/mem` physical scans (e.g., 16 MiB chunks) and page-table/kernel-memory sweeps dropped USB and **rebooted the camera**. They are **excluded** from standing read-only authorization; never run them without explicit per-incident user go-ahead.
- **SAFETY NOTE (`E0297`, `E0298`):** Do **not** read `/dev/stream` for OSD capture (rebooted camera). Use safe `im.elf` ptrace (`E0298`: OSD A/B `640×480` RGBA4444).
- **Device & storage boundaries (`E0219`, `E0222`):**
  - Physical SD `E:\` is read-only for emulator inputs. Authorized diagnostic camera writes stay under `/tmp_bt` (except the explicitly authorized small SD diagnostic journal `E0219`, which remains unwritten and requires verified service ownership, non-overwrite creation, bounded write, flush/readback, and restart-survival evidence).
  - `A:/dev/mmca` is SD (`E0222`); `B:/dev/nflasha23` is internal flash and **excluded**. Never guess from drive letters, concurrently write-mount SD, or issue raw storage writes.
  - Ordinary tests must never access USB, invoke service-mode backup, install firmware, replace drivers, or modify the camera. A host monitoring window is not completion, successful STOP, restored hooks, drained DMA, or unloaded-module proof.

## 3. Current technical checkpoint

See [docs/INDEX.md](docs/INDEX.md) and [docs/CURRENT_STATE.md](docs/CURRENT_STATE.md) for the full map. Active workstreams:
- **L2 Kernel Boot (`UnicornMachine`):** `E0415–E0467` — `ARM-CXD900X0` (`0xDA9`), `UC_TLB_VIRTUAL` deferred at `ret_to_user` (`0x6010DF34`), reaches `ld-2.11.2.so` `USR` Thumb (`0x0402E790`, `CPSR=0x30`); next is Thumb TB warm-up at `0x0402E798` → BusyBox `_start` (`0x0000C439`) → `/bin/ash`.
- **L3 User-Space (`InterpreterProbe`):** `E0298–E0340`, `E0473` — `--thread-timeslice` reaches 88+ threads (`THREAD_APP`, `Appframework`, `gui.so`); blocked on guest `stella HeapAllocator` `0x4C`/`0x50` pool-boundary overrun (`libObj+0x79FE14`).
- **Track B Physical UVC/PTP (`054C:0322`):** `E0468`, `E0471`, `E0476` — Run B25 `S1` root-caused EP0 Status-OUT NAK window; `E0476` status pre-arm module (`dcc2f64f…`, `117/8/0`, Unicorn `8/8 PASS`) awaits explicit user GO for Run B26.
- **Multi-Device Platform (`CXD90045`):** `E0477–E0489`, `E0506–E0509` — 13 bodies / 9 kernels mapped + `ILCE-6400A` 1.01 reference qualification and USBSTOR native `GetModelInfo` (`0032858730`, 2.727 ms); `TargetProfile` registry in `src/a6400/targets/`.

## 4. Fidelity and evidence invariants

- Separate observations, inference, assumptions, fixtures, and physical verification. Bound execution; stop with PC, arguments, and reason at unsupported imports, syscalls, devices, memory, or metadata. Faults and limits are not success.
- No silent zero/success replies, automatic mappings, fabricated queues/UI, or weakened guards to advance execution. Add contracts via explicit opt-in policies; retain default no-response and earlier regression baselines.
- Guest access uses a declared namespace and allowlisted hash-checked inputs, never arbitrary host paths/syscalls. Unsupplied runtime mounts are unknown, not verified absent.
- Original code owns application logic/rendering in fidelity experiments. A bounded instruction probe is not a booted kernel, timing model, complete machine, or proof of deployment safety.
- Preserve firmware, backups, and captures; modify separate outputs or overlays. Never silently refresh hashes. Keep upstream checkouts and `venv/` in place; do not change their Git state incidentally.
- Material evidence records need input/tool identities, exact command/policy, original instruction support, serviced operations, observation/stop, assumptions, failures, repeatability, and next boundary. Preserve failed receipts and mark superseded conclusions. Update `README.md`/roadmap when status changes; never publish proprietary inputs or secrets.

## 5. Implementation, verification, and research tooling

- Use small components and shared path/memory rules (`project_paths.py`). Prefer `rg`, constructed fixtures, and focused ABI/state/error/provenance/ARM checks. Generated fixtures belong under `artifacts/tests/`.
- Launch first-party scripts as modules from the repository root (`python -m tools.research.<tool>`, `python -m legacy.<prototype>`).

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests -q
.\venv\Scripts\python.exe -m tools.research.probe_interpreter
```

- Run focused checks during work, the full suite after substantive code changes, and real-firmware replays when their path changes. Preserve reports under new output directories. Boundary exits (including the `files` probe's expected exit 2) are not regressions.
- For substantial ARM/Thumb analysis, prefer REA/Ghidra via WSL and `tools.research.rea_wsl_batch`; reuse only identity-matched evidence. Read [docs/REA_WORKFLOW.md](docs/REA_WORKFLOW.md) and [docs/DEPENDENCY_WORKFLOW.md](docs/DEPENDENCY_WORKFLOW.md) before following call chains.
- References: [CONTRIBUTING.MD](CONTRIBUTING.MD), [docs/LIVE_CAMERA_EMULATOR_WORKFLOW.md](docs/LIVE_CAMERA_EMULATOR_WORKFLOW.md), [docs/ADDING_A_BIONZX_CAMERA.md](docs/ADDING_A_BIONZX_CAMERA.md).
- Complete historical experiment logs are preserved verbatim in [docs/archives/agent-notes-2026-11-13-e0210-to-e0476.md](docs/archives/agent-notes-2026-11-13-e0210-to-e0476.md) and [docs/archives/agent-notes-2026-11-09.md](docs/archives/agent-notes-2026-11-09.md). Keep `AGENTS.md` concise; refresh `docs/images/status_a6400.png` only for substantive research milestones.
