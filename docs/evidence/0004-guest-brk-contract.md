# E0004 — Guest heap contract and the next original-linker boundary

Date: 2026-10-18. Scope: bounded Linux process research; camera behavior remains unvalidated.

## Result

With the new optional `brk` policy, the original interpreter executes **2,222 instructions**, servicing one `brk(0)` request and then stopping at syscall **122 (`uname`)**. Its ARM `svc #0` instruction is at `0x40010f78`. No response is supplied for `uname`.

The initial guest program break is **`0x15000`**, derived by rounding the greatest application PT_LOAD memory end to a page boundary. The original query returns that state. The observed run does not grow the heap: initial and final breaks both remain `0x15000`. Growth/shrink/failure behavior is checked with constructed tests, not claimed as exercised by this firmware run.

The original no-response policy remains the default. It still stops at the first `brk(0)` after **1,183 instructions**. Separate report names keep the experiments distinct.

## Contract and declared policy

`src/a6400/execution/guest_brk.py` implements a guest-only program break. It maps RW, non-executable pages on growth, unmaps released pages on shrink, preserves retained partial pages, and checks collisions with mapped ranges plus a guard page. Failed requests leave the break unchanged. No guest request is passed to a host syscall.

The initial break is page-aligned and ASLR is disabled. A **64 MiB growth ceiling** is an explicit experiment resource policy, not a recovered camera RLIMIT_DATA. Sony's kernel configuration, resource accounting and overcommit behavior remain unverified. This is a bounded contract rather than the whole Linux memory manager.

Every serviced request records its arguments, prior/returned break, reason, and mapping change. Unknown syscalls remain explicit boundaries. Neither a failed allocation nor an unknown request gets a generic success response.

## Commands and reports

```powershell
# Default: stop before every kernel response
.\venv\Scripts\python.exe -m tools.research.probe_interpreter

# Implement only the declared guest brk contract
.\venv\Scripts\python.exe -m tools.research.probe_interpreter --syscalls brk

# Independent repeat report
.\venv\Scripts\python.exe -m tools.research.probe_interpreter --syscalls brk --report artifacts/execution/interpreter-brk-repeat.json

.\venv\Scripts\python.exe -m unittest discover -s tests -v
```

Default reports: `artifacts/execution/interpreter-probe.json` for no responses and `artifacts/execution/interpreter-brk.json` for the heap contract. Both identify the syscall policy and report how many requests were serviced. Exit code zero means a planned unsupported syscall boundary was reached, not that the application ran successfully.

## Checks and limits

Tests cover query-only behavior, page allocation and permissions, retained bytes, released-page zeroing on regrowth, lower/upper limits, collisions/guard space, allocation/unmap failure, initial-break derivation and integration with original-code execution. The constructed integration fixture verifies that the `brk` response is consumed before a different unsupported syscall stops execution.

This step does not implement `uname`, filesystem access, dynamic-library mapping, TLS syscalls, devices, IPC, or scheduling. The original application has not reached its entry point. Firmware, camera state, and physical camera connections were not modified.

## Primary references and next experiment

The contract follows the observable program-break behavior in [Linux v3.0 `mm/mmap.c`](https://github.com/torvalds/linux/blob/v3.0/mm/mmap.c), with the explicit resource limits above. Syscall identity comes from the [ARM syscall table](https://github.com/torvalds/linux/blob/v3.0/arch/arm/include/asm/unistd.h).

Next: inspect how this linker consumes `uname`, identify which returned fields can be grounded in the extracted kernel, and keep unknown fields explicit. Any configurable research identity must be labeled as an assumption. Do not copy the Windows host identity or fabricate camera data to bypass the boundary.
