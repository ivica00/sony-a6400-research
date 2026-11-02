# Evidence 0035: Original DMM configuration and boot reservations

## Result

The original ARM routines in `dmm.ko` parse the preserved 77,108-byte package `setting/DmmConfig.bin` in a bounded, isolated execution experiment. They construct one root header, 367 extent headers and 592 unit mappings. Graphics unit **0x280** references extent **0x35d**, whose configured size is **32 MiB**, under parent **0x21**. The parent configuration begins at **0x20200000** and spans **60 MiB**. That parent address is **not a demonstrated allocation address** for the graphics unit.

A separate cold-module execution of `dmm_unit_ctrl_Init` returns zero after **1,401,064 original instructions**. The configuration declares three boot extents. Initializing the first boot unit, **0x116**, executes **8,381 original instructions** and stops at `osal_snd_sync_direct(0x00910042, request)` inside `dmm_timer_GetSyscnt`, module `.text+0x50e0`. The 32-byte request consists of word `0x20` followed by 28 zero bytes. No response is supplied.

REA reconstruction identifies this as the timer service: the return payload contains a status at byte 20 and a 64-bit counter at byte 24. `dmm_unit_ctrl_SetUnitAccInfo` consumes that counter and writes reservation/access records through `dmm_ctrl_GetUlogioExtentBuf`. `utimer_get_syscnt` itself requires a locked resource counter and accumulated module state; `utimer_read_res_counter` calls external `hwtimer_read_clock_cpu(0)`. A fabricated successful acknowledgement or zero timestamp would hide this missing contract. The shared log buffer is another prerequisite; it has not been supplied to this isolated experiment.

This is **isolated module execution**, not a loaded kernel module, running DMM service, completed allocation, or authentic camera boot. No GRM-MA/DMM reply has been added to the application process. The latest demonstrated `im.elf i` boundary remains E0034: **42,465,243 instructions**, original allocator assertion and SIGABRT request, without stream mmap or `/dev/fb0` operations. No original GUI screen has been produced.

## Inputs

| Preserved input | SHA-256 |
| --- | --- |
| `kmod/dmm.ko` | `c5cb62579f4719bed9248b8e3dabe4d95c6fa57481e07908f10b68098e54a74f` |
| package `setting/DmmConfig.bin` | `3e68b4f482ba24fceea1b572c8e2c5ee132f3fdd93ade64e634df47448bd3abd` |

The tool checks both against `artifacts/inventory/baseline.json`. This explicitly selected package configuration is not evidence of actual camera runtime `/setting` contents. REA batch manifests separately record subject hashes and verify unchanged source files.

## Reproduction and boundaries

```powershell
.\venv\Scripts\python.exe -u -m tools.research.dmm_config_trace
.\venv\Scripts\python.exe -m unittest discover -s tests -v
```

`tools/research/dmm_config_trace.py` maps allocated ELF sections and applies supported defined ABS32 and ARM CALL relocations. Undefined imports or literal dependencies stop explicitly. Original configuration reads use the module's memory-backed branch, beginning at file offset 64; its file-backed branch and host filesystem operations are not serviced. Only bounded `__memzero`, `memset` and nonzero unsigned division helpers are supplied. Memory permissions, input-byte limits, instruction budgets and timeouts remain enforced. The CPU selection, stack, section addresses and cold ELF BSS are constructed experimental state.

Original table parsers execute **1,023,000** and **211,252** instructions, respectively. Their final input cursors are **66,780** and **77,108**. They run separately from allocation-state initialization: parser output alone is not passed off as initialized allocator state. Boot reservations must finish before the tool attempts `Alloc(0x280)` and `Open`; neither call is reached in this run.

Two fresh runs produce byte-identical `artifacts/execution/dmm-config-trace-first.json` and `dmm-config-trace.json`, SHA-256 **0b8269c3bbce37434f0c518d405261c5f667e5e3fc31b4a363d93a01b5691dc9**. The earlier observer-timeout artifact is retained separately and is not a successful run.

REA artifacts under `artifacts/tools/rea/`: `dmm-config-and-open`, `dmm-table-init`, `grm-ma-allocation`, `dmm-config-getters`, `dmm-allocation-request`, `dmm-extent-allocation`, `dmm-system-counter`, `dmm-utimer-counter`, and `dmm-utimer-counter-source`. These are static reconstructions, checked against original instruction execution where stated; decompilation alone does not establish runtime state.

## Verification and next work

All **306 tests pass**, including six new constructed ARM checks for returns versus budget exhaustion, unknown IPC observation without mutation, configuration padding rejection, unresolved literal guards, bounded writable fills, and division by zero. Ordinary tests require no proprietary firmware. Full results: `artifacts/execution/dmm-research-final-suite.txt`.

Next establish the timer request's actual recipient/counter semantics and the shared reservation-log memory contract, then finish original boot reservations and allocate/open unit 0x280. Only after those steps can a verified physical extent inform the GRM-MA response. Preserve the E0034 application report and all explicit `/tmp`, entropy and preset-state assumptions. The status image is refreshed with this research boundary; capability counts remain unchanged.
