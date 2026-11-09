# Contributing

Contributions should improve a documented Sony ILCE-6400 contract, fix a reproducible defect, or clarify evidence and its limits. For larger work, open an issue describing the current boundary, proposed experiment and expected observation.

## Make a focused change

- Read [AGENTS.MD](AGENTS.MD), the relevant evidence and the [research workflow](docs/LIVE_CAMERA_EMULATOR_WORKFLOW.md).
- Preserve original inputs and existing policy baselines. Stop explicitly at unsupported behavior; do not replace unknown services with success values or host-written camera decisions.
- Keep physical observations, original-code execution, fixture results and inferences distinct. Record firmware/input hashes, commands, results, failures and remaining limitations in `docs/evidence/` for material findings.
- Never include proprietary firmware, extracted binaries, backups, raw RAM captures, credentials or generated payloads. Use constructed fixtures where possible.

## Validate

From the project root, using the existing Windows environment:

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests -q
```

Run focused checks during implementation and the full suite after substantive code changes. Report actual failures and environment limitations; do not describe historical test counts as a new run. Documentation-only changes need link/content checks. No camera is needed for ordinary checks. Dependencies and local firmware inputs are not yet a reproducible fresh-install bundle.

## Physical experiments

Device operations require explicit scope and a reviewed plan. Preserve receipts before cleanup; verify restoration rather than inferring it from a host timer. Emulator SD access stays read-only. Do not format, flash, replace drivers or activate experimental UVC as part of routine tests. The current configured-session teardown boundary is unresolved; read E0210–E0218 before proposing another activation. Root AGENTS.MD records the owner's existing journal authorization and storage restrictions; it is not blanket permission for contributors to write to a device.

## Pull requests

Explain the problem, resulting behavior, evidence and validation. Link the relevant issue/evidence, state which paths are simulated or physically verified, and list remaining limits. Keep unrelated changes separate. Update status documentation when an evidence boundary changes; preserve superseded findings as history.
