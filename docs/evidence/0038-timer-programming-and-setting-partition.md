# Evidence 0038: Timer programming and the missing setting partition

Follow-up: [E0043](0043-wbi-memory-and-recovered-logging-input.md) recovers the identified logging file buffer/state from compressed warm-boot memory. The complete partition-2 image remains absent, but the logging-input research gate is superseded for an explicit package-WBI environment. This does not supply timer hardware state.

## Observed original behavior

`tools.research.dmm_timer_program` composes E0037's original pointer-store results with the original kernel timer-programming routine at **0x60124cec**. In constructed supervisor mode with a bounded stack, it executes **51 original ARM instructions**, including the original interrupt-disable and barrier instructions, and stops at **0x60124d4c**, before the next runtime callback-table access. It records **12 four-byte stores**:

1. For channels 0–3 in order: write **0x32** at channel offset **0**, then **0x11** at offset **4**.
2. For channels 0–3 in order: write **0x1032** at offset **0**.

Channel bases are the original descriptor-derived `0xf2403500`, `0xf2403600`, `0xf2403700` and `0xf2403800`. No counter read, reset value, elapsed time or tick is supplied. These are **observed software bus requests**, not established hardware register semantics: the writes do not prove that a counter returns zero, runs at a particular frequency or has reset successfully. The mapped observation pages reject all reads, including reads of a register that was just written. Only the observed store locations are accepted. No interrupts or peripheral effects are modeled.

This is an isolated composed slice. Earlier boot/IRQ setup and the later callback/read path remain unexecuted. No application service contract changes.

## `/setting` source

Hash-checked original `sbin/init` mount row 2, **0x13330**, identifies:

```text
/dev/nflasha2 /setting vfat flags=0xc0ed0490 data=posix_attr
```

Together with E0036's original `ulogio_initfile=/setting/ulogio.bin` option, this connects the unresolved logging configuration to the camera's **setting partition 2**. No `/dev/nflasha2` image is present in the preserved baseline. The preserved updater supplies partition images 3, 5, 7 and 15, plus partial application setting files; those are not a complete partition-2 snapshot. E0037's raw-tag scan found no candidate LOGB record in all inventoried inputs. Absence from that set is not proof of absence on an actual camera or in an unrecognized compressed representation.

Consequently, an authentic DMM log-area address cannot yet be reconstructed. It needs an identified `/setting/ulogio.bin` or its original producer/representation, including its LOGB physical range and subsystem 0x61 area layout. The package-backed DmmConfig experiment does not supply this independent input. A guessed logging buffer would conceal the missing state.

## Reproduction, identity and checks

```powershell
.\venv\Scripts\python.exe -m tools.research.dmm_timer_program
.\venv\Scripts\python.exe -m unittest discover -s tests -v
```

Both kernel and init are checked against the baseline before use, with their full identities retained in the report. Kernel SHA-256: **12eeec829407595e28265f7d0db3b88c56f63a9f0fdd725c9c53c66a49643707**; init SHA-256: **0af5724ece7f60db2831b7a4e61829be369868027877cca0f921f981ae8dc7ad**.

Two runs give identical `artifacts/execution/dmm-timer-program-first.json` and `dmm-timer-program.json`, SHA-256 **0ed949eea79fe4b6f55d572984d7749c18e944cb110570c6b33d0a9a995d1000**. The probe bounds execution to 200 instructions and one second; unknown reads, writes, control flow and faults stop explicitly. The observation buffer is not a new hardware model or execution policy in `src/a6400/`.

All **318 tests pass**, including three constructed checks for rejecting register readback, rejecting stores to other offsets, and validating selected channels/input bounds. Suite: `artifacts/execution/dmm-timer-program-suite.txt`. No camera, updater or device-write operation was performed. A web search for the exact proprietary timer source name returned no results and is not used as technical evidence.

## Remaining work

The timer register effects, clock progression and subsequent callback dependency still need evidence. Logging requires the identified missing configuration or its producer. These dependencies remain before original DMM boot reservations and graphics allocation can finish. Latest main-process evidence remains E0034: **42,465,243 instructions**, allocator assertion/SIGABRT request, no stream mmap, `/dev/fb0` request or original GUI. The status image is updated without changing capability counts.
