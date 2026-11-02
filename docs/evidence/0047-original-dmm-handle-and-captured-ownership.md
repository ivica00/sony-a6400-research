# Evidence 0047: Original DMM search connects unit 0x280 to GRM

## Result

Original captured `dmm_unit_ctrl_SearchUnitTypeToHandle(0x280)` and `dmm_unit_ctrl_MakeHandle` execute **224 instructions** and return **0x0417**, matching the identifier in E0044's captured `gl_common` object. No host-generated handle, memory allocation, clock response or IPC reply is supplied.

There are two table records for unit0x280. Original code skips the inactive record at index8 and selects index23. Both retain the same first-extent pointer, but that extent's owner pointer refers to index23. This identifies why raw matching pointers alone cannot establish ownership.

These are observations in an explicitly selected package-WBI environment. A read-only search is not allocation/open success or a demonstrated cold-start reply. Main execution remains E0034; no fb0 or GUI advancement.

## Identity and coordinate discovery

Inputs, checked before and after execution:

| Input | SHA-256 |
| --- | --- |
| nflasha5 | `19a702b030306a32f4287131da314e5c89d66163997f0f9a23b0967981b0001b` |
| dmm.ko | `c5cb62579f4719bed9248b8e3dabe4d95c6fa57481e07908f10b68098e54a74f` |

`tools.research.wbi_dmm_handle` finds the complete 68-byte non-relocated `MakeHandle` function uniquely at physical **0x08add4c8** by scanning decoded source sections. It then enumerates the bounded VMALLOC range **0x5f000000..0x60000000** through E0045's explicitly selected root PA0x104000; exactly one alias maps that page. Subtracting the ELF .text-relative function offset **0x94c8** gives captured module code base **0x5f0cb000**.

All **46,256 non-relocated .text bytes** match preserved DMM code. **1,211 relocation words** are excluded and retained as captured. The exact `.bss+617912` literal in the original search resolves the unit table to VA **0x5f1709e0**; no guessed BSS contents are supplied. Active TTBR/TTBCR are still not recovered; this is selected-root translation, not complete MMU execution.

Dependency plan `artifacts/analysis/wbi-dmm-handle-plan` and completed WSL batch `artifacts/tools/rea/plan-ed12f6742920a34b-0` retain search/construction pseudocode and instructions (two cached pseudocode results and two fresh instruction queries). Original instructions/symbols are used for the bounded functions. An additional completed plan/batch `wbi-dmm-range-plan` / `plan-1c38f2ece96abec3-0` identifies that `GetUnitTop` returns the table and `GetUnitSize` is a configured-size query; neither is claimed executed here.

## Selected records and structural ownership

The original search uses **0x580 records**, stride **336 bytes**, matching unit word +0, state halfword +12 in range1..3, and generation byte +11. The exact record bytes are retained in reports.

| Index | Record VA | State halfword +12 | Generation +11 | First extent +16 |
| --- | --- | --- | --- | --- |
| 8 | `0x5f171460` | 0 | 1 | `0x5f1f454c` |
| 23 | `0x5f172810` | 2 | 1 | `0x5f1f454c` |

Original MakeHandle combines index/generation bits, yielding **0x0417** for index23/generation1. The selected search performs no non-stack writes; source-backed pages are mapped read-only. Execution is limited to the two verified function bodies, 50,000 instructions and a one-second backend timeout. Other code, writes, unsupported descriptors and unsupplied memory stop explicitly.

The first extent's captured words include base **0x20200000** (+4), offset **0xe0000** (+8), size **0x02000000** (+12), extent identifier **0x35d** (+32), owner record **0x5f172810** (+40), and sequence **0x18** (+44), matching that record's sequence word +4. Base plus offset is **0x202e0000**, agreeing with captured GRM's physical base and E0035's configured extent861/32MiB. This field interpretation is structural evidence supported by retained allocator analysis; no original address getter or allocator was executed in this experiment. The inactive record's retained pointer is not treated as a second live allocation.

## Reproduction and checks

```
python -m tools.research.wbi_dmm_handle --report-dir artifacts/execution/NEW_DIRECTORY
```

Output directories must be new and inside artifacts. Initial search: `artifacts/execution/wbi-dmm-handle-first/report.json`; expanded linked records: `wbi-dmm-handle-linked/report.json`; repeat: `wbi-dmm-handle-repeat/report.json`. Both expanded runs return0x0417 after224 instructions with the same record data. Pages and instruction bytes are recorded. Original firmware inputs are unchanged.

Full suite **342 passing tests**, `artifacts/execution/wbi-dmm-handle-suite.txt`. Status image regenerated with unchanged capability counts. This adds research tooling, not a guest-service contract.

Next: bound original `dmm_unit_ctrl_Alloc(0x280, 1, ...)` against captured state with explicit permitted mutation ranges and stops at unknown imports/clock/device behavior. This is distinct from the completed read-only lookup; preserve the existing startup guard until allocation, access-info, transport and ownership effects are established.
