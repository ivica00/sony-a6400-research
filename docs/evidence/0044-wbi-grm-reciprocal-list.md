# Evidence 0044: Captured GRM allocator list

## Result and limits

The identified package WBI contains a structurally consistent circular list of **six** allocator objects, including exactly one `gl_common` record. This strengthens E0043's candidate object identification. It does **not** establish allocation ownership, a usable cold-start response, a proven VMALLOC mapping, or original lookup execution. No execution backend changed; the main process remains at E0034 and no fb0 request or GUI is demonstrated.

Source: preserved `0700_part_image/dev/nflasha5`, SHA-256 `19a702b030306a32f4287131da314e5c89d66163997f0f9a23b0967981b0001b`. The scanner decodes directly from the checked original, validates sparse physical reads, and checks source identity again after reading. Extracted section files are not trusted inputs.

## Method

Dependency plan `artifacts/analysis/wbi-grm-ma-lookup` targets `ma_findbyname_impl` and `ma_list_findbyname` in `grm_ma.ko` (SHA-256 `4bd42001061c8c6f163ede217b0cadf117f2e9f4e23723c0658ac5c3d29f163f`). The generated native WSL batch completed at `artifacts/tools/rea/plan-181945481a9f9d3f-0`: two retained pseudocode queries reused, two instruction queries obtained through REA/Ghidra. Cached evidence is not fresh analysis.

Original instructions establish list links at object +20/+24, name comparison of up to 16 bytes at +28, and an increment of the 16-bit count at +2 on a match. `ma_findbyname_impl` then returns status, physical base, size and object pointer. These are static observations, not an executed request. ELF symbol `head` is `.data+0x80`, eight bytes; its two self-link ABS32 relocations are present. Ghidra's function coordinates are synthetic, not camera addresses.

The candidate `gl_common` object is at physical `0x08a96220`, with cached link pointer `0x68a96234`. A complete aligned reference scan finds two references to that link: physical `0x00b7f374` and `0x096ce34c`. The latter supports candidate head backing at physical `0x096ce348`, corresponding structurally to terminal pointer `0x5f3fc348`. **No declared WBI virtual section covers that VMALLOC pointer.** This correspondence is an inference from reciprocal structure, not a page-table-derived translation.

Starting from the candidate head's forward link, the scanner uses only the established cached-address conversion for individual nodes. It checks each reverse link, bounds traversal to 1,024 nodes, rejects premature cycles, and requires final head/tail agreement and exactly one candidate occurrence. All six nodes pass:

| Name | Object physical | Pool physical | Size |
| --- | --- | --- | --- |
| empty | `0x00b7f2a0` | `0x23b16000` | `0x96000` |
| mpMemoryHeap2 | `0x08abd560` | `0x226e0000` | `0x1a0000` |
| mpTextHeap | `0x08abd5a0` | `0x22880000` | `0x200000` |
| mpMemoryHeap | `0x00b7f2e0` | `0x222e0000` | `0x400000` |
| empty | `0x00b7f360` | `0x23a80000` | `0x96000` |
| gl_common | `0x08a96220` | `0x202e0000` | `0x2000000` |

`gl_common` has count +2 = 1, word +4 = `0x44`, mspace pointer +16 = `0x802e0008`, and flag byte +44 = 1. Bytes after string terminators and after the flag byte are not assumed initialized. Its state must not be substituted for the cold-start open request (flags 0 / unit 0x280) without establishing the applicable lifecycle and effects.

## Reproduction and validation

`python -m tools.research.wbi_grm_scan --report-dir artifacts/analysis/NEW_DIRECTORY` writes a separate report and refuses an existing directory. Initial reference-only scan: `artifacts/analysis/wbi-grm-references/report.json`. Completed reciprocal scan: `artifacts/analysis/wbi-grm-reciprocal-list/report.json`. A subsequent invocation refused to overwrite the initial directory; it did not change that report.

Full suite: **339 tests passed**, `artifacts/execution/wbi-grm-suite.txt`. `status_a6400.png` regenerated with unchanged capability counts and an explicit no-UI title.

Next: establish captured module/page-table mapping and bound original lookup execution with its count mutation. Then investigate compatibility between captured pool ownership and the current startup request before any selected package-WBI service policy is implemented.
