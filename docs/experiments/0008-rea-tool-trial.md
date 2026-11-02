# Experiment 0008: REA on the backup-service module

## Outcome

**WSL follow-up (2026-10-19):** the Windows-only limitation below is superseded for the new Linux trial. Ubuntu 26.04.1 under WSL 2 now runs REA 6.7.0 with Ghidra 12.1.4 successfully on the same ARM ELF relocatable module. This is a static-analysis tool result, not a new guest execution or UI milestone. See the follow-up below; the original Windows observations remain historical.

REA **6.7.0** was installed and tested locally against `backup.ko`. It successfully wraps the existing GNU objdump symbol inspection and produces evidence containing the module identity and original output. All **145 section-backed functions** independently match the existing ELF parser's names, sections, offsets and sizes.

The requested decompiler trial cannot complete in the current environment. REA's Ghidra provider explicitly rejects ARM ELF targets on Windows, in addition to lacking a configured Ghidra installation. The available Java runtime is 8; no working WSL distribution or Docker/Podman runtime was found. The installed GNU objdump supports symbol inspection of this ELF but not ARM disassembly; relocation offsets/symbols are returned with unknown relocation types.

No speedup in recovering backup operation 8 was measured. The useful potential remains decompilation and cross-reference analysis with a supported provider/host, rather than the already-covered symbol extraction alone. No emulator contract, firmware input or agent configuration was changed. No new camera/UI milestone or status-chart capability is claimed.

## Local installation and inputs

- Node.js: **24.17.0**; npm: **11.13.0**.
- Local runtime: `artifacts/tools/rea/runtime/node_modules/rea-agents/`.
- Downloaded package: `rea-agents@6.7.0` from the official npm registry, with dependencies under the same local prefix.
- Install used `--ignore-scripts --no-save --no-audit --no-fund --package-lock=false`; REA setup/agent registration was not run.
- Target: `firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/kmod/backup.ko`.
- Expected target SHA-256: `63c69e991a8da77e301a7090c8ba6e4dcced43921e88415e3591cf0e96dbb2c6`.
- Existing objdump: `C:\mingw64\bin\objdump.exe`.

REA's before/after evidence hashes and a fresh independent hash match the preserved inventory. No firmware routines, updater, target binary or camera operation was executed.

## Observed checks

| Operation | Result |
| --- | --- |
| `doctor --json` | Node/host accepted; native decompiler prerequisites and agent registration missing |
| `providers --json` | Provider capabilities and unavailable analysis engines recorded |
| `inspect-with-objdump ... symbols` | Success; 145 function records independently matched |
| `inspect-with-objdump ... relocations` | Offset/symbol output retained; relocation types reported as `UNKNOWN` by this objdump build |
| `inspect-with-objdump ... disassemble` | Provider process exit 1: cannot disassemble architecture UNKNOWN |
| `inspect ... --provider ghidra` | Explicit `target_format_unsupported`: Windows Ghidra P0 admits native PE and selected raw 6502, not ARM ELF |

The overall CLI call can still return evidence for a failed provider process. Provider exit status and diagnostic fields, not merely JSON production, determine the result.

The symbol inventory includes `backup_osal_call_func` at `.text+0x5204` (size `0x7e8`), `Backup_reg_cb` at `.text+0x2d8c` (size `0x118`), and `func_cb_sync` at `.text+0x4f6c` (size `0x14`). These are identified function symbols, not proof that operation 8 dispatches to a particular one. No decompiler output or recovered reply structure was obtained.

## Reproduction and retained results

From PowerShell in the project root, the local CLI entry point is:

```powershell
node artifacts/tools/rea/runtime/node_modules/rea-agents/scripts/rea.mjs --version
node artifacts/tools/rea/runtime/node_modules/rea-agents/scripts/rea.mjs doctor --json
$env:REA_OBJDUMP_COMMAND = 'C:\mingw64\bin\objdump.exe'
node artifacts/tools/rea/runtime/node_modules/rea-agents/scripts/rea.mjs inspect-with-objdump 'C:\Users\Administrator\Desktop\a6400 project\firmware\extracted_a6400\firmware.tar_unpacked\0700_part_image\dev\nflasha15_unpacked\kmod\backup.ko' symbols --format json
.\venv\Scripts\python.exe -m tools.research.rea_trial_audit
```

Retained artifacts under `artifacts/tools/rea/`: `doctor.json`, `providers.json`, `backup-symbols.json`, `backup-relocations.json`, `backup-disassembly.json`, `backup-ghidra.json`, `trial-audit.json`, and the local CLI runtime. The audit validates the evidence identities and symbol inventory; it does not rerun or benchmark the external tools.

