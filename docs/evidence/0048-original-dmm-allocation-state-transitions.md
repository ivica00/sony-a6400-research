# Evidence 0048: Original DMM allocation mutates a new record

## Result

Original captured `dmm_unit_ctrl_Alloc(0x280, 1, output)` executes **2,019 instructions** and **11 non-stack stores** in a disposable copy of selected WBI state. It consumes free record **65**, initializes that record for unit0x280, and original `MakeHandle(65,1)` returns **0x0441** internally. This is distinct from the already active captured handle **0x0417** at record23.

Execution stops explicitly at runtime **0x5f0d5658**, `.text+0xa658`, the unapproved inner extent-allocation function (REA entry **0x1a694**). No physical extent has been assigned to the new record; its first extent pointer is still zero. The caller's output halfword remains sentinel **0xa5a5**, so **no successful allocation or returned handle is claimed**. Existing captured memory cannot be substituted as the new allocation reply.

Main `im.elf i` execution remains E0034; no fb0 request, original GUI or new service response was supplied.

## Inputs and bounded setup

Same hash-checked DMM/WBI identity and code discovery as E0047, plus preserved kernel SHA-256 **12eeec829407595e28265f7d0db3b88c56f63a9f0fdd725c9c53c66a49643707**. All inputs are checked before and after execution. The selected root remains PA0x104000; active CPU translation state and cold-boot equivalence are not claimed.

`tools.research.wbi_dmm_handle --operation alloc` selects the original allocation entry rather than search. It executes original DMM table access, handle construction, free-queue/sequence helpers, extent wrapper/current-rule query, and the actual captured kernel `memset` target. That captured kernel target's 256-byte window is compared with preserved kernel bytes before it is allowed; there is no host-written memset or allocation reply.

Only these snapshot mutation ranges are permitted:

| Range / field | Scope |
| --- | --- |
| `0x5f16fecc..0x5f16fed0` | free-queue head word |
| `0x5f1709d4..0x5f1709dc` | free-record count and sequence words |
| `0x5f175f30..0x5f176080` | selected record65, 336 bytes |

The selected index comes from the captured queue's current entry, not a chosen free slot. Head/tail and selected-index bounds are checked. Pages are fully read from source-backed WBI before mapping; missing backing is never zero-filled. Stack and a two-byte constructed output are separate. Snapshot page copies may be writable, but every guest store is checked against complete explicit intervals; output padding reads stop. Original package bytes remain unchanged. Unknown imports/control flow/device reads/writes stop, with limits of50,000 instructions/one second.

## Observed state transitions

- Queue head **42 -> 43**, tail remains22.
- Free count **1389 -> 1388**.
- Sequence **66 -> 67**; record65 receives sequence67.
- Record65 type **0xffffffff -> 0x280**; activity/flags/generation fields are initialized by original stores, including generation1 and state1.
- Original handle construction observes inputs index65/generation1 and result **0x0441**. This value has not been returned through the allocation output.
- First extent pointer in record65 is explicitly stored zero before calling the extent wrapper.

Write PCs, previous bytes, values, record-before/at-stop bytes, instruction bytes and page walks are retained in reports. No clock value was supplied or consumed in this bounded prefix; access-info and transport remain outside this execution.

## REA and coordinate checks

Completed plan/batch: `artifacts/analysis/wbi-dmm-alloc-plan` / `artifacts/tools/rea/plan-8d93eef24c54e380-0`, fourteen queries, six reused results. Named graph retains three unresolved direct calls rather than inventing symbols. Exact helpers at provider **0x18588** and **0x18600** correspond to `.text+0x854c` and `.text+0x85c4`, using observed DMM provider text base **0x1003c**. Their original executable body bounds are88 and40 bytes. Retained exact query batch: `wbi-dmm-alloc-exact-helpers`.

An earlier query batch `wbi-dmm-alloc-helpers` used an incorrect0x1002c coordinate assumption and resolved containing functions at0x18514/0x185e4. It is retained but **not used** as the execution bounds for the exact helpers. Completed current-rule plan/batch: `wbi-dmm-current-rule-plan` / `plan-540e861f3a6c304c-0`.

## Reproduction and verification

```
python -m tools.research.wbi_dmm_handle --operation alloc --report-dir artifacts/execution/NEW_DIRECTORY
```

Final reports: `artifacts/execution/wbi-dmm-alloc-handle/report.json`, `wbi-dmm-alloc-repeat/report.json`. Both reach the same boundary after2,019 instructions with the same eleven stores and internal handle observation. Earlier retained runs: `wbi-dmm-alloc-first` stopped on an unmapped write to source-backed record memory; after explicitly mapping the permitted source-backed pages, `wbi-dmm-alloc-mapped` stopped at the not-yet-approved extent wrapper. Neither was treated as allocation success.

Search regression: `wbi-dmm-search-alloc-regression` still returns0x0417 after224 instructions without snapshot mutations. Three constructed tests verify complete mutation containment, adjacent-range crossing rejection, ARM32 wraparound/invalid-size rejection and invalid permission ranges. Full suite: **345 passing tests**, `artifacts/execution/wbi-dmm-alloc-suite.txt`. Status image regenerated and visually checked; capability counts remain unchanged.

Next: analyze exact inner function0x1a694 / .text+0xa658, determine extent selection and required mutations against captured owner/rules, then continue with explicit state bounds. Preserve missing timer/device guards; do not promote the internal0x0441 to successful allocation or overwrite active0x0417's owned extent.
