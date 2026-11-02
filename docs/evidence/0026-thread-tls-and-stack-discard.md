# Evidence Record 0026: Hardware TLS Context Switching and Guarded Stack Discard

## Result and scope

The application-stage stack/context concern in E0025 has a concrete cause: `GuestThreads.restore_context` updated the software TLS slot and the model's value but **did not update hardware TPIDRURO** (`CP15 c13,c0,3`). Original pthread instructions read that register directly. A worker therefore used the main thread's TLS/unwind state, allowing its execution to return onto the main stack while the harness still labeled it as a worker.

The corrected scheduler restores both representations. With an additional explicit private-anonymous `MADV_DONTNEED` contract, `im.elf a` completes all four worker lifecycles and reaches its main event loop without the earlier futex retry loop or diagnostic main-stack stop. This remains a bounded process experiment: no framebuffer transaction or camera UI is produced, and component log markers do not establish plugin initialization.

## Identities and diagnostic controls

Firmware identities are unchanged from E0025:

- `im.elf`: `866729eb0bc1e6f5aba04d8bf8e45491985afe89a078ccb106a1ce2476865225`.
- `ld-linux.so.3`: `7c215cee6c4175079d69cb1433c6be90189e793f6e44f068ed6ac97621dd7a2c`.
- `libpthread-2.11.2.so`: `938387093567f5721bdeafa5bf68275d3a8705c8c6536745358e229af27fcab8`.
- `libc-2.11.2.so`: `bceb5cfb7769b54bf9c9d178b8a5f4579531c0f60e673cbcae872a8c7a3508fb`.
- Kernel: `12eeec829407595e28265f7d0db3b88c56f63a9f0fdd725c9c53c66a49643707`.

The original static filesystem, experimental kernel/process identity, deterministic inputs and existing IPC assumptions remain. No camera is accessed, no firmware input is changed, and no entropy bytes are supplied.

```powershell
.\venv\Scripts\python.exe -m tools.research.experiment_ui_boot --argument a --stimulus none --urandom-open --stop-worker-main-stack --instructions 3000000 --timeout-us 60000000 --report artifacts/execution/package-h-worker-stack-boundary.json
.\venv\Scripts\python.exe -m tools.research.experiment_ui_boot --argument a --stimulus none --urandom-open --stop-worker-main-stack --instructions 5000000 --timeout-us 60000000 --report artifacts/execution/package-h-tls-fixed-a.json
.\venv\Scripts\python.exe -m tools.research.experiment_ui_boot --argument a --stimulus none --urandom-open --madvise-dontneed --stop-worker-main-stack --instructions 5000000 --timeout-us 60000000 --report artifacts/execution/package-h-tls-madvise-a.json
.\venv\Scripts\python.exe -m tools.research.experiment_ui_boot --argument a --stimulus none --urandom-open --madvise-dontneed --stop-worker-main-stack --trace-library-activation --instructions 3000000 --timeout-us 60000000 --report artifacts/execution/package-h-tls-activation-trace.json
```

The first command records the **pre-fix configuration**; rerunning it after the correction reaches the new syscall boundary instead. Historical reports are preserved, not overwritten to hide the change.

`--stop-worker-main-stack` is an optional diagnostic boundary: it stops before the next instruction when a scheduled worker's SP enters the initial main-stack mapping. It neither rewrites SP nor claims that every possible clone program must use disjoint stacks. These runs use the separate NPTL child stacks observed in their clone arguments. The optional library trace observes arguments and results at original `im.elf` call sites; it does not replace `dlopen`.

## Original instructions identify the TLS consumer

Before the fix, the diagnostic stops at 2,296,240 instructions with TID 1001 (`THREAD_INFRA0`) still active and SP in the main stack. The instruction tail includes an original libc unwind/restore sequence, followed by the first instruction at the restored main-stack context.

Original `libpthread` code at linked offset `0xab90` executes:

```text
mrc p15, 0, r4, c13, c0, 3
sub.w r4, r4, #0x4c0
```

It then accesses per-thread state through that result. Updating only `0xffff0ff0` cannot satisfy this direct hardware-register read. `GuestThreads.restore_context` now delegates to `GuestKuser.set_tls` when available; that method restores hardware TPIDRURO, the software slot and model value. Its standalone path also updates the hardware register. The guest's own TLS and unwind structures are not patched.

