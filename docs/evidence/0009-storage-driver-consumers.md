# E0009 — Storage table consumers and isolated original instruction execution

Date: 2026-10-18. Scope: identified original eMMC module, static instruction evidence and an isolated instruction window. No kernel boot, storage hardware or camera operation.

## Result

The original storage module's consumers support the major/first-minor/count interpretation proposed in E0008. An isolated **nine-instruction original ARM window** reproduces the field copies with no supplied kernel responses. Static instructions also establish the decompressed-device partition numbering formula and a conditional registration path.

This does not select a runtime `st_dev`. Successful device registration, successful mount selection, boot mode and the writable `/etc` contents remain unobserved. Existing process policies and both the 3,091-instruction mount-aware and 6,493-instruction snapshot boundaries remain unchanged.

## Source identity and reproducibility

The module is `nflasha3_unpacked/initrd.img_unpacked/kmod/emmc.ko`, SHA-256 `d60683420d1ef7af57571d4281def19254c88e47c9047da9d5098e49de848671`. Device-table input remains `devno.ko`, SHA-256 `3b36fcea8687d7f29112a7008ce61fde9229679ebc24c65ec2d21cf3af632f56`. Both are confined to firmware paths and checked against the existing baseline before analysis or execution.

`tools/research/storage_trace.py` records six original function ranges, their source file offsets, bytes, section-relative offsets, relocations and PC-relative literals in `artifacts/inventory/storage-trace.json`. Undefined kernel symbols remain unresolved annotations. Relocations are not applied. PC-referenced words and ABS32 relocation data are labeled as data rather than instruction candidates. Other inline data can remain: linear disassembly is not an executed control-flow graph.

Two fresh runs produce identical complete reports, including the isolated execution observations.

## Parameter consumers

All offsets below are **within their named ELF section**, not runtime virtual addresses.

In `.init.text`, `init_blk_params.clone.7` takes a table record in its first argument and a block-parameter output in its second. At `0x39c`–`0x3bc` it performs these copies:

| Original source halfword offset | Destination word offset | Observed values: nflasha / dnflasha |
| --- | --- | --- |
| `+6` | `+0x28` | 252 / 252 |
| `+8` | `+0x2c` | 0 / 128 |
| `+10` | `+0x30` | 32 / 32 |

In `init_emmc_and_blkdev`, `.init.text:0xe64` loads the count and `0xe68` calls relocated `alloc_disk`. The word from block parameters `+0x28` is stored into the allocated disk at offset 0 (`0xea4`–`0xeac`); `+0x2c` is stored at disk offset 4 (`0xeb0`–`0xebc`). The disk is passed to relocated `add_disk` at `0xf34`.

The leading Linux `gendisk` fields are major, first minor and minor count; [the kernel header](https://android.googlesource.com/kernel/common/+/18dc6fbbd9d7/include/linux/genhd.h) provides the structural interpretation. [Linux block registration source](https://android.googlesource.com/kernel/common/+/7d0291256ca99cbb6124f63228003329e7a64b21/block/genhd.c) also identifies the requested major argument to `register_blkdev`. These upstream references interpret the observed calls/layout; they do not prove that Sony's kernel is unchanged.

The table's first block record is loaded through an ABS32 relocation to `udif_devnodes` in `.init.text:0x610`. Its `+6` halfword is copied to driver parameters at `0x624`–`0x628`, consistent with the value later requested by `register_blkdev` at `.text:0xcec0`. The first kind halfword remains outside this isolated verification; E0008's complete table parser continues to label its field semantics as inferred.

## Isolated execution experiment

The tool executes the preserved `.init.text` bytes `[0x39c, 0x3c0)` separately for the original `nflasha` and `dnflasha` records. It supplies explicit R4 output/R5 input addresses, a read-only record mapping, an RX code mapping and writable output initialized to `0xa5`. It requires exactly nine instructions and the exact end PC; loops, faults and timeouts are not success.

Observed output words are shown above. No syscall, MMIO, invalid-memory or external-function response is supplied. The report records original record bytes, all output bytes, instruction count and experimental setup.

This is execution of a short original field-copy path with constructed initial state. The supplied registers do not establish the original caller's runtime state. Cortex-A9 is still a provisional choice; ARM user mode, fixed mappings and a fresh engine are experimental inputs. The window does not initialize or emulate the storage device.

## Decompressed partition numbering and registration

In `.text`, `emmc_blk_plat_probe_post` loads a relocation to `udif_devnodes + 36` at `0x7fb8`, selecting E0008's `dnflasha` record, and copies its three words to a temporary record. At `0x7fc8`–`0x7fd8`, it adds `1 + sl` to the record's first-minor halfword. It sets the minor count to one at `0x7fdc`–`0x7fe0` and calls `init_blk_params.clone.7` at `0x7fe4`.

At `0x7f94`, `sb = sl + 1`; the `%s%d` format and `sb` are supplied to `snprintf` at `0x7ff0`–`0x7ffc`. This supports a decompressed name suffix `p = index + 1` and minor `128 + p`. If partition 15 registers through this path, the resulting device candidate is **major 252, minor 143**; partition 7 gives **252, 135**. These are conditional driver-derived candidates, not selected mounted-device values or supplied stat responses.

The loop checks partition flags and sector alignment at `0x7f00`–`0x7f20`. It then calls `uz_emmc_lzp_part_size` at `0x80ec`. A nonnegative result branches to the registration setup at `0x812c`; a result of `-22` branches through the diagnostic at `0x8160`–`0x8168`, reporting an invalid compressed image and skipping the `dnflasha` registration. Other failures take separate error paths. The successful setup calls relocated `emmc_blk_decomp_request_dev` at `0x8150`, whose failure also prevents retaining that device.

These checks explain why the existence of the decompressed name in a static table does not establish availability on the booted system. The updater's extracted ext2 bytes do not prove the physical partition's compressed header or that these checks pass.

## Checks and next work

```powershell
.\venv\Scripts\python.exe -m tools.research.storage_trace
.\venv\Scripts\python.exe -m unittest discover -s tests
```

Constructed ELF tests cover undefined call relocations, section-backed string relocations, literal/data separation, invalid ranges, wrong ELF types, missing symbols, out-of-section and duplicate relocations. ARM fixtures exercise field copies and demonstrate that a looping window cannot be reported as completion. The complete suite has 127 passing tests.

Next: follow `uz_emmc_lzp_part_size` into its compressed-header validation and identify the necessary on-device input state; preserve this report as evidence of conditional numbering. Mount outcomes and `/etc` state still require identified runtime-state evidence. Do not use the conditional candidate numbers to bypass metadata guards or the unsupplied-overlay stop.
