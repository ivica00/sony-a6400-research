# Evidence 0043: Packaged WBI memory recovers the logging input

## Result

The preserved **`nflasha5`** image is a compressed **WBI1 warm-boot memory image**, not an ordinary filesystem image. Its identified contents resolve the earlier missing-logging-data research gate for an explicitly selected **package-WBI** environment:

- **644 sections**, **145,162,240 expanded bytes**, with physical and virtual addresses retained.
- An identified `/setting/ulogio.bin` input buffer: **3,772 bytes (0xebc)**, **128 tags**, SHA-256 **a7b1aa1919c3f3273baa1e4a9ece71c620e0d755b9d9c197e49be74c4a790a44**.
- Logging root at physical **0x03085000**, size **0x00478000**, containing **109** subsystem records.
- DMM subsystem **0x61**, area 0 at physical **0x033f1148**, size **0x10024** (36-byte ring prefix plus 64 KiB).
- All five expected original DMM initializer markers match inside that area.
- Original `ulogio_get_logaddr` and `ulogio_lbm_lookup_table_find` execute **71 original ARM instructions**, return normally, and populate exactly **0x033f1148 / 0x10024** in the DMM request.

This is identified **packaged warm-boot memory**, not current camera state, a complete setting-partition image, or a successfully booted kernel. No snapshot data has been injected into the main process and no timer/device response is invented. The latest main `im.elf i` boundary remains E0034; no new GUI or fb0 request is claimed.

## Input and format

| Preserved input | SHA-256 |
| --- | --- |
| `0700_part_image/dev/nflasha5` | `19a702b030306a32f4287131da314e5c89d66163997f0f9a23b0967981b0001b` |
| `vmlinux.bin` | `12eeec829407595e28265f7d0db3b88c56f63a9f0fdd725c9c53c66a49643707` |
| `osal_ulogio.ko` | `9645f7bfc8148a5fcf52829dd3161fcbf95c58b246691e5d24ec5e302237c074` |

Inputs are checked against the preserved baseline before analysis. The existing preserved sources [WBI reader](../../fwtool.py/fwtool/sony/wbi.py) and [LZ77 decoder](../../fwtool.py/fwtool/lz77/__init__.py) already describe this representation. They were read/reused without modifying the upstream checkout. The new bounded independent decoder lives in `tools/research/wbi_memory.py`.

Header observations: magic **WBI1**, format version **0x20060224**, flags **9**, section count **0x284**, sector size **0x200**, compressed payload size **0x1faa800**, expanded size **0x08a70000**, resume-vector field **0x00124b9c**. Format version is not claimed as the firmware build date. Checksum fields are retained, including `0x0f0f0f0f`; their kernel validation semantics are not established. All 644 metadata fields match the observed XOR relation, recorded separately from SHA-256 identity and decoding verification.

Section tables, individual ranges, output totals, source lengths, dictionary references and block output are bounded. Individual expanded sections are capped at 4 MiB, aggregate expansion at 256 MiB. Truncation, invalid LZ77 references, empty non-progressing blocks and oversized declarations stop. Sparse physical-memory reads never fill gaps; overlapping physical sections are rejected.

## Independent decoding verification

`tools.research.wbi_verify` first validates each section with the bounded decoder, then compares it with the preserved fwtool LZ77 implementation. **All 644 sections and all 35,440 blocks agree**, including consumed compressed byte counts. Reference implementation SHA-256: **8c4bd864655ae9b324068ec1a279f5ba068be6dacb1c7a3f3fc49744f96a6bdc**; unchanged-source verification is performed.

Four selected kernel windows recovered through physical ranges match the corresponding preserved kernel bytes: entry prefix at `0x60108000`, freerun setup at `0x6011fdec`, timer-pointer store slice at `0x6012534c`, and timer read at `0x601256ec`. This supports these specific coordinate/code comparisons, not complete running-kernel/module identity or successful resume.

Reports: `artifacts/analysis/wbi-memory-first/manifest.json` (separate section files) and `artifacts/execution/wbi-decoder-verification.json`.

## Recovered input provenance

The captured logging state tuple at physical **0x089294c4** contains:

| Field, relative to selected state base | Captured value |
| --- | --- |
| +0 input-buffer cached pointer | `0x6898b000` |
| +4 input length | `0x00000ebc` |
| +8 filename cached pointer | `0x68925f48` |
| +28 logging-root cached pointer | `0x63085000` |

The filename pointer resolves to the exact null-terminated **`/setting/ulogio.bin`**. The input-buffer bytes at physical **0x0898b000** parse into 128 complete aligned tags, including all five mandatory tag types identified in E0037. LOGB gives the same root physical base/size as the captured ULOG root. Its subsystem declarations and the captured runtime subsystem table agree on DMM's identity and layout. This is structural compatibility with the preserved module's identified state layout, not an assertion that every loaded module byte has been verified.

