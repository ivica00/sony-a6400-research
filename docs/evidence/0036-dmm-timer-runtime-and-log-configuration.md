# Evidence 0036: DMM timer runtime and log configuration prerequisites

Follow-up: [E0043](0043-wbi-memory-and-recovered-logging-input.md) later identifies the logging input and DMM area inside the preserved compressed WBI image. The missing raw input conclusion below is historical; it does not describe that subsequently recovered package-WBI representation. Timer state remains separate.

## Findings

Original kernel export pairs identify `hwtimer_read_clock_cpu` at **0x601256ec** in the preserved kernel, using the independently established base **0x60108000**. Its literal at **0x60125724** names runtime table **0x604be020**. CPU indices 0 through 3 select entries at **20-byte** intervals. The routine loads the slot's pointer, then reads a word at pointer + 12. Indices above 3 leave the window through an external failure path.

A bounded execution of the original CPU-0 path stops after **nine original instructions**, at **PC 0x60125718**, before accepting the four-byte pointer at **0x604be020**. The report labels this `unsupplied_timer_runtime_read`, not a successful timer return. Although preserved bytes at the table are zero, this does not establish initialized runtime timer state. The probe supplies **zero responses**. The eventual register read is not reached; its address and value remain unestablished.

The DMM logging dependency is also traced to its producer. Original `sbin/init` loads `/usr/kmod/osal_ulogio.ko` with **`ulogio_initfile=/setting/ulogio.bin `**. `ulogio_module_init` selects the file-loading branch when its initial-data pointer is absent, reads the file into allocated memory, and calls `ulogio_init`. That initializer calls `ulogio_lbm_init`, which builds a live lookup table from the configuration and allocates its table storage. No path ending in `/ulogio.bin` appears in the preserved input inventory. This is an **unsupplied input**, not proof of absence on a running camera.

Original `ulogio_sync_api_handler` dispatches command **0x0b** to `ulogio_get_logaddr`. For DMM's nonzero subsystem **0x61**, area **0**, the latter uses `ulogio_lbm_lookup_table_find`, validates the area index, and returns the selected area address at request offset **12** and size at offset **8**. Its final instructions convert the address to a physical-address form. The returned address is therefore derived from live configuration/allocation state, not an arbitrary buffer the process probe may invent. The `Backup_read(0x00fa0132)` branch belongs to subsystem zero and is not DMM's branch.

These findings refine E0035; they do not complete timer initialization, logging initialization, DMM boot reservations or graphics allocation. The application contract is unchanged: latest demonstrated `im.elf i` run remains **42,465,243 instructions**, ending at the original allocator assertion/SIGABRT request without stream mmap, `/dev/fb0` open or original GUI output.

## Inputs and reproduction

| Input | SHA-256 |
| --- | --- |
| `vmlinux.bin` | `12eeec829407595e28265f7d0db3b88c56f63a9f0fdd725c9c53c66a49643707` |
| `osal_ulogio.ko` | `9645f7bfc8148a5fcf52829dd3161fcbf95c58b246691e5d24ec5e302237c074` |

The init input hash is retained in the report alongside these hashes; all three are checked against the preserved baseline.

```powershell
.\venv\Scripts\python.exe -m tools.research.dmm_runtime_trace
.\venv\Scripts\python.exe -m unittest discover -s tests -v
```

`tools/research/dmm_runtime_trace.py` verifies a unique aligned kernel export value/name pair, records the original instruction window and relocation-aware logging-function disassembly, records actual init options, and executes the timer window with a constructed stack and provisional Cortex-A9. Only stack reads and the function's literal word are allowed; other data reads stop before being accepted as supplied runtime state. Execution is bounded to 100 instructions and one second. Unknown control flow and memory faults remain distinct stops.

`artifacts/execution/dmm-runtime-trace-first.json` and `dmm-runtime-trace.json` are byte-identical, SHA-256 **c7da04191ac4ed09b1d6c9680263a5bc6b30af9a46ce30b89eae947fde01fdc8**. Additional static reports `dmm-log-memory-instructions.json` and `dmm-log-init-source.json` retain the intermediate investigation; the final report includes their relevant functions.

## Tool limitation and checks

Two REA/WSL batches (`artifacts/tools/rea/dmm-log-memory-source` and `dmm-log-memory-source-retry`) fail before MCP initialization. Their failed manifests are retained, not described as successful analysis. Direct elevated WSL access succeeds, but the Python child process receives UTF-16 `Wsl/E_ACCESSDENIED` text that the current launcher misreports as JSON decoding failure. Native Python libraries also need the normal tool escalation in this session. No installation, security setting or global configuration was changed. Targeted original disassembly and isolated execution provided the evidence above.

All **310 tests pass** (`artifacts/execution/dmm-runtime-final-suite.txt`), including four new constructed tests for export ambiguity, rejection of static zero timer pointers, CPU slot selection and unsupported CPU control flow. Tests use constructed code, not proprietary kernel input. Historical process policies are unchanged.

Next trace the producer of the kernel timer table and the source/generation of `/setting/ulogio.bin`, including any preserved boot configuration representation. Do not invent a timer pointer/counter or logging region to bypass these prerequisites. A package-backed logging policy would still need an identified input and explicit scope, as with the existing DMM package configuration experiment.
