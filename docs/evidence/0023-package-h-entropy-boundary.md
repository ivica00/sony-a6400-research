# Evidence Record 0023: Package H Reaches the Stack-Guard Entropy Boundary

## Result and scope

The Package H experiment advances beyond the previously recorded 15,000,000-instruction linker window. At **41,953,485 instructions**, original code stops at `unsupported_filesystem`, reason `runtime_namespace_not_supplied`, during an `open` request whose path pointer addresses `/dev/urandom` in `libssp.so.0.0.0`. The reported boundary path `/dev` is the namespace prefix visited during resolution, not the complete requested name. The syscall PC is `0x5008bc64` in libpthread's open wrapper, syscall 5, flags 0. **No `/dev/fb0` initialization, framebuffer transaction, blit or camera UI screen was observed.** Package H's display objective remains incomplete.

This is a bounded process experiment with injected messages, not authentic full-camera boot. Passing the earlier symbol-lookup window does not establish completion of every plugin's relocations or constructors.

## Inputs and method

Preserved SHA-256 identities:

| Input | SHA-256 |
| --- | --- |
| `im.elf` | `866729eb0bc1e6f5aba04d8bf8e45491985afe89a078ccb106a1ce2476865225` |
| `ld-linux.so.3` | `7c215cee6c4175079d69cb1433c6be90189e793f6e44f068ed6ac97621dd7a2c` |
| `libObj.so` | `60ffd2b0f31f4bc139a7c13a4f62c25cdeb6a531ad5ef35df48471e6e36e88b1` |
| `libssp.so.0.0.0` | `ab8da476bd2511f0b5173adbab0bb72d76e64728f6f2a1af0f8eda80319c6a8e` |
| rootfs `nflasha7` | `305e289ecc1d768544af71c83d58ce23ec4d232be1e7572d9d4f68f0f12188cc` |
| usr `nflasha15` | `0e9b19144b021d8b1b1908554a7ac9cdc6f8b9599eeeb1d53118b8832a296e56` |

Commands from project root:

```powershell
.\venv\Scripts\python.exe -m tools.research.experiment_ui_boot --instructions 100000000 --timeout-us 420000000 --report artifacts/execution/package-h-symbol-resolution.json
.\venv\Scripts\python.exe -m tools.research.experiment_ui_boot --instructions 45000000 --timeout-us 240000000 --report artifacts/execution/package-h-runtime-dev-repeat.json
.\venv\Scripts\python.exe -m tools.research.display_boot_trace
```

The `threads` policy, original argv `/usr/bin/im.elf`, deterministic process-entry inputs and static filesystem snapshot remain experimental. The runtime `/etc` overlay is unsupplied; this run does not use the conservative mount-aware namespace. Existing UIPC/scheduler substitutions remain in effect. The experimental message sequence is `0x00940007`, `0x0092014b`, `0x00940036`, `0x00940038`, `0x00920152`, with 60 zero payload bytes following each identifier, delivered when Task 94's queue `0x0094016a` is empty. Only the first three are delivered before the new boundary. Static handler IDs do not validate producer ordering, timing, mode or payloads; earlier E0021/E0022 use of “authentic” for this injection should be read with this correction.

The runner now uses the production dynamic-ID handler rather than a second monkey-patched implementation, exposes separate instruction/time limits and report paths, verifies preserved filesystem images, records stimulus assumptions, and counts unsigned errno returns as failed opens. New reports preserve register and standard-output diagnostics. Reports are saved before optional diagnostic image conversion. No original firmware input is modified.

## Observations

- An initial 100-million-instruction/60-second run times out after 18,291,523 instructions at `0x4000701c` in the original interpreter. A timeout is not success.
- The longer run services 600 syscalls before the namespace boundary. It records 44 successful open operations; E0022's count of 86 included failed searches encoded as unsigned errno values. Successful opens are not equivalent to completed plugin initialization.
- The 15-million-instruction runner regression reproduces 592 serviced syscalls, the same first three delivered events and zero framebuffer transactions (`package-h-runner-regression.json`).
- The default no-response probe still reaches its first syscall after 1,183 instructions (`package-h-default-regression.json`). No execution implementation or historical policy is changed in this work; other historical real-firmware policies were not rerun.
- Static `libssp` `.init_array` contains target `0x9c5`. The Thumb initializer at `0x9c4` checks `__stack_chk_guard`, loads the string `/dev/urandom` via `ldr`/`add pc` at `0x9d4`/`0x9d6`, calls `open` at `0x9d8`, and requests four bytes via `read` at `0x9e8`. Original code has a failure fallback, but this experiment does not manufacture an open failure to select it.
- `GRM_fbrmInitializeYUV` at Thumb `0x65e8c1` is original `push; movs r0,#0; add r7,sp,#0; pop`. Its name does not establish a display initialization edge. `ObjDisplay_Create` at `0xda3f85` allocates an object and calls `0xdb4cec`; further display-path tracing remains necessary.

The independent 45-million-instruction repeat reproduces the exact status, instruction count, syscall count, boundary arguments/PC and final 32 instructions. Its captured registers retain the original caller context; see `package-h-runtime-dev-repeat.json`.

## Verification and remaining work

All **204 unit tests pass**, recorded in `artifacts/tests/package-h-suite.txt`. These tests do not validate the camera's runtime state or the framebuffer model's defaults.

Next establish an explicit evidence-backed entropy-device contract and its replay/provenance requirements; identify authentic boot-event producers and payloads; then follow the first actually executed display call. The existing framebuffer defaults (960x540, ARGB8888, physical base `0x60000000`) lack a demonstrated camera driver source in this record and cannot support an authentic screenshot claim. Device metadata, geometry, format, DMA/submission behavior and observed guest writes must be verified before declaring a first camera UI frame. `status_a6400.png` is a project-status visualization, not firmware-rendered camera output.

Status visualization accounting correction: replaced instruction counts as completion units with one bounded-run milestone, and marked unverified Task 94 phases/display steps incomplete. Chart percentages are local research checklists, not camera compatibility percentages.
