# Research utilities

Firmware extraction and static analysis tools are preserved here, with root compatibility entry points. Camera tools interact with USB hardware and should be invoked deliberately. No camera write or service-mode operation is part of repository validation.

Bundled upstream dependencies remain at the project root to preserve their existing environments and provenance.

Static process-startup workflow (run as modules from the project root):

```powershell
.\venv\Scripts\python.exe -m tools.research.elf_inventory
.\venv\Scripts\python.exe -m tools.research.startup_trace
.\venv\Scripts\python.exe -m tools.research.guest_layout
```

The last command reads original image metadata through the bundled fwtool parser. It records symlinks in JSON without creating host links or modifying firmware. Reports under `artifacts/inventory/` are static evidence and candidate plans, not a guest execution environment.

After generating those reports, run `.\venv\Scripts\python.exe -m tools.research.probe_interpreter` for the original-interpreter first-boundary experiment. It checks input hashes and stops before answering any guest kernel request. See [E0003](../../docs/evidence/0003-original-interpreter-boundary.md) for assumptions and results.

Add `--syscalls brk` to enable only the guest heap contract and stop at the next unsupported request. This writes a separate `interpreter-brk.json` report. See [E0004](../../docs/evidence/0004-guest-brk-contract.md).

Add `--syscalls brk-uname` for guarded kernel-image identity as well. This requires `baseline.json` and writes `interpreter-uname.json`. Runtime-unknown identity reads stop execution. The next filesystem request remains unsupported. See [E0005](../../docs/evidence/0005-guarded-kernel-identity.md).

Add `--syscalls files` for read-only image file contracts. This also requires the generated baseline and filesystem manifests. It writes `interpreter-files.json` and currently stops with exit code 2 at unsupported `stat64` success for `/lib`. See [E0006](../../docs/evidence/0006-read-only-guest-filesystem.md).