## Assessment

A focused next trial would use REA with a supported Linux/Ghidra environment to analyze the original backup dispatcher and independently verify operation 8's case, argument layout and reply behavior against instructions and bounded execution. Ghidra's pseudocode would remain a reconstruction requiring verification. Installing Ghidra on Windows alone would not remove REA's observed ELF admission restriction. Enabling Windows features, installing a Linux distribution or configuring global agent integration was outside this local tool trial.

Primary tool references: [REA native analysis](https://github.com/morluto/rea/blob/main/docs/native-investigation.md), [Windows Ghidra boundary](https://github.com/morluto/rea/blob/main/docs/windows-ghidra-p0.md), and [objdump integration](https://github.com/morluto/rea/blob/main/docs/reverse-engineering-tools.md). The local CLI observations above determine this trial's result; upstream documentation is not a substitute for a successful target run.

## Successful WSL follow-up

Ubuntu uses Node 22.22.1, OpenJDK full JDK 21.0.12.1, procps and GNU ARM binutils. REA is installed locally in `/home/administrator/a6400-rea-tools/runtime`; Ghidra is in the adjacent `ghidra_12.1.4_PUBLIC` directory. No REA setup or global agent registration was performed. Ubuntu packages were installed for the runtimes, unzip and ARM binutils.

The official Ghidra release archive was checked against its published SHA-256 `ddac49f903da9d5bac833e5cc79395098b9c33cfd3279be5f31bd00387d2d4db`. The target's before/after SHA-256 remains `63c69e991a8da77e301a7090c8ba6e4dcced43921e88415e3591cf0e96dbb2c6`. [Official release and checksum](https://github.com/NationalSecurityAgency/ghidra/releases/tag/Ghidra_12.1.4_build).

`inspect --provider ghidra` succeeds with an immutable-source import and completed default analysis. Ghidra reports 276 procedures (including its external/discovered inventory) and 474 defined strings. These counts are not comparable to the earlier 145 section-backed ELF symbols. Doctor accepts every Ghidra prerequisite; its overall exit remains 1 because unrelated optional providers and skill registration are absent.

Decompilation of `backup_osal_call_func` identifies **case 8 as `Backup_write`**, passing a 16-bit value from message offset 24 and 32-bit values from offsets 28 and 32. The common epilogue copies the callee return into message bytes 4–7. Independent ARM disassembly and ELF records confirm the switch indexing (`operation + 1`), table entry `.text+0x526c` targeting `.text+0x559c`, the `R_ARM_CALL Backup_write` relocation at `.text+0x55e0`, and reply byte stores at `.text+0x5990`, `0x5994`, `0x59a4`, `0x59a8`. Thus the first guarded request is statically a backup write request; no write handler or firmware binary was executed. Its real result, storage prerequisites and downstream effects remain unestablished.

`Backup_reg_cb` also decompiles, and dispatch operation `0x10` selects it. `Backup_write` itself is a short wrapper whose inferred `void` prototype loses argument/return information; this is a concrete reminder to verify pseudocode against ARM instructions rather than implementing its inferred types directly.

The wrapper's helper at Ghidra coordinate `0x10748` also decompiles. Its original diagnostic string names `Backup_write_core`; the reconstruction shows unit lookup (`Data_SearchId`), attribute/size checks, locking, a destination obtained through `Data_GetDataPt`, and conditional callback notification. This supplies useful next research targets. Those helper paths and inferred prototypes have not been independently validated here, and neither their success values nor persistent content are supplied to the execution environment.

Reproduction: run `wsl.exe --exec sh '/mnt/c/Users/Administrator/Desktop/a6400 project/artifacts/tools/rea/wsl-trial.sh'` from PowerShell. It checks both archive and target identities, uses the local Linux runtime, and preserves results in `artifacts/tools/rea/wsl/`. Files include `doctor.json`, `backup-inspect.json`, `backup-dispatcher.json`, `backup-register.json`, `backup-write.json`, original ARM disassembly, `dispatch-verification.json` and `target-after.sha256`. The helper follow-up script decompiles Ghidra address `0x10748`; that address is an analysis coordinate, not a camera runtime address.

All **253 tests pass**, recorded in `artifacts/tests/rea-wsl-suite.txt`. No execution implementation changed. The strict backup-service guard remains in place, and no framebuffer/UI milestone or new status-chart capability is claimed. REA now provides usable decompilation for this research, but no measured end-to-end speedup is asserted.