The generic ARM Linux relationship is also documented in [Linux ARM TLS handling](https://raw.githubusercontent.com/torvalds/linux/master/arch/arm/include/asm/tls.h). That source supports the architectural contract; the local original pthread instructions establish the consumer in this firmware. It is not proof that Sony's complete kernel equals current upstream Linux.

Constructed tests execute an actual ARM `MRC` across main → child → main switches. They verify each thread sees its own pointer, the software slot matches, and helper-page protections are retained. A separate check exercises the actual `GuestKuser.set_tls` method without requiring proprietary instruction bytes.

## New boundary: original stack discard

With corrected TLS and the default no-response madvise policy, `im.elf a` stops at **2,298,610 instructions**, syscall **220**, advice **4**, during original infrastructure-thread cleanup. It has supplied 213 earlier responses. The request is:

```text
madvise(0x50480000, 0x7fa000, MADV_DONTNEED)
```

That range lies in the original guest's eight-MiB anonymous private stack allocation and excludes its retained upper stack/TLS area. The report confirms hardware TPIDRURO, software slot, model TLS and the current worker's TLS are all `0x50c7f920` at this boundary. No main-stack diagnostic fired.

The optional `--madvise-dontneed` contract implements only advice 4 on fully known private anonymous pages. It validates the complete range before mutation; rejects file, shared, device, initial/unclassified and unmapped pages; checks alignment/overflow; rounds length to pages; preserves mappings and permissions; and clears provenance labels for bytes legitimately replaced by known zero-filled memory. Device emulation storage is explicitly tagged separately even when implemented using underlying anonymous memory.

The [Linux madvise contract](https://man7.org/linux/man-pages/man2/madvise.2.html) defines subsequent private-anonymous accesses as zero-filled after successful `MADV_DONTNEED`. This process model uses eager zeroing to implement that visible content behavior. It does not model physical page reclamation, resident-memory accounting, timing, general advice modes, or file/shared discard semantics. Unknown ranges stop explicitly rather than returning invented success or partially modifying memory.

## Application-stage observations after both changes

- The five-million-instruction `a` run exhausts its bound in the event loop, with **21,259** supplied syscall responses; it is not application success.
- `THREAD_INFRA0`, `THREAD_INFRA1`, `THREAD_INFRA2`, and `THREAD_APP` are all terminated; main is running on its own TLS. Four original stack-discard requests were serviced, each for `0x7fa000` bytes. No initial-main-stack diagnostic fired.
- The three-million-instruction activation trace reaches the same loop with **4,546** responses. It records `dlopen("gui.so", 0x101)` returning **zero**, not a usable library handle.
- Original linker opens for `//lib/gui.so` and `//usr/lib/gui.so` return snapshot `ENOENT`. `/usr/local/lib/libVssApp.so` also returns snapshot `ENOENT`. Both the namespace manifest and a fresh hash-checked ext2 directory walk lack `gui.so`; `viewUnified2.so` exists. This does not establish runtime camera absence or authorize creating an alias between them.
- Begin/end markers for `appFw.so`, `libVssApp.so`, and `gui.so` remain insufficient evidence that those components initialized. Display transactions remain zero.

## Historical correction and remaining work

E0019–E0025 reports that use cooperative thread switches retain their value as observations of their recorded implementation, but claims of faithful NPTL context or normal camera startup past those switches must account for this TLS defect. In particular, E0025's `i` run had a worker active with main marked runnable; its deeper linker result must be reassessed under corrected TLS. The old reports and instruction counts are preserved as historical configurations, not required outcomes to recover by restoring incorrect thread state.

Remaining dependencies include the corrected `i` startup path, original subsystem load/IPC outcomes, identified runtime `/etc` and entropy state, and verified display geometry/submission. No missing library is invented, no failed load is turned into success, and no host-rendered camera UI is introduced. Floating-point and other architectural thread state beyond the exercised TLS/general-register subset still require their own checks before broader thread-fidelity claims.


## Verification completed so far

All **232 tests pass** (`artifacts/tests/package-h-thread-tls-suite.txt`). This includes actual ARM TLS reads across switches, optional/default madvise syscall behavior, range/ownership/provenance checks and the prior suite. The mmap ABI fixture's encoded shift was independently decoded as 24 bits (`0xe1a01c01`) even though its comment intended 12; it now uses `0xe1a01601` and asserts the mapped length is exactly 4096. This fixes its excess allocation and intermittent timing failure without increasing timeouts or weakening assertions.

Fresh no-response, brk, uname, files and mmap runs match their historical status, instruction count, response count and boundary exactly: 1,183; 2,222; 3,091; 5,078; and 56,230 instructions respectively. Comparisons are preserved in `artifacts/execution/package-h-tls-early-baselines.json`. Threaded deep baselines are superseded by the TLS correction, not forced to match incorrect state.

The first corrected `i` run, with a per-instruction stack diagnostic and a 240-second timeout, stops as **timeout** at 41,023,544 instructions while resolving symbols, with 471 responses and zero framebuffer transactions (`package-h-tls-corrected-i.json`). It is retained separately. A repeat omits that diagnostic overhead while preserving corrected TLS, the no-injection argv, instruction budget and entropy guard; its outcome is recorded below.

`status_a6400.png` is regenerated as a research-status chart. Its plugin-initialization count is corrected to zero demonstrated entries: opening dependencies or printing component markers is not successful plugin initialization. The chart is not firmware-rendered camera output. The bounded protocol is [Experiment 0004](../experiments/0004-thread-tls-and-stack-discard.md).

### Corrected `i` repeat

The repeat in `artifacts/execution/package-h-tls-corrected-i-complete.json` reaches **41,782,794 instructions**, with **473 supplied syscall responses**, then stops explicitly as `unsupported_filesystem` at `entropy_state_not_supplied`: original code requests four bytes from `/dev/urandom`, and zero bytes are supplied. Original `libObj.so` and dependency opens are observed, but no successful display initialization or framebuffer transaction is demonstrated. Hardware TPIDRURO, software slot, kuser model and the scheduled worker's TLS agree at this boundary. This reassesses the old `i` result under corrected thread state without inventing entropy or boot messages.

Reproduction:

```powershell
.\venv\Scripts\python.exe -u -m tools.research.experiment_ui_boot --argument i --stimulus none --urandom-open --madvise-dontneed --trace-library-activation --instructions 45000000 --timeout-us 240000000 --report artifacts/execution/package-h-tls-corrected-i-complete.json
```
