# Evidence 0037: Original timer pointer producer and restored REA workflow

## Original timer slices

The original kernel's exported `udif_hwtimer` descriptor selects one device through its pointer array at `0x603c9354`. The device at **0x604d9084**, named `hwtimer`, declares four channels beginning at **0x604d932c**, stride **0x5c**. Channel descriptors contain these physical/compiled virtual bases, each with a **0x100-byte** extent:

| CPU | Descriptor base value | Counter read address |
| --- | --- | --- |
| 0 | `0xf2403500` | `0xf240350c` |
| 1 | `0xf2403600` | `0xf240360c` |
| 2 | `0xf2403700` | `0xf240370c` |
| 3 | `0xf2403800` | `0xf240380c` |

The callback at **0x601252d8** derives a channel pointer from device + `0x14` and channel index, then stores its base into timer runtime table **0x604be020 + CPU*20**. `tools.research.dmm_timer_setup` executes the original slice **0x6012534c through the store at 0x6012537c**, **13 original instructions per channel**. It observes exactly the four expected pointer writes. The slice excludes earlier proc setup and later interrupt registration, locking and timer initialization; it is not execution of a complete boot callback.

An explicitly composed control transfers each observed store to a fresh original `hwtimer_read_clock_cpu` window. Each executes **10 original instructions** and stops at **PC 0x6012571c**, on its counter read at the address in the table above. No MMIO page, register value or timestamp is supplied. Default timer-window behavior remains unchanged: without the selected pointer control it still stops before reading the unsupplied pointer table, as in E0036. These are selected static descriptor/reset-state slices, not observed camera runtime mappings or a running timer.

`vmlinux.bin` SHA-256 remains **12eeec829407595e28265f7d0db3b88c56f63a9f0fdd725c9c53c66a49643707** and is checked against the preserved baseline before execution. Kernel export matching now requires a complete null-delimited symbol name, avoiding a false ambiguity between `udif_hwtimer` and the suffix of `__udif_init_udif_hwtimer`.

Two runs produce identical `artifacts/execution/dmm-timer-setup-first.json` and `dmm-timer-setup.json`, SHA-256 **ba4a3121a566d42fe2e45f6d2e60d38af524428cef527f82e783332fc488f59b**.

## Logging configuration and preserved inputs

Successful native-WSL REA batches reconstruct `ulogio_lbm_init`, `ulogio_init`, `ulogio_module_init`, `ulogio_get_logaddr` and the root parser `FUN_00010090`, with the latter's original instruction listing retained. The root parser requires tags corresponding to **RECO, LGNM, LOGB, DBGL and PRTB** (combined presence mask `0x1f`). `LOGB` supplies the log physical base and size; `SUBS` records describe individual subsystem areas. The log area is not a free choice of kernel heap address. E0036's init option `/setting/ulogio.bin` remains the selected source.

`python -m tools.research.ulogio_input_scan` hashes and streams all **1,126** preserved baseline inputs, **1,759,255,471 bytes**, using 1 MiB chunks with overlap. It finds **zero candidate raw LOGB records** with declared length 16–4096 bytes fitting the input. Report: `artifacts/execution/ulogio-input-scan.json`, including baseline manifest hash. This rules out that bounded raw representation in those inputs, **not compressed/encrypted representations or a runtime file on a camera**. The scan does not extract, mutate or refresh inputs.

## REA/WSL recovery

The Windows-Python child-launch problem recorded in E0036 remains reproducible. Direct WSL invocation works. `rea_wsl_batch` now also runs directly inside the existing WSL Python runtime using only Python's standard library, starting the same installed Node/REA/Ghidra provider. No packages, security settings or global configuration were changed. The existing Windows launcher path remains supported. Target namespace, pre/post hash checks, query digest checks, bounds, new report directories and failed-run retention remain enforced.

Successful batches:

- `artifacts/tools/rea/dmm-log-native-wsl`
- `artifacts/tools/rea/ulogio-root-config-native`

Both manifests confirm completed queries and unchanged `osal_ulogio.ko`, SHA-256 **9645f7bfc8148a5fcf52829dd3161fcbf95c58b246691e5d24ec5e302237c074**. REA results remain static reconstruction, not executed kernel service behavior.

Example from PowerShell:

```powershell
wsl.exe --cd "/mnt/c/Users/Administrator/Desktop/a6400 project" --exec python3 -u -m tools.research.rea_wsl_batch --target firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/kmod/osal_ulogio.ko --procedure ulogio_get_logaddr --report-dir artifacts/tools/rea/NEW_REPORT_DIRECTORY
.\venv\Scripts\python.exe -m tools.research.dmm_timer_setup
.\venv\Scripts\python.exe -m tools.research.ulogio_input_scan
```

Use a genuinely new directory, not the literal example if it already exists. Native libraries and direct WSL require the normal tool escalation in this environment; successful runs used that mechanism.

## Validation and remaining work

All **315 tests pass** (`artifacts/execution/dmm-timer-setup-suite.txt`). New constructed tests cover exact export-name boundaries, composed reads stopping before unknown hardware, launcher namespace/hash guards, records split across scan chunks and rejected truncated/changed inputs. No physical camera operations were performed.

Next trace original writes/configuration for the selected timer channels and determine supported register/clock semantics before supplying any counter result. Logging needs an identified configuration source or producer, including the mandatory physical backing range and subsystem 0x61 layout. These remain prerequisites to completing original DMM boot reservations and graphics allocation. No application-service replies have been added: `im.elf i` remains at E0034's **42,465,243 instructions**, original allocator assertion/SIGABRT request, with no stream mmap, `/dev/fb0` request or original GUI. The status image is refreshed without increasing capability counts.
