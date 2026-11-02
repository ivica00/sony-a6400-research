# Evidence 0064: Original captured GLES open, kernel locks and ioctl queries

Date: 2026-10-24

## Result and scope

Original `sugilite_open` now executes through original kernel migration and
spinlock instructions to a genuine **return 0 after 437 instructions**, with
**21 non-stack stores**, in a separately selected package-WBI experiment.
Original code retains the captured device and owner entry, increasing each
reference count from 1 to 2. Both lock objects return byte-for-byte to their
initial state. No lock or open result is supplied by the host.

Original GLES ioctl queries also return through original kernel `__get_user_4`
and `__put_user_4`, including their address-limit failure paths. Original register
initialization now follows the captured cache callback and stops at its first
hardware write request, rather than at an unknown callback pointer.

**This is a captured-state kernel/driver experiment, not a new main-process
milestone.** The newly launched `im.elf` has not been bound to the captured task,
file ownership or address space. Its boundary remains E0063: opening
`/dev/dmpgles2` at 80,739,451 instructions. No descriptor or device success is
injected into that process. There is no GPU execution, IRQ completion, framebuffer
transaction or image output. SD/card state is untouched.

## Preserved inputs and verification

| Input | SHA-256 |
| --- | --- |
| packaged WBI `nflasha5` | `19a702b030306a32f4287131da314e5c89d66163997f0f9a23b0967981b0001b` |
| `grm_gles.ko` | `a8d1dbe8c66be365d32371b13f35a0e7d598c415c0ff17f2c8f544084ccc6882` |
| `vmlinux.bin` | `12eeec829407595e28265f7d0db3b88c56f63a9f0fdd725c9c53c66a49643707` |

The existing E0063 dependency plan and retained REA/Ghidra results identify the
module functions and field-access instructions; they were not rerun unnecessarily.
The new tools use original bytes and small targeted instruction decoding to
resolve captured relocations and kernel helper targets.

`tools.research.wbi_gles_state` searches an original non-relocated 20-byte open
prefix in preserved physical sections. Under explicitly selected page root
**PA 0x104000**, reverse page-table translation identifies module text at
**VA 0x5f400000**. All **5,124 non-relocated text bytes** match the preserved
module; **253 relocation words** are excluded, not accepted as source identity.
An ambiguous or mismatching mapping fails closed.

This selected root has the earlier original boot-instruction check; it is not
proof of an active TTBR, cold boot or current camera execution.

## Captured device, cache and ownership state

Captured original relocation slots identify:

- `outer_cache`: **0x604c92d0**; callback at `+0x1c`: **0x6011a5d0**.
- device pointer slot: `.bss+0x78`; captured device object: **0x696bbc00**.
- owner-list head: **0x5f4022d4**.
- reciprocal owner entry: **0x68abdda0**, TGID **152**, reference count **1**.

The device has open count 1, event status 0, suspend status 1, shared area
`0xb0a55000`, kind 2, register pointer `0xf1000000`, word at `+0x104` zero,
and BAR extent `0x4000`. These are read from the translated snapshot, not
invented reset values. Compiled initialization fields are cross-checked.

Original module lookup at `.text+0` returns `0x68abdda0` for TGID 152 in
**19 instructions**, and zero for absent control `0xffffffff` in **24**. It
does not allocate, retain or modify that list. A list hit does not authorize
attributing the record to a different process.

### Task/stack backlinks

An initial structural search using an assumed `task+4` stack field found no
candidates; that absence was not treated as a missing task. Original GLES wait
instructions at `.text+0xbb4..0xbbc` and `.text+0xc50..0xc58` demonstrate the
actual sequence: current `thread_info+0xc` -> task -> **task+8** -> thread_info
flags. Using this original field access yields **124 reciprocal task/stack
candidates** for owner group 152 in preserved memory.

Selected explicit control:

| Field | Value |
| --- | --- |
| task | `0x60a4a800` |
| reciprocal thread_info | `0x684a8000` |
| PID / TGID | 358 / 152 |
| thread_info flags / preempt count | 0 / 1 |
| user address limit | `0x5f000000` |
| migration depth at task+0xa8 | 0 |

The bytes `grm_dn_vdf_if` also occur in this task record at `+0x5c8`; that
association is a naming observation, not independent proof of the current CPU
task. Kernel `get_task_comm`/`set_task_comm` export lookup did not yield an
unambiguous exported accessor, so no stronger name-layout claim is made.

## Original open and lock execution

`tools.research.wbi_gles_execute` rechecks original module text, relocation
anchors and kernel helper bytes on every load, without depending on generated
reports. It uses explicitly selected captured task state and a constructed
inode/file ABI fixture; the inode's device pointer comes from captured memory.
The research call frame is placed inside that task's reciprocal thread-info
region. Captured header bytes are known, while unwritten frame/padding reads
remain guarded.

The staged prefix executes original `__migrate_disable` at **0x6012c0ac** and
stops before `rt_spin_lock` after **17 instructions**. Captured preempt count 1
selects the original early return; the host does not supply migration success.

The explicit kernel-following experiment then permits source-verified kernel
instructions and narrowly declared state mutations:

- the two original 28-byte GLES spinlock objects, sizes verified from ELF symbols;
- selected task's four-byte migration-depth field;
- device open-count/event-status words;
- selected existing owner's four-byte reference count;
- constructed file's `private_data` and original call-frame stores.

