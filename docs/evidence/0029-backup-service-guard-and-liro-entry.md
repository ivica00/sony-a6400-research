# Evidence 0029: Backup-service guard and bounded LIRO entry

## Result and correction

Tracing the module request exposes an earlier fidelity gap: the UIPC model acknowledged synchronous backup messages without executing a recipient. Original `libbackup.so` could then interpret zero-initialized reply fields as a successful service result. The observed `adr=0x0` is therefore not established camera state.

The UI experiment runner now defaults to **stopping before replies to backup queue `0x003e014d`**. Fresh `l` and `i` runs stop at **2,107,833** and **2,107,861** instructions, respectively, after **137 supplied responses**, with `unsupported_uipc_contract / backup_service_reply_not_supplied`. The blocked request supplies no response and modifies no reply data. No framebuffer transaction or camera UI is produced.

E0028's exact module-buffer observation remains reproducible under the explicitly named historical `unverified-ack` policy. It is not proof of authentic settings, kernel-module initialization or a booted backup service. Earlier deep process reports using this acknowledgement behavior retain their recorded implementation, not validated service semantics.

## Original consumer and parameter producer

Inputs are unchanged. In particular:

| Input | SHA-256 |
| --- | --- |
| `libbackup.so` | `ab3ad7b492a1654bfa3f1468106785f933539fffcbe709f808af8dc2c59bbc15` |
| `im.elf` | `866729eb0bc1e6f5aba04d8bf8e45491985afe89a078ccb106a1ce2476865225` |
| `liro.ko` | `72cb5700d34ecac6f8a9475f05268e55c94bf972183884bdb0e6d95edc40d9f7` |

Original `Backup_read` at linked Thumb address `0x1205` calls `backup_sync_msg`. The latter initializes message bytes **4–7** to zero, invokes `osal_snd_sync_msg` at `0x100c`, and, if that returns zero, reads bytes 4–7 and copies them to the caller's result destination at `0x1028`. A transport acknowledgement without recipient execution therefore leaves an apparent zero service result. An unchanged output buffer is not evidence that persistent data contained zero.

The LIRO parameter producer in `im.elf` at `0xb314` initializes its output word, requests backup unit `0x00fa007c`, and has a conditional second request for `0x00fa0076`. Original error/fallback branches exist, but selecting a service error or reply value requires its own contract; their existence does not authorize forcing that outcome. The format string is `%s adr=0x%x %s %s`.

The first guarded request occurs earlier than that LIRO-specific read. It has operation word **8**, reply word zero, argument count **3**, queue `0x003e014d`, and argument words `0x3e`, `0x003e000b`, and a guest pointer. This record does not assign an unverified service meaning to operation 8. The guard covers all requests to this identified recipient rather than inventing success for registration-like requests.

## Policy and memory changes

`GuestUipc` defaults to `backup_service_policy='stop'`. It records the request in the stop boundary before appending a serviced transaction or returning a guest value. Message read failures are no longer swallowed as successful acknowledgements.

`experiment_ui_boot` selects this strict recipient policy by default. `--backup-service unverified-ack` explicitly reproduces the historical behavior and labels its transactions. For compatibility with earlier generic probe-policy experiments, `InterpreterProbe`'s legacy constructor default remains `unverified-ack`, now recorded in its report and assumptions; callers can select `stop`. Other synchronous recipient responses remain experimental and are explicitly described as such. This is a backup-service guard, not validation of all UIPC services.

The interpreter's UIPC host-read/write wrappers now preflight guest bounds and page permissions, enforce provenance on reads, and release overwritten provenance only after a permitted write. Unsupported memory requests stop without a response. These checks do not implement recipient behavior, timing, kernel callback dispatch or authentic pool allocation geometry.

## Isolated original LIRO windows

`tools.research.liro_startup_trace` checks all three inputs against the ELF inventory and decodes module relocations with the existing section-relative analysis. Three selected, verified `R_ARM_ABS32` literals are relocated to explicit constructed section addresses. No general module relocation or loader is implemented; external calls are stopped before execution.

- **Eight original ARM instructions** in `init_module` construct an array containing the `udif_liro` descriptor and count **1**, stopping before `udif_driver_register`. Registration is requested, not executed.
- A window starting at `liro_init + 0x50`, after unexecuted earlier helpers, tests the supplied address. Zero reaches the original `Address not set` diagnostic's `printk` call boundary. This does not establish that earlier helpers completed or that registration succeeded.
- Nonzero constructed controls `0x10000000` and `0xc0000000` become `0x70000000` and `0xe0000000`, respectively, before the entry-point diagnostic call. These demonstrate conditional address transformation only; they are not proposed camera addresses or permission to map firmware there.
- Static `tsk_entry` instructions show header validation and indirect firmware entry calls downstream. No header, firmware payload, kernel thread, callback or hardware response is supplied by this experiment.

The descriptor's initializer relocation selects `liro_init`; the full static instruction/relocation records and bounded traces are in `package-h-liro-startup.json`. The kernel/module-loader boundary remains unsupported in the historical process experiment.

## Reproduction

```powershell
.\venv\Scripts\python.exe -m tools.research.liro_startup_trace
.\venv\Scripts\python.exe -u -m tools.research.experiment_ui_boot --argument l --stimulus none --urandom-open --madvise-dontneed --regular-inode-rdev --readonly-image-times --trace-library-activation --instructions 3000000 --timeout-us 45000000 --report artifacts/execution/package-h-backup-guard-l.json
.\venv\Scripts\python.exe -u -m tools.research.experiment_ui_boot --argument i --stimulus none --urandom-open --madvise-dontneed --trace-library-activation --instructions 3000000 --timeout-us 45000000 --report artifacts/execution/package-h-backup-guard-i.json
.\venv\Scripts\python.exe -u -m tools.research.experiment_ui_boot --argument l --stimulus none --urandom-open --madvise-dontneed --regular-inode-rdev --readonly-image-times --backup-service unverified-ack --trace-library-activation --instructions 3000000 --timeout-us 45000000 --report artifacts/execution/package-h-backup-historical-l.json
.\venv\Scripts\python.exe -m unittest discover -s tests -v
```

## Verification and remaining work

All **253 tests pass** in `artifacts/tests/package-h-backup-guard-suite.txt`. New constructed fixtures exercise the actual ARM ioctl stop, unchanged request/guest return state, explicit historical-policy labeling, no swallowed payload error, host memory bounds/permissions/provenance, and the isolated ARM window's call, fault, unexpected-control-flow and budget outcomes.

`package-h-backup-comparisons.json` records report hashes and exact status, instruction count, response count, boundary and final-instruction comparisons. The repeated strict `l` run matches; the explicit historical run matches E0028 at **2,226,764 instructions / 197 responses / syscall 128**; the default no-response probe remains **1,183 instructions**.

Next work is to identify the original backup request handler, registration semantics and required persistent state, then continue original startup with verified replies. Kernel driver registration, LIRO firmware state, runtime `/etc`, entropy and display submission remain unresolved. A smaller strict instruction count exposes a real dependency rather than losing an established camera capability. See [Experiment 0007](../experiments/0007-backup-service-and-liro.md). The regenerated chart remains a research checklist, not firmware-rendered pixels.
