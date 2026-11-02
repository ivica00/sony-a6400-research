# Targeted dependency analysis and cached REA

Use this workflow before substantial new module call-chain analysis. It is static research; it does not execute firmware or supply a guest response.

## Start from a known boundary

From the project root in PowerShell, using a new report directory:

```powershell
.\venv\Scripts\python.exe -m tools.research.dependency_plan --target firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/kmod/dmm.ko --pc-offset 0x50e0 --depth 1 --max-nodes 12 --report-dir artifacts/analysis/NEW_DMM_PLAN
```

`--pc-offset` is a **.text-relative module offset**, not a process/kernel virtual address. Alternatively use `--function dmm_timer_GetSyscnt`; repeat `--function` for multiple roots. Do not pass a raw runtime PC without first identifying the mapped module and translating it.

The tool writes:

- `summary.md`: function counts, bounds and cache reuse.
- `plan.json`: original instruction evidence, direct-call edges, data literals/strings, unresolved calls, candidate provider modules, input hashes and retained REA references.
- `rea-commands.ps1`: targeted, safely quoted WSL batches, at most 48 queries per batch, using the existing provider. Review the target/function list, then run this generated script to materialize cached evidence and analyze missing queries.

Default traversal stays in the selected module. `--cross-module` follows a uniquely named candidate function definition across module files; it does **not** prove exports, module load state or successful linking. Ambiguous providers remain candidates. Depth is limited to 0–5; the graph allows 1–128 functions and reports truncation explicitly. Each decoded function is capped at 16 KiB.

Only ELF32 little-endian **ARM ET_REL** module functions are supported initially. Thumb, raw kernels, application ET_DYN/ET_EXEC and indirect/IPC dispatch remain explicit research boundaries. Data references are static literal/relocation observations, not validated runtime contents or complete pointer graphs.

## Two cache layers

Static function analysis lives under `artifacts/cache/dependency-planner/`. Its key includes input SHA-256, function identity, analyzer/helper source hashes and Capstone/pyelftools versions. Every run verifies original input bytes before accepting cached analysis. Cached payload checksums detect corruption; rejected entries are recomputed and counted. Analyzer changes invalidate their own namespace automatically. Do not edit firmware hashes to obtain a hit.

REA evidence is reused from successful retained batches under `artifacts/tools/rea/`. Reuse requires completed status, verified unchanged source, exact subject digest, operation, procedure, Ghidra 12.1.4 identity and one unambiguous analysis profile. Changed evidence files, failed batches, subject/query mismatches, incompatible profiles and escaping references are rejected. Reused results keep their original evidence/profile and receive a `reused_evidence` provenance record in the new manifest. A cache hit is not a new decompilation.

The generated commands use the existing stdlib-only launcher directly within WSL with `--reuse-evidence`. That optional flag can also be supplied to manual `rea_wsl_batch` calls. Missing results share one MCP session per batch. If every query is cached, the launcher starts **no REA/Ghidra process**. All runs still create a new report directory and recheck the target hash afterward.

## Verified example

`artifacts/analysis/dmm-plan-verified-warm/summary.md` records **2 static cache hits, zero misses, and 4/4 retained REA queries** for DMM's timer boundary. The corresponding earlier mixed batch reused one query and executed three missing queries. `artifacts/tools/rea/plan-a7894980dd6e3768-0/manifest.json` demonstrates a completed four-query all-cache run without `initialize.json` or `open.json`.

`artifacts/analysis/dmm-dependency-cross-module/plan.json` shows a bounded eight-function graph reaching `osal_uipc.ko`; `truncated: true` records the cap. Do not interpret a graph cap or unresolved edge as a missing firmware function.

This workflow reduces repeated disassembly/decompilation. It cannot recover unsupplied `/setting/ulogio.bin`, establish unknown register values or turn static candidates into authentic runtime state. Continue using original-instruction experiments and the evidence rules before implementing responses.
