# Evidence 0045: Captured page tables and original GRM lookup

## Result

Original captured `ma_findbyname_impl`, `ma_list_findbyname` and kernel string-comparison instructions return successfully for `gl_common`: **285 instructions**, status **0**, physical base **0x202e0000**, size **0x02000000**, object pointer **0x68a96220**. The original halfword store changes its captured retain count from **1 to 2** in disposable memory. No allocator decision or comparison helper is substituted on the host.

A deliberately absent name returns normally after **211 instructions**, with status **-9**, base/size/handle zero, and **no retain-count write**. These are isolated selected-WBI lookups, not an IPC service, cold-start allocation/open, booted kernel, current-camera observation or GUI milestone. Main execution remains E0034.

## Inputs and translation evidence

Inputs are checked against `artifacts/inventory/baseline.json` before use and again after execution:

| Input | SHA-256 |
| --- | --- |
| nflasha5 | `19a702b030306a32f4287131da314e5c89d66163997f0f9a23b0967981b0001b` |
| grm_ma.ko | `4bd42001061c8c6f163ede217b0cadf117f2e9f4e23723c0658ac5c3d29f163f` |
| vmlinux.bin | `12eeec829407595e28265f7d0db3b88c56f63a9f0fdd725c9c53c66a49643707` |

The original kernel word at linked **0x60108054** is `0xe3a04941`, `mov r4, #0x104000`; following instructions add r8 and initialize a 16 KiB table. This motivates selecting physical root **0x00104000** for research, but does not recover active TTBR/TTBCR or establish r8/current boot state. The selected saved table translates E0044's head independently of the reciprocal-pointer inference:

| Step | Address | Descriptor/result |
| --- | --- | --- |
| Virtual head | `0x5f3fc348` | |
| L1 lookup | physical `0x001057cc` | `0x09615c11` |
| L2 lookup | physical `0x09615ff0` | `0x096ce45e` |
| Translated head | physical `0x096ce348` | agrees with E0044 candidate |

`tools.research.wbi_pagewalk` supports selected-root short-descriptor section, replicated 32-bit supersection, and coarse/small-page translation. Extended physical addresses, missing bytes, invalid descriptors and large L2 pages stop. It checks all 16 supersection descriptors agree. It performs address translation only: permissions, domains, caches, ASIDs and active CPU translation controls are not simulated. All backing reads are bounded sparse reads directly from the hash-checked original WBI; gaps are never zero-filled.

Primary format references: [Arm ARMv7-A/R architecture manual, short-descriptor tables](https://documentation-service.arm.com/static/5f8daeb7f86e16515cdb8c4e), [Linux ARM supersection construction](https://github.com/torvalds/linux/blob/master/arch/arm/mm/mmu.c). The latter explicitly constructs replicated entries and places extended physical bits in the descriptor. These references inform decoding; they do not establish this camera's active MMU state.

## Code identity and execution guards

Selected captured module code begins at **0x5f3f8000**. Across its full **15,380-byte .text**, all **14,548 non-relocated bytes** match the preserved `grm_ma.ko`; **208 four-byte relocation sites** are excluded from this comparison and retained from captured memory. This is stronger code identity evidence than only the E0044 structure. It is not complete module identity validation.

The actual captured BL relocation within `ma_list_findbyname` resolves the comparison target to **0x60260928**. Its 256-byte captured window matches preserved kernel bytes exactly. Execution is restricted to the two original module function bodies and this explicit kernel window; unknown branches stop. The trace contains the executed bytes. No Ghidra synthetic coordinates are used as runtime addresses.

`tools.research.wbi_grm_consumer` supplies constructed stack/name/output ranges. Snapshot pages are copied only after successful selected-root translation and a complete source-backed read. Writes are allowed only to the stack, four aligned output words, and the `gl_common` retain halfword at **0x68a96222**. Other writes stop. Constructed padding reads stop. Original snapshot/module/package files are unchanged. Limits: 10,000 instructions and one second CPU backend timeout; hitting either limit is not success.

## Reproduction and validation

```
python -m tools.research.wbi_grm_consumer --report-dir artifacts/execution/NEW_DIRECTORY
python -m tools.research.wbi_grm_consumer --name absent_control --report-dir artifacts/execution/NEW_CONTROL_DIRECTORY
```

Directories must be new and inside artifacts. Successful reports: `artifacts/execution/wbi-grm-consumer-second`, `wbi-grm-consumer-guarded`, `wbi-grm-consumer-repeat`; negative control: `wbi-grm-consumer-absent`. Guarded/repeat report bytes match, SHA-256 **468c11dd82757b2bda4171a65570b7dbd471e5d7e93a49e3ba9222a5d78d2da0** (before adding the explicit name report field). Initial attempt `wbi-grm-consumer-first` stopped during pre-execution validation because the walker did not yet support the observed kernel supersection; it did not execute or supply a false translation.

Three constructed-fixture tests cover small-page cross-boundary reads, sparse gaps, sections, supersection replication, unsupported descriptors, extended physical addresses and bounds. Full suite **342 passing tests**, `artifacts/execution/wbi-grm-consumer-suite.txt`. Status image regenerated and visually checked; capability counts unchanged.

Next: determine original `ma_open_impl` behavior for the current startup request (unit 0x280, flags 0) when this captured named object already exists. Verify lifecycle, locks and relevant side effects before considering a separate package-WBI service policy. Existing captured pool/mspace state does not authorize a fabricated allocation response or bypass missing timer/hardware state.