`tools.research.wbi_logging_trace` decodes required source sections directly from the hash-checked original WBI. It does not trust mutable extracted section files or a generated manifest as source bytes. It validates the tuple, filename, complete tag ranges, root pointers/ranges, subsystem counts, area pointers and sizes. The recovered file is a **new artifact**, never written over a preserved input or forwarded into the guest namespace automatically.

Recovered DMM subsystem header: physical **0x033f111c**, ID **0x61**, span **0x140d8**, three areas:

| Area | Physical base | Size |
| --- | --- | --- |
| 0 | `0x033f1148` | `0x10024` |
| 1 | `0x0340116c` | `0x4024` |
| 2 | `0x03405190` | `0x64` |

Area 0's initializer markers match original code at offsets **0x24 (`0x51434f4c`)**, **0x1588 (`0x51564452`)**, **0x1aac (`0x4c545845`)**, **0xfab0 (`0x56415350`)**, **0xfaf8 (`0x4c444e45`)**. The first 36 bytes belong to the ring prefix; DMM's first marker follows it. This ties the recovered area to the original DMM producer layout rather than only to a filename/string.

The original partition-2 image is still absent. E0036–E0042's statements that no logging file/raw LOGB record was found remain valid for their stated raw scan; their broader unknown-input gate is now **superseded for this identified packaged-WBI representation**. Compressed representations had explicitly remained open.

## Original consumer execution

`tools.research.wbi_log_consumer` maps original source module code/read-only data and applies supported local ABS32/ARM CALL relocations. It selects the captured module BSS page, lookup-map pages and logging root from the verified WBI, using the established cached/physical conversion. The selected module functions are bounded to their original bodies; unresolved imports, unsupported literals, other control flow, unverified reads and writes outside the output packet/constructed stack stop. Snapshot backing is read-only. Code/data padding does not silently supply memory.

Request: command **0x0b**, subsystem **0x61**, area **0**, with output sentinels. Original instructions fill size at +8 and physical address at +12, returning **0x10024** and **0x033f1148**. No host-written allocation decision, guessed address, kernel lock/registration success or timer timestamp is substituted. This is a direct isolated consumer experiment, not execution of the transport or a running logging driver.

Repeated `wbi-log-consumer-first.json` / `wbi-log-consumer.json` are identical, SHA-256 **ff5f8e7e11876f359ef19b9d6d346e6efdcf3207e05f635f5f3bddf1d10e2153**. Repeated recovery manifests in `wbi-logging-recovered` / `wbi-logging-repeat` are identical, SHA-256 **6db272b494a59f1318fe52876c1bb316e9a96159dcfc85bf9ea471a6b2d6df51**. The recovered config file itself has the independent hash stated above.

## Reproduction and checks

```powershell
.\venv\Scripts\python.exe -m tools.research.wbi_memory --report-dir artifacts/analysis/NEW_WBI_EXTRACTION
.\venv\Scripts\python.exe -m tools.research.wbi_verify
.\venv\Scripts\python.exe -m tools.research.wbi_logging_trace --report-dir artifacts/analysis/NEW_WBI_LOGGING
.\venv\Scripts\python.exe -m tools.research.wbi_log_consumer
.\venv\Scripts\python.exe -m unittest discover -s tests -v
```

Extraction/recovery directories must be new. All original firmware and upstream sources remain unchanged. No USB, service mode, updater or device write is involved.

All **339 tests pass** (`artifacts/execution/wbi-recovery-suite.txt`), including five constructed checks covering raw/overlap LZ77 decoding, truncation/output/reference bounds, aggregate identity, sparse memory gaps/overlaps, and logging tag/pointer ranges. Original-module behavior is separately supported by the 71-instruction real-firmware experiment.

## Next work

Use this identified data only through an explicit package-WBI policy with provenance and mutable-state boundaries. Verify remaining module state/ownership before allocator replies; do not combine captured state with an invented reset silently. A candidate `gl_common` record at physical **0x08a96220** contains the name and fields consistent with a 32 MiB pool at **0x202e0000**; this is a next research target, **not a validated allocation reply**. It can be reproduced with `PackageMemory.read(0x08a96220, 48)` under the same input identity.

No timer MMIO page or authoritative current counter/control value has been identified in this image; original scheduling/resume/device effects remain separate requirements. Main `im.elf i` is not rerun with fabricated replies: its last demonstrated boundary is still E0034, **42,465,243 instructions**, allocator assertion/SIGABRT request, no stream mmap or fb0 request. Status visualization is updated with unchanged capability counts.
