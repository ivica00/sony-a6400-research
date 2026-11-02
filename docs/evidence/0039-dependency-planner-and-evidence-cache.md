# Evidence 0039: Bounded dependency planner and reusable REA evidence

## Delivered

`tools.research.dependency_plan` accepts named functions or one .text-relative stop offset in an inventoried ARM ET_REL module. It builds a bounded call/dependency graph from original relocations and exact direct-call symbol entries, retains literal/data/string references and unresolved calls, identifies candidate function definitions in other hash-checked modules, and prepares shared-session REA commands. It does not execute firmware or invent service behavior.

Static results are cached per input/function/analyzer/helper/library identity with payload integrity checks. `tools.research.rea_evidence_cache` separately indexes completed retained REA batches with subject, operation, procedure, provider/version/profile and file-integrity checks. `rea_wsl_batch --reuse-evidence` materializes retained results with explicit provenance and opens a provider session only for missing queries. Existing non-cache runs remain available. The native WSL launcher remains stdlib-only.

See [the usage and limitations](../DEPENDENCY_WORKFLOW.md).

## Original DMM demonstration

Target `dmm.ko`, SHA-256 **c5cb62579f4719bed9248b8e3dabe4d95c6fa57481e07908f10b68098e54a74f**, seed `.text+0x50e0`, resolves uniquely to `dmm_timer_GetSyscnt`. Depth-one planning discovers it and `dmm_log_Put`, recording their calls, data references and provider candidates.

- Initial mixed batch: `artifacts/tools/rea/plan-8d8198a1836d5553-0`. One retained query reused; three missing queries executed through the established native WSL REA/Ghidra environment. Completed manifest and unchanged target hash retained.
- Final static cold run: `artifacts/analysis/dmm-plan-verified-cold`, two misses, 4/4 REA results available.
- Final static warm run: `artifacts/analysis/dmm-plan-verified-warm`, **two hits, zero misses**, 4/4 REA results available.
- All-cache batch: `artifacts/tools/rea/plan-a7894980dd6e3768-0`. Four reused queries, completed status, source hash unchanged, **no provider initialization/open artifacts**, demonstrating that no REA/Ghidra process was launched.
- Cross-module run: `artifacts/analysis/dmm-dependency-cross-module`. Eight nodes reach `osal_uipc.ko`, including `osal_snd_sync_direct`, locks and message-allocation/send functions. Its explicit `truncated: true` records the eight-function cap. Candidate definitions do not establish export/load/IPC routing contracts.

No claim of general speedup factor is made: input hashing, indexing and WSL startup still incur overhead. Avoiding repeated imports and unchanged queries is demonstrated directly. Earlier development reports remain separate; an initial inventory-size guard was adjusted to a bounded 64 MiB for the existing large ELF inventory before successful planning.

## Validation

All **326 tests pass**, including eight new constructed checks for original call/data separation, static cache reuse and corruption rejection, changed input rejection, dependency limits/unresolved providers, retained provenance, exclusion of failed/wrong-subject/wrong-query evidence, incompatible-profile isolation and escaping/changed evidence references. Full suite: `artifacts/execution/dependency-planner-suite.txt`.

The generated DMM batch was inspected and executed through WSL; mixed and all-cache paths both completed. Documentation and project workflow instructions are updated. The status image is regenerated with unchanged capability counts.

## Fidelity scope

Supported analysis initially excludes Thumb and ET_DYN/ET_EXEC/raw-kernel targets. Runtime callback/IPC routing and complete data-pointer graphs remain unresolved. Static source/provider labels are evidence candidates, never successful guest responses. The application execution boundary remains E0034's **42,465,243 instructions**, allocator assertion/SIGABRT request and no original GUI. E0038's timer semantics and missing setting-partition/logging input remain open.
