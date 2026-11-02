# Evidence 0030: Original backup dispatch and packaged preset lookups

## Result and scope

REA 6.7.0 with Ghidra 12.1.4 now runs through WSL 2. A shared session avoids repeated imports: the 14-query driver batch completed in **12.603 seconds**, including its first analysis; subsequent queries in that batch took 5–29 ms. This measures this local static-query batch, not an end-to-end project speedup.

Original instructions now establish the first blocked startup request's producer, operation-8 dispatch and read-only lookup of three relevant units in all **11 packaged BK4 presets**. The startup flag is one byte with value `1`; both LIRO-related units contain the four-byte package value `0x035c6000`. This replaces uncertainty about the request's meaning with reproducible original-code evidence.

**The strict startup boundary does not change.** Package presets are identified inputs, not current camera RAM, a validated boot selection or saved device settings. No backup reply, write, kernel-module registration, framebuffer operation or camera UI is supplied. E0029's backup guard remains required.

## Inputs and identity

| Input | SHA-256 |
| --- | --- |
| `usr/kmod/backup.ko` | `63c69e991a8da77e301a7090c8ba6e4dcced43921e88415e3591cf0e96dbb2c6` |
| `usr/lib/libbackup.so` | `ab3ad7b492a1654bfa3f1468106785f933539fffcbe709f808af8dc2c59bbc15` |
| `usr/bin/im.elf` | `866729eb0bc1e6f5aba04d8bf8e45491985afe89a078ccb106a1ce2476865225` |
| Package `CX62600_UC2.bin` | `241c8521035bc9ff1edbe66cf3d42d81879a4bef8ff9e21cbfb84530a1446154` |

All preset paths and hashes are recorded individually in `artifacts/execution/package-h-backup-state.json`, checked against the preserved input inventory. They are under `0110_backup/SYSASTRA-DSLR/DX2/`; the `usr` inputs are under the existing `nflasha15_unpacked` tree. Package `MainDest.txt` names `CX62600_UC2.bin`; that packaging observation does not select the camera's runtime destination.

REA imports immutable temporary copies, and the launcher checks the source before and after its queries. `backup_rea_audit` independently checks the original inventory, before/after identities and **32 retained query identities** across six relevant sessions. One client session explicitly failed on ambiguous `backup_sync_msg` symbols; the later query selected Ghidra coordinate `0x10f64`, matching the ELF's linked Thumb entry `0xf65`. Failed sessions are retained as failed. Analysis coordinates such as the module `.text` base `0x1015c` are not camera addresses.

The Linux tool environment is Ubuntu 26.04.1, Node 22.22.1, full JDK 21.0.12.1 and Ghidra 12.1.4. See [Experiment 0008](../experiments/0008-rea-tool-trial.md) for the checked Ghidra release archive. No REA agent registration, target execution by Ghidra, updater execution or physical-camera operation occurred.

## Request producer and consumer

At linked Thumb function `im.elf:0x99c4`, **eight original instructions** construct `Backup_write(0x3e, 0x003e000b, &value)` with a stack word `value = 1`. The isolated slice stops before the call at `0x99d8`; its temporary code and stack addresses are explicitly constructed. Static instructions after the call test the signed result before another helper. No return is forced.

Original `libbackup.so:Backup_write` sends operation **8**, argument count **3**, to queue `0x003e014d`. Its message producer initializes reply bytes 4–7 and copies them to the caller only after transport success, consistent with E0029's reason for rejecting an untouched reply.

The kernel module's dispatcher executes **33 original ARM instructions** from `.text+0x5204` to the call boundary at `.text+0x55e0`. The operation-8 jump-table entry at `.text+0x526c` selects `.text+0x559c`. The call's `R_ARM_CALL` relocation names **`Backup_write`**. Decoded arguments are `r0 = 0x3e`, `r1 = 0x003e000b`, `r2 = 0x7feffd74`, matching the blocked request. The supplied request bytes remain unchanged; the call is not executed. The common original epilogue stores the callee's return into message bytes 4–7.

REA's reconstruction of `Backup_write_core` identifies unit lookup, attributes and size checks, a write lock, data copying and conditional callback notification. These downstream operations have not run in the experiment. In particular, the short wrapper's inferred `void` prototype loses argument/return information; pseudocode is a guide to instruction verification, not a replacement contract.

