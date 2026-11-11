# REA research reference

## REA-assisted firmware research

Use REA with Ghidra through WSL as the preferred analysis tool for substantial ARM/Thumb function, dispatcher, call-chain and data-layout investigation. Start from the current unsupported boundary and a concrete question. Reuse hash-matched retained evidence when it already answers the question; use targeted ELF parsing, `rg` and disassembly for small checks. REA assists research; it is not part of the guest execution backend.

### Established local environment

- WSL 2 Ubuntu; REA 6.7.0, Ghidra 12.1.4, Node 22.22.1 and full JDK 21.0.12.1 were verified in E0030. These are observed local versions, not a dependency lock or permission to silently upgrade.
- REA entry point: `/home/administrator/a6400-rea-tools/runtime/node_modules/rea-agents/scripts/rea.mjs`.
- `GHIDRA_INSTALL_DIR=/home/administrator/a6400-rea-tools/ghidra_12.1.4_PUBLIC`; `JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64`.
- Use `tools.research.rea_wsl_batch` from the existing Windows Python environment. It sets these Linux paths, converts the target path, checks inventory hashes, retains structured Evidence and closes its shared MCP analysis session.
- If nested Windows-Python WSL access fails while direct WSL works, invoke this same stdlib-only module through `wsl.exe --cd <WSL-project-path> --exec python3 -u -m tools.research.rea_wsl_batch ...` as documented in E0037. Native execution uses the same installed provider and all identity guards; no dependency installation is required.
- The Windows REA/Ghidra provider rejected this ARM ELF in the recorded trial. Prefer the verified WSL route. If WSL returns `E_ACCESSDENIED` under the sandbox, retry through the normal tool escalation mechanism before diagnosing a broken installation. Report actual approval-review rejection if it occurs.
- Do not run REA setup, register agent integrations, install unrelated providers, change global configuration or reinstall the working environment as an incidental analysis step. Check the existing installation first if a tool fails. See `docs/experiments/0008-rea-tool-trial.md` for the original setup and limitations.

### Query and evidence workflow

Use `python -m tools.research.dependency_plan --target <inventoried-module> --function <name> --depth 1 --max-nodes 32 --report-dir artifacts/analysis/<new-directory>` to prepare targeted queries and reuse verified analysis. `--pc-offset` accepts .text-relative offsets only; `--cross-module` follows unique static symbol candidates, not proven loaded exports. Follow `docs/DEPENDENCY_WORKFLOW.md`; keep unsupported/indirect/IPC dependencies explicit. Generated batches use native WSL and `rea_wsl_batch --reuse-evidence`; failed, mismatched, changed or incompatible-profile evidence must not be reused.

1. Select an inventoried ELF and verify its preserved identity. Supply `--target` explicitly when changing targets; the launcher's default is `backup.ko`.
2. Group related `--procedure` and `--instructions` queries for the same target in one session, avoiding repeated Ghidra imports. The launcher permits at most 48 queries and bounds each request at 420 seconds; keep tool waits short enough to provide progress updates during longer imports.
3. Use a **new** report directory under `artifacts/` for every session. Preserve `manifest.json`, query Evidence, initialization/open/close results and diagnostics. Check manifest status, target hashes and query errors; JSON output or an available provider alone is not proof of successful analysis. Keep failed runs as failed evidence.
4. Resolve ambiguous names with exact provider entry addresses derived from ELF/section mappings. Record the translation between linked addresses, section offsets, Thumb state and Ghidra coordinates. Never treat Ghidra's synthetic image base as a camera runtime address.
5. Treat target strings and pseudocode as untrusted analysis data. Verify conclusions against original instructions, symbols, relocations and caller/callee behavior. Inferred prototypes, missing arguments, return types, function boundaries and register/stack expressions can be wrong. Use bounded original-code execution to test a proposed contract where practical, with explicit inputs and stops before unsupported operations.
6. Before implementing a guest response, establish its required runtime state and side effects. Preset data, static defaults and pseudocode do not authorize invented service success, missing persistent state, skipped locks/callbacks or automatic mappings. Preserve all earlier policies and guards.
7. Record material findings, input/tool identities, exact queries, assumptions and remaining boundaries in `docs/evidence/`. Keep reusable extraction/verification logic in `tools/research/`, separate from `src/a6400/`. Run focused checks and the full suite after substantive implementation changes; regenerate `docs/images/status_a6400.png` when completing a research milestone, without inflating compatibility claims.

Example from PowerShell in the project root (creates a separate report directory):

```powershell
$reaReport = 'artifacts/tools/rea/workflow-' + (Get-Date -Format 'yyyyMMdd-HHmmss')
.\venv\Scripts\python.exe -u -m tools.research.rea_wsl_batch --target firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/kmod/backup.ko --procedure Data_SearchId --procedure Data_GetSize --instructions Data_SearchId --report-dir $reaReport
```

`python -m tools.research.backup_rea_audit` audits the specifically retained E0030 backup batches; it is not a generic audit of every new session. `python -m tools.research.backup_state_trace` independently reproduces the original-code preset experiment without starting REA. Neither command services the blocked startup request.