Snapshot pages permit writes only where those selected ranges require them;
every store is checked against the ranges. Every executed kernel instruction is
compared with the preserved kernel. Unbound imports, unknown coprocessor/system
register consumption, other snapshot writes and unsupported control flow stop
explicitly. No kernel scheduler, allocator or hardware success is substituted.

Observed 437-instruction result:

| Object | Before | After |
| --- | --- | --- |
| file private pointer | unwritten fixture field | `0x696bbc00`, stored by original open |
| device open count | 1 | 2 |
| selected owner references | 1 | 2 |
| both spinlock objects | captured unlocked bytes | identical to initial bytes |
| selected task migration depth | 0 | 0 |
| source package/WBI bytes | original | unchanged |

The 21 non-stack stores include file initialization, transient lock operations
and the two retained counts. Mutations exist only in that CPU instance. Because
the device was already open and the owner existed, this does **not** execute
the first-open DMA preparation or new-owner allocation paths.

## Original queries and copy failures

Captured call relocations uniquely identify kernel `__put_user_4` at
**0x602593d4** and `__get_user_4` at **0x60258140**; their bytes match the
preserved kernel. Research ioctl calls use a constructed file pointing at the
captured device and declared user buffers/address limits. The handlers and kernel
helpers own the returned words and error codes.

| Command | Input word where used | Original output word |
| --- | --- | --- |
| `0x80048200` | — | `2` |
| `0x80048205` | — | `0` (device word `+0x104`) |
| `0x80048206` | — | `0x4000` |
| `0x80048207` | — | `0x200` |
| `0x8004820a` | — | `1` |
| `0x80048263` | — | `0` |
| `0xc0048201` | 0 / 1 | `0` / `0x4000` |
| `0xc0048202` | 0 / 1 | `0x80000000` / `0xf1000000` |

The above calls return zero through original instructions. Original
`0x40048204` returns zero without touching the buffer; this no-op is not evidence
of a submitted or completed GPU job. Unknown command 0 returns `-515` without
touching the buffer. Reducing the declared address limit to one byte below the
four-byte buffer end yields original `-14` for both input and output-copy paths,
without a result-buffer write. Reads into unsupplied buffer padding stop rather
than accepting zero-filled backing memory.

## Hardware and main-process boundaries

Register preparation executes **28 original instructions** through the captured
cache callback. That callback loads captured controller pointer `0xf8002000`
and attempts a four-byte zero write to **0xf8002730**, PC **0x6011a5e8**.
The experiment stops **before accepting that hardware operation**. No GLES
register write or hardware response is supplied. Thus the old unknown callback
slot is resolved, but cache-controller/DMA semantics remain open.

Separately, an ioctl `0xc0048203` control with input `0x40000000` reaches **59
instructions** before reading the unknown current-task word at constructed
thread_info `+0xc` (`0x0800000c`), PC **0x5f400bfc**. This control intentionally
has no captured task binding; it remains a guarded missing-context test. It
does not claim job submission or completion. Binding a captured task for the
open experiment does not automatically bind new user-process requests.

The main process was not rerun unchanged: these additions are isolated research
execution tools and tests, not a new `/dev/dmpgles2` runtime policy. E0063's
80,739,451-instruction main-process boundary and zero framebuffer transactions
remain the latest main result. A correct next integration must establish the
new process's kernel task/address-space/resource ownership, or a separately
declared and verified complete captured-process continuation. Reusing TGID 152's
successful open as a reply for a newly created process is not established.

## Artifacts and reproduction

```powershell
.\venv\Scripts\python.exe -m tools.research.wbi_gles_state --report-dir artifacts/analysis/NEW_GLES_STATE
.\venv\Scripts\python.exe -m tools.research.wbi_gles_execute --report-dir artifacts/analysis/NEW_GLES_EXECUTION
.\venv\Scripts\python.exe -m unittest discover -s tests -v
```

Report directories must be new and remain under `artifacts`; source inputs are
hash-checked. Each bounded execution has a 1,000-instruction / one-second limit,
declared SVC-mode control `0x13`, and provisional Cortex-A9 model. These are
research execution controls, not verified camera CPU/reset state.

- Identity/backlink report: `artifacts/analysis/wbi-gles-threadinfo-backlinks/report.json`,
  SHA-256 `b31d95b12da38639bafcd1084f54112219f9c3b50f0183e15f5fa38dc57af968`.
- Final execution report: `artifacts/analysis/wbi-gles-verified-open-final/report.json`,
  SHA-256 `bbae5e0c4435443ea2a9e5e270c672a15d030917d79d28d1ef0e4bdb8865bb44`.
- Earlier failed/partial scans and staged query/open reports are retained in
  separate `artifacts/analysis/wbi-gles-*` directories, with their stated scopes.
- Full regression result: **423 tests passed** in
  `artifacts/execution/wbi-gles-verified-open-suite.txt`.

The 12 new checks cover original query/helper results, indexed reads, read/write
address-limit failures, output padding, unknown/no-op requests, actual owner
lookup, staged migration, complete captured open, lock restoration, retain
mutations, immutable source memory, task alignment and unsupported hardware/task
reads. They do not replace physical display validation or the main-process gate.