## Original preset lookups

The independent host preflight checks a complete BK4 header, table extents, payload extent and checksum. It does not claim that original `Data_init` performs these checks.

For each preserved preset, original `Data_init` returns zero after **105 instructions**. Its original revision comparison and selected local call run; it computes the subsystem/property-table addresses in a constructed `.bss` mapping. Subsequent original `Data_SearchId`, `Data_GetDataPt`, `Data_GetSize`, `Data_GetVmaxSize` and `Data_GetAttr` run using those observed table addresses and read-only preset bytes.

| Unit | Descriptor file offset | Original size | Attribute | Package data |
| --- | --- | --- | --- | --- |
| `0x003e000b` | `0x5a76` | 1 byte | 0 | `01` |
| `0x00fa007c` | `0x1d272` | 4 bytes | 0 | `00 60 5c 03` |
| `0x00fa0076` | `0x1d24e` | 4 bytes | 0 | `00 60 5c 03` |

These observations match across all 11 package presets. The LIRO values are little-endian `0x035c6000`, not permission to map or execute code there. E0029's LIRO address-conversion and validation dependencies still apply.

Only selected `R_ARM_ABS32` literals and same-section `R_ARM_CALL` sites in these bounded functions are relocated. The report preserves each original relocation and constructed word. This is not a general module loader, a booted kernel or an IPC-connected backup service. Original return, fault, unexpected flow, timeout and budget outcomes remain distinct. All preset bytes and the initialized lookup state are read-only during getter execution.

## Remaining runtime requirements

The module's original initialized defaults name `/setting/Backup.bin` for both primary and secondary inputs, `Backup_load = 0`, and `Backup_save = 1`. These are static defaults, not proof that boot passes no overrides. [E0014](0014-boot-selection-and-root-device.md) identifies `/setting` as a writable vfat mount on `/dev/nflasha2`; that partition's contents are not supplied by the extracted package partitions.

Original `backupfile_init` reads the header, checks its cookie, calls `arch_phys_to_cache` on its first word, and conditionally loads file data when its load argument equals 1. Otherwise it initializes tables at that converted address. REA and retained original instruction records expose a dependency on preexisting RAM as well as runtime files. Package presets therefore cannot silently stand in for the successful service's live state.

Next work: resolve actual module arguments, the original file-selection helper and boot-time RAM producer/address conversion. Then choose an explicitly identified state input and execute the write path with verified locking/copy/callback contracts. Do not acknowledge the request merely because its package default is also `1`.

## Reproduction and verification

```powershell
.\venv\Scripts\python.exe -u -m tools.research.rea_wsl_batch --procedure Data_init --procedure Data_SearchId --procedure Data_GetDataPt --procedure Data_GetSize --procedure Data_GetAttr --procedure Data_GetVmaxSize --procedure backup_init --procedure backupfile_init --procedure backupfile_load --procedure backupfile_load_file --procedure backup_osal_init --procedure 0x10748 --instructions Backup_write --instructions Data_SearchId --report-dir artifacts/tools/rea/backup-state-reproduction
.\venv\Scripts\python.exe -m tools.research.backup_state_trace
.\venv\Scripts\python.exe -m tools.research.backup_rea_audit
.\venv\Scripts\python.exe -m unittest discover -s tests -v
```

The REA launcher requires a new report directory and this documented local WSL installation. It closes the analysis target and its server after the bounded queries. The static original-code trace does not require REA to run again. Retained batch manifests give the exact additional queries and elapsed times; all output stays under `artifacts/`.

All **262 tests pass**, including the previous 253 and nine new fixture/Thumb checks, in `artifacts/tests/package-h-backup-state-suite.txt`. Constructed tests reject corrupt/truncated preset data, unsupported revisions, table overlap and overflowing extents, and distinguish Thumb call boundaries, unexpected branches and instruction exhaustion. Original preset/dispatcher execution repeats with matching traces and values. Core process-execution policies were not changed; the existing strict process boundary remains E0029's 2,107,833 (`l`) / 2,107,861 (`i`) instructions with no backup reply.

The regenerated `status_a6400.png` describes preset-lookup research and still states **No Camera UI**. Checklist totals remain unchanged; neither the chart nor this static/bounded milestone is firmware-rendered display output.
