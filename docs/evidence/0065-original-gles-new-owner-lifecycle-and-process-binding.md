# Evidence 0065: Original GLES new-owner lifecycle and process binding

Date: 2026-10-24

## Result

In an isolated package-WBI CPU instance, original `sugilite_open` creates a
previously absent GLES owner for observed PID/TGID 97. Original kernel allocation,
zeroing, waitqueue initialization, locking and linked-list insertion execute;
there is no host allocator reply or copied owner-152 success. In the same CPU
instance, an original ioctl query and release then return successfully:

| Operation | Original instructions | Return |
| --- | ---: | ---: |
| open | 1107 | 0 |
| ioctl 0x80048200 | 38 | 0 (output 2) |
| release | 1320 | 0 |

Total: 2465 instructions. Device retain count and owner-list links return to
their original values. The selected cache array's available count returns to
66; the selected free-object slot is restored. Release also invokes original
`complete_all` on the remaining owner's completion, changing its done word from
0 to 0x7fffffff. Consequently this experiment does not claim that every byte of
captured state is unchanged. The preserved input remains immutable.

## Inputs and bounded execution

The same hash-checked `nflasha5`, original `grm_gles.ko`, kernel, selected page
root PA 0x104000 and relocation comparisons as E0064 are used. Complete identities
are retained in `artifacts/analysis/wbi-gles-new-owner-verified-v2/report.json`.
Report SHA-256: `92e41e9fbe38758e291a1383826e29f4151c9a2a7bbe1f05e9f07eff2110c3e0`.
Selection of this root does not establish active hardware TTBR state.

The selected reciprocal task has thread_info 0x60a1c000, PID/TGID 97, CPU 0 and
addr_limit 0x5f000000. The original allocator is 0x601b0c4c. Original module
instructions select cache 0x69400080 via `malloc_sizes + 12`. CPU 0's nonempty
array is 0x6940f000, initially available 66, limit 120, batch 60; the selected
64-byte object is 0x68ad25a0. Original code requests a 60-byte owner, zeros the
cache object and initializes its fields. An earlier actual PID 1 / CPU 2 control
instead reaches an unsupplied NULL per-CPU array; it is retained in
`artifacts/analysis/wbi-gles-new-owner-cpu-lock/report.json`, not replaced with
allocator success.

Mutation permissions are confined to source-identified lock, migration-depth,
allocator metadata, selected object, list and empty completion ranges. A peer
completion with waiters is rejected because scheduler wakeup is not established.
Each executed kernel instruction is compared with preserved source bytes;
unknown memory, stack padding, system-register contracts and MMIO stop execution.
No GPU/cache hardware reply, service return or rendering command is supplied.
The default E0064 experiment remains available unchanged.

Reproduce from the project root:

```powershell
.\venv\Scripts\python.exe -m tools.research.wbi_gles_execute --new-owner-thread-info 0x60a1c000 --report-dir artifacts/analysis/gles-owner-reproduction
```

Use a fresh output directory. The lifecycle has a cumulative instruction budget,
including between calls; exhausting it cannot accidentally start an unlimited run.

## Main-process incompatibility

The main process cannot inherit this captured owner's success. The E0063 report
has current modeled TID 1003, modeled TGID 1000 and initial stack
0x7fe00000..0x7ff00000. Both identity fields differ from the selected task, and
the stack lies outside that task's observed addr_limit. A historical anonymous
mapping at 0x5ef60000 of length 0x800000 also crosses that limit. Mapping records
are request history, not a reconstructed live address space; the audit labels
them accordingly. These observations do not establish a universal TASK_SIZE.

`KernelTaskObservation` validates reciprocal task pointers and rejects identity,
range and unsupported zero-user-limit bindings. It grants no driver success.
`gles_process_binding_audit` retains the comparisons and input/report hashes in
`artifacts/analysis/gles-main-binding-audit/report.json`. The process probe now
stops `/dev/dmpgles2` open explicitly with
`gles_kernel_process_binding_not_supplied`, before creating a descriptor or
changing r0. The modeled thread group is recorded independently of current TID.
Audit report SHA-256:
`a3f6486a856d8f504b174719a398a8e1616e85141f4be4a95cddd868f54a690a`.

Next establish original task/address-space creation and driver ownership for the
main process, then original cache/DMA and GPU submission/completion contracts.
Changing PIDs, bypassing addr_limit or inventing a kernel task would not resolve
these prerequisites. No framebuffer pixels or authentic GUI image are claimed.

## Validation

All **431 tests pass** (14.089 seconds). The complete regression suite is retained in
`artifacts/execution/gles-new-owner-release-verified-suite.txt`. Checks cover original
new-owner allocation/release, restoration of allocator/list state, actual peer
completion, cumulative budget exhaustion, default refusal of absent ownership,
identity/range mismatches and process-open refusal without a kernel binding.
The 150M-budget main-process rerun stops at **80,739,451 instructions**, with
`unsupported_gles_contract` / `gles_kernel_process_binding_not_supplied`,
caller TID 1003 / TGID 1000, before any GLES descriptor is created. The report is
`artifacts/execution/ui-boot-gles-binding-150m.json`, SHA-256
`c8c25d31989eecb02ce0e3dd258c0a402b8e0ee0b1c036a723a2f553919b6402`.
This reproduces E0063's instruction count with a more precise boundary; it is not
150M instructions executed or a main-process graphics advance. SD remains read-only.
