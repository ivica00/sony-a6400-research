# Evidence 0049: Original allocation failure cleanup and the existing-name startup path

## Result

With an explicit `--inner-extent` research policy, original captured DMM allocation completes its failure path: **2,565 instructions**, **88 non-stack stores**, return **0xfffffeff (-257 / -0x101)**, output handle **0xffff**. The internally prepared0x0441 is not a successful allocation result. Record65 is made inactive and returned to the free queue. No new physical extent is assigned.

A separate, fresh hash-checked disassembly of original `libObj.so` establishes an actionable startup branch: after the existing-name lookup call, **success (r0=0) branches directly to the common semaphore-release/exit path**, skipping creation/opening of a new unit0x280. E0045's original successful lookup against selected WBI state is therefore relevant to startup; successful duplicate allocation is not necessarily required on that selected path. The client/IPC connection has **not yet been implemented or executed**.

Main process/UI boundary remains E0034. No GUI, fb0 request, successful allocation or camera-equivalent boot is claimed.

## Identity and bounds

Same checked WBI/DMM/kernel inputs, selected root and source-backed mapping as E0048. New consumer input `libObj.so`: SHA-256 **60ffd2b0f31f4bc139a7c13a4f62c25cdeb6a531ad5ef35df48471e6e36e88b1**. The consumer source hash is checked before and after the disassembly; runtime requests are not altered by this research.

The default `--operation alloc` retains the E0048 boundary after2,019 instructions. `--inner-extent` is explicit and requires allocation mode. It additionally permits:

- Inner original function REA0x1a694 / .text+0xa658, verified body1,724 bytes.
- Error-priority helper0x19ed8 / .text+0x9e9c,152 bytes, and rule-count helper0x1a278 / .text+0xa23c,40 bytes.
- Original free-queue return helper0x18514 / .text+0x84d8,112 bytes, and identified extent-table getters.
- Exact original kernel memset/memzero call targets from this function, each checked against a256-byte preserved kernel window before execution. No host fill helper is used.

Additional mutation ranges are derived from original literal pointers: recursion depth word **0x5f1f37ac**, aggregate error halfword **0x5f0d9ae4**, 256-byte visited bitset **0x5f1f37b0..0x5f1f38b0**. Failure cleanup additionally permits the old queue-tail word and exactly its halfword slot. All ranges remain bounded; other writes/control flow/imports and unsupplied memory stop. Original code owns all changes inside disposable source-backed copies. No physical-camera operation occurs.

## Allocation observations

The inner call receives extent identifier **861 (0x35d)**, mask **0xffffff**, current rule **0**, and a constructed stack output pointer. Original code clears its scratch bitset, tracks recursion, searches saved/configured extent tables, selects errors, and restores depth to0. This experiment does not assign a textual interpretation such as memory exhaustion to error-257 without a verified error-name contract.

On cleanup, record65's state and active byte become0; the record retains some initialized data, just as E0047 showed stale pointers/data can remain in inactive records. Original queue cleanup stores65 into the old tail slot, advances tail **22 -> 23**, restores free count **1388 -> 1389** (matching its initial count), and leaves head43 after the consumed entry. The sequence advances to67; queue ordering and sequence are not reset to the original snapshot. Output0xffff is written by original instructions. No host rollback is substituted.

## Startup branch evidence and next direction

Fresh report: `artifacts/analysis/wbi-dmp-lookup-branch/report.json`.

| Original libObj Thumb address | Observation |
| --- | --- |
| `0x6bcb72..0x6bcb78` | Prepare existing `gl_common` name/output arguments |
| `0x6bcb7a` | BL to lookup client `0x71f3dc` |
| `0x6bcb7e` | Compare r0 with0 |
| `0x6bcb80` | BEQ.W to `0x6bcefc` on success |
| `0x6bcb84..` | Failure fall-through builds new open request including unit0x280 |
| `0x6bcefc..0x6bcf1a` | Common semaphore-release/check and function epilogue |

Addresses are ELF-linked coordinates with Thumb state; this is static original-instruction evidence, not an executed client/service continuation. The common-exit block is bounded at its real epilogue; words after0x6bcf1a are literal data, even if the generic disassembler prints them as instructions. E0034's earlier trace observed op7 lookup followed by op1 opening under generic transport behavior. E0045 demonstrated an original lookup returning a real captured handle; these facts motivate tracing the lookup client response and snapshot-service effects next, without changing an opcode or forcing the branch.

## REA and validation

Planner `--pc-offset0xa658` explicitly rejected the unnamed function (no unique ELF function symbol); no graph was invented. Exact REA batch `artifacts/tools/rea/wbi-inner-extent` completed the function query/instruction listing. Selector batch `wbi-inner-extent-selectors` completed both helper listings. The existing earlier containing-function evidence is now used for the actual resolved free-helper entry0x18514/body112, not as evidence for the formerly misaddressed allocation helper.

Reproduce with a new output directory:

```
python -m tools.research.wbi_dmm_handle --operation alloc --inner-extent --report-dir artifacts/execution/NEW_DIRECTORY
```

Final report: `artifacts/execution/wbi-inner-extent-final/report.json`, including signed status and queue/scratch bytes at stop. Earlier completed cleanup/repeat reports are byte-identical (`wbi-inner-extent-cleanup` / `wbi-inner-extent-repeat`). Intermediate stopped runs (`wbi-inner-extent-first`, `wbi-inner-extent-selectors`) remain retained as bounded unsupported-control-flow observations, not successful allocation.

Default-policy regression `wbi-inner-default-regression` still stops after2,019 instructions at the E0048 inner entry. Full suite **345 passing tests**, `artifacts/execution/wbi-inner-extent-suite.txt`. Status image regenerated with unchanged capability counts. No execution backend or default process contract changed.

Next: verify original lookup-client response consumption at0x71f3dc and connect it to the original captured GRM lookup under an explicit package-WBI service policy, including needed mutex/transport effects. Do not force lookup success, skip the semaphore, or substitute a duplicate allocation from already-owned captured memory.
