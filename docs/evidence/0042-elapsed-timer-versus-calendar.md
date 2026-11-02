# Evidence 0042: Elapsed timer units, calendar service and DMM usage

Follow-up: [E0043](0043-wbi-memory-and-recovered-logging-input.md) recovers the previously unsupplied logging input from the packaged WBI image and verifies the original DMM log lookup. The timer-unit findings remain unchanged; current timer/MMIO state is still unsupplied.

## Answer to the timer/date/image-count question

The DMM timer value is an **elapsed-time counter in software microseconds**, not a packed calendar date or a photograph count. There is a real connection to dates: the separate `udate.ko` calendar service uses differences between these timer readings to advance stored calendar state. That does not make an individual timer reading a calendar date.

Primary original-code observations:

- `utimer_drv_init` divides both the system-counter and scheduling-clock readings by **1000** before formatting `%lld[ms]` boot diagnostics.
- `udate_get_localtime` requests the system counter on **0x00910042**, subtracts its saved counter baseline, divides the difference by **1,000,000**, and passes the result to `date_time_add_seconds`. It also applies stored local-time adjustments and calendar validity rules. This directly establishes the software time-unit interpretation.
- `udate_open_kif` registers its separate date set/get service at **0x0090013d** and notifications at **0x0090013f**, distinct from the timer queue.
- `dmm_unit_ctrl_SetUnitAccInfo` obtains the timer value and stores it in unit access history and extent-log records. It records initial/current access times alongside subsystem/operation/allocation metadata. These are observations of the selected function, not a global assertion about every possible timer consumer.

No image-capture or shutter counter is involved in the demonstrated path. This conclusion applies to this specific timer request; it does not identify or model any separate camera image/shutter counters. The software microsecond unit does **not** establish oscillator frequency, cycle accuracy, initial hardware state or the current counter value.

## Original argument-window execution

`tools.research.timer_units_trace` verifies input hashes and extracts each function from its actual ELF section. It executes the two original instructions immediately before each selected `__aeabi_uldivmod` call, then stops **before** the division helper:

| Module/function | Section | Call offset | Original divisor argument |
| --- | --- | --- | --- |
| `utimer_drv_init` | `.init.text` | `0x7c` | `1000` |
| `utimer_drv_init` | `.init.text` | `0xec` | `1000` |
| `udate_get_localtime` | `.text` | `0x504` | `1000000` |

The selected slices overwrite explicit register sentinels with the observed arguments. They supply no counter/calendar value and do not execute a division, service request or boot. Original instruction listings and literal/string references are retained. Bounds cap each window at 32 bytes, 16 instructions and one second; reads past supplied bytes stop even within mapped page padding.

An initial trial incorrectly used `.text` for `utimer_drv_init`, which resides in `.init.text`. That failed trial is preserved as `artifacts/execution/timer-units-wrong-section.json`. It was not treated as successful evidence. The corrected tool resolves the section from each function's actual metadata.

Inputs:

| Input | SHA-256 |
| --- | --- |
| `utimer.ko` | `10bf86d6b707dfaf5bc36b11cad2030d7f8e0fcc6603cddc4061c3b3dde29436` |
| `udate.ko` | `5d7adf8252cdcb34ce61a974b6da483ef821151e0f6cdb852eac98e14a94e2fc` |
| `dmm.ko` | `c5cb62579f4719bed9248b8e3dabe4d95c6fa57481e07908f10b68098e54a74f` |

Two corrected runs produce identical `artifacts/execution/timer-units-trace-first.json` and `timer-units-trace.json`, SHA-256 **cf6492a64273fc86f631b0ca2642058074a7271499251b4fadda1ee3bee544f4**.

```powershell
.\venv\Scripts\python.exe -m tools.research.timer_units_trace
.\venv\Scripts\python.exe -m unittest discover -s tests -v
```

## Planner and REA evidence

Plans: `artifacts/analysis/dmm-counter-use` and `calendar-versus-utimer`. Inspected generated WSL batches completed under `artifacts/tools/rea/plan-e8b7de338ebda527-0` and `plan-414c3970a3320c57-0`. The DMM batch reused **five** retained results and executed three missing queries; the calendar batch executed four new targeted queries. Manifests retain completed status, exact subject hashes and unchanged-source checks. Calendar/unit semantics are supported by the connected original arithmetic and consumers, not names alone.

## Checks and next gate

All **334 tests pass** (`artifacts/execution/timer-units-suite.txt`), including three new constructed argument-window tests for immediate/literal values, stopping before calls and rejecting mapped padding/unaligned ranges. No camera operations, date changes, image-count changes or firmware/device writes occurred.

The next gate remains an identified counter initial state and timer register/clock behavior, plus the independent logging configuration from the unpreserved setting partition. Calendar logic depends on timer deltas and stored date state; it cannot supply missing timer hardware state by itself. Main `im.elf i` behavior remains E0034's **42,465,243 instructions**, original allocator assertion/SIGABRT request and no original GUI/fb0 request. Status visualization is refreshed without increasing capability counts.
