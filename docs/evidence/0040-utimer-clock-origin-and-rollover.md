# Evidence 0040: Timer clock origin and original rollover execution

## Result

The dependency-planning workflow identified the complete bounded named call chain from `utimer_get_syscnt` through locking in `osal_uipc.ko` and the resource-counter reader, plus an unresolved direct call at module **.text+0x1394**. Targeted original disassembly resolves that unnamed local helper as a phase/wrap tracker. Its lack of a function symbol remains explicit in the planner rather than being silently assigned a guessed function name.

Original `utimer_read_freerun`, at **.text+0x1b78**, reads **0xf240310c**, using compiled literal base **0xf2403000** and offset **0x10c**. This is a **separate free-running counter** from E0037's four descriptor-selected resource timer channels (`0xf240350c` through `0xf240380c`). Its original isolated window executes five instructions and stops at the unsupplied four-byte MMIO read, relocated observation PC **0x10010**, module **.text+0x1b88**. No register page/value is supplied.

Targeted REA reconstruction and retained original instruction listings show:

- `utimer_init_counter` obtains a 64-bit scheduling-clock result, subtracts the current resource counter to initialize its offset, registers the update callback and calls it. A zero timer epoch is not established.
- `utimer_get_schedclock` uses `utimer_read_freerun`, separate rollover history and arithmetic shifts to form its result. `utimer_get_syscnt` uses the resource reader, its history and the initialized offset. These are distinct stateful paths.
- `utimer_update_counter` calls both readers and, in its running branch, schedules resource timer 1 at current resource count + **0x20000000**. Counter history and update scheduling are prerequisites to interpreting later reads.

These observations do not establish hardware frequency, reset values, clock progression or a live boot timestamp. Neither clock path can be replaced with an unqualified zero acknowledgement.

## Original helper controls

`tools.research.utimer_counter_trace` executes the original **64-byte** helper at `.text+0x1394` with constructed counter/history inputs, a bounded stack and provisional Cortex-A9. History bit 31 tracks the observed high-bit phase. A low-to-high transition updates that phase; a high-to-low transition increments the lower wrap count. The return clears the phase bit:

| Counter control | Prior history | Returned wraps | New history |
| --- | --- | --- | --- |
| `0` | `0` | `0` | `0` |
| `0x80000000` | `0` | `0` | `0x80000000` |
| `0xffffffff` | `0x80000000` | `0` | `0x80000000` |
| `0` | `0x80000000` | `1` | `1` |
| `0x80000000` | `1` | `1` | `0x80000001` |
| `0` | `0x80000001` | `2` | `2` |

The controls execute 11 or 16 original instructions and return normally. They validate arithmetic for stated inputs, not actual camera samples, frequency or missed-wrap recovery. The tool separately executes the original freerun reader to its unknown MMIO boundary. Calls are bounded to 100 instructions and one second; faults, unsupported memory/control flow and limits remain distinct outcomes.

Input: original `utimer.ko`, SHA-256 **10bf86d6b707dfaf5bc36b11cad2030d7f8e0fcc6603cddc4061c3b3dde29436**, checked against the preserved baseline. Two fresh runs produce identical `artifacts/execution/utimer-counter-trace-first.json` and `utimer-counter-trace.json`, SHA-256 **abe68034f0e7e5a3f26be8b599f7c2b90cd2eca6def5598de0ec4ef33fc337c6**.

```powershell
.\venv\Scripts\python.exe -m tools.research.utimer_counter_trace
.\venv\Scripts\python.exe -m unittest discover -s tests -v
```

## Dependency workflow used

Plans retained under `artifacts/analysis/`:

- `utimer-service-followup`: depth 2 with cross-module candidates, four named functions; two of eight REA results already available.
- `utimer-counter-initialization`: two targeted initialization functions, four missing queries.
- `utimer-time-origin`: three targeted clock/update/init functions, six missing queries.
- `utimer-freerun-origin`: a single reader; its small original instruction listing directly identifies the MMIO access without needing another decompilation.
- `utimer-service-followup-warm`: **four static hits, zero misses, 8/8 REA results reusable** after analysis.

Generated commands were inspected before execution. Successful REA batches `plan-b6f070aef16df431-0`, `plan-b6f070aef16df431-1`, `plan-0f3667ca3e1bb766-0` and `plan-0cd76ca78edb4453-0` reside under `artifacts/tools/rea/`. Across those batches, two existing results were reused and sixteen missing queries ran through the installed native WSL provider; completed manifests retain target identity and unchanged-source checks. Static provider candidates remain distinct from actual load/IPC-routing evidence.

## Checks and remaining work

All **328 tests pass** (`artifacts/execution/utimer-counter-suite.txt`), including two new constructed ARM checks for phase/wrap transitions and rejecting an unsupplied freerun register. No camera/device/update operations were performed.

Next investigate the separate freerun hardware initialization and clock contract, then the timer service's dispatch and scheduling state. The independent `/setting/ulogio.bin`/partition-2 input remains unsupplied as documented in E0038. No application-service reply has changed; the main `im.elf i` boundary remains E0034, **42,465,243 instructions**, original allocator assertion/SIGABRT request and no stream mmap, fb0 request or original GUI. The status image is refreshed with unchanged capability counts.
