# Contributing

Contributions should improve a documented Sony BIONZ X / ILCE-6400 contract, fix a reproducible defect, or clarify evidence and its limits. For larger work, open an issue describing the current boundary, proposed experiment and expected observation.

## Multi-device BIONZ X support

The execution platform is built against the Sony a6400 but models the shared BIONZ X (`CXD90045`) contracts, so owners of other bodies (a6100, a6600, a7 III, ZV-E10 or similar) can join without forking the code. Start with [docs/ADDING_A_BIONZX_CAMERA.md](docs/ADDING_A_BIONZX_CAMERA.md): it explains the `TargetProfile` schema in `src/a6400/targets/`, the read-only probe in `probes/`, and how to submit a profile with an evidence receipt. A partial, honest profile is a valid contribution; a complete guess is not.

## UVC/PTP workstreams

For UVC video and PTP mode, start with [docs/CONTRIBUTING_UVC_PTP.md](docs/CONTRIBUTING_UVC_PTP.md). It lists scoped tasks with acceptance criteria, the relevant evidence records and the labels (`uvc`, `ptp`, `good first issue`, `boundary`). Claim a task by commenting on the matching issue.

## Make a focused change

- Read [AGENTS.MD](AGENTS.MD), the relevant evidence and the [research workflow](docs/LIVE_CAMERA_EMULATOR_WORKFLOW.md).
- Preserve original inputs and existing policy baselines. Stop explicitly at unsupported behavior; do not replace unknown services with success values or host-written camera decisions.
- Keep physical observations, original-code execution, fixture results and inferences distinct. Record firmware/input hashes, commands, results, failures and remaining limitations in `docs/evidence/` for material findings.
- Never include proprietary firmware, extracted binaries, backups, raw RAM captures, credentials or generated payloads. Use constructed fixtures where possible.
- **Language policy:** Use exclusively English for all documentation, evidence records, code comments, docstrings, UI strings, pull requests, and commit messages.

## Validate

No camera is needed for ordinary checks. Install the pinned offline dependencies once and run the suite from the repository root:

```powershell
# Windows (PowerShell), using the existing environment
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe -m unittest discover -s tests -q
```

```bash
# Linux / macOS
python3 -m pip install -r requirements.txt
python3 -m unittest discover -s tests -q
```

The repository-structure, target-profile and status-synchronization contracts are standard-library checks that CI runs on every pull request:

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_repository_layout tests.test_target_profiles tests.test_research_status_sync -v
.\venv\Scripts\python.exe -m tools.research.render_research_status --check
```

Run focused checks during implementation and the full suite after substantive code changes. Report actual failures and environment limitations; do not describe historical test counts as a new run. Documentation-only changes need link/content checks. `requirements.txt` pins the offline suite only: physical experiments and local firmware inputs are not reproducible from a fresh clone.

## Documentation sync

`README.md` and the generated `docs/images/research-status.svg` dashboard are checked against `STATUS_SNAPSHOT` / `TELEMETRY` in `tools/research/a6400_status_data.py`. When a milestone changes the latest evidence record, the evidence count or the recorded suite count, update the data module, regenerate the dashboard with `python -m tools.research.render_research_status --write`, and let `tests/test_research_status_sync.py` + `tests/test_research_status_dashboard.py` prove that the README, the dashboard and the inventory agree. The generator also pins a content-hash query (`?v=...`) on the README image link, so a refreshed dashboard gets a new URL instead of a stale cached render.

## Physical experiments

Device operations require explicit scope and a reviewed plan. Preserve receipts before cleanup; verify restoration rather than inferring it from a host timer. Emulator SD access stays read-only. Do not format, flash, replace drivers or activate experimental UVC as part of routine tests. The current configured-session teardown boundary is unresolved; read E0210–E0218 before proposing another activation. Root [AGENTS.MD](AGENTS.MD) records the owner's existing journal authorization and storage restrictions; it is not blanket permission for contributors to write to a device.

## Pull requests

Explain the problem, resulting behavior, evidence and validation. Link the relevant issue/evidence, state which paths are simulated or physically verified, and list remaining limits. Keep unrelated changes separate. Update status documentation when an evidence boundary changes; preserve superseded findings as history.
