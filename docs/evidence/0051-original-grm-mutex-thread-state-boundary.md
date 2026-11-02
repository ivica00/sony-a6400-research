# Evidence 0051: Original callback locking requires kernel thread state

## Result

Original captured `ma_user_sync_cb` is now a separate bounded research entry. Its first external call is **_mutex_lock**, with mutex address **0x5f3fc4a4** and original captured branch target **0x603c6998**. A separately selected kernel-prefix experiment records **41 original instruction events**, stopping on the first unsupplied kernel-stack-state read:

- PC **0x603c6e5c**, original `ldr r2,[r3,#4]`.
- Read address **0x08002004**, four bytes, derived from constructed SP aligned down to8KiB.
- No packet output or `gl_common` retain-count write occurs; reply sentinels remain unchanged.

The terminal load is included in the instruction trace but its value is not accepted. No lock acquisition/completion, scheduler identity, owner task, callback reply or IPC success is supplied. This is a newly explicit prerequisite, not GUI advancement. Main process remains E0034.

## Source-backed mutex and original kernel path

Same checked WBI/GRM/kernel inputs and selected page-table root as E0045. Every permitted kernel window is compared byte-for-byte between captured WBI memory and preserved kernel bytes before execution. The exact callback BL relocation is decoded and required to target0x603c6998; other imports continue to stop.

The mutex's first24 captured bytes are:

```
00000000 00000000 5f3fc4ac 5f3fc4ac 00000000 00000000
```

These raw words alone do **not** establish an acquired/released mutex or permission to bypass the kernel implementation. Original path:

| Window | Observed original call/operation |
| --- | --- |
| `0x603c6998..0x603c69ac` | wrapper calls0x603c60ec |
| `0x603c60ec..0x603c610c` | prepares arguments and calls0x603c5f98 |
| `0x603c5f98..0x603c5fc8` | saves frame/local state and calls0x603c6ed8 |
| `0x603c6ed8..0x603c6eec` | wrapper calls0x603c6e40 |
| `0x603c6e40..0x603c6e60` | derives aligned stack base, then reads its +4 state word |

The following disassembly contains state updates and atomic instructions, but they are outside this executed prefix. A kernel field name/semantics is not inferred solely from offset4. Actual current thread/stack state and scheduling effects must be established before extending this execution or modeling successful locking.

## Explicit policies and provenance guard

```
python -m tools.research.wbi_grm_consumer --operation callback --report-dir artifacts/execution/NEW_DIRECTORY
python -m tools.research.wbi_grm_consumer --operation callback --mutex-prefix --report-dir artifacts/execution/NEW_PREFIX_DIRECTORY
```

Plain callback stops before the mutex import after5 executed-prefix instructions. `--mutex-prefix` requires callback mode and permits only the source-verified windows above. It tracks each byte written by original instructions to the constructed stack, and rejects reads of unwritten bytes even though host backing is zero-filled. Thus the missing kernel state is not silently replaced with zero. The report records36 stack-store ranges and the blocking read; there are zero non-stack stores.

Default lookup/open policies and producer `main(argv)` behavior are preserved. Lookup client regression still has original producer285 instructions and client6 instructions to the184-byte new boundary. There is no guest execution-backend change or process policy implementing this callback.

Retained reports: `artifacts/execution/wbi-grm-callback-first` (import boundary), `wbi-grm-mutex-prefix-guarded` / `wbi-grm-mutex-prefix-repeat` (byte-identical guarded reports), `wbi-mutex-client-regression` (E0050 behavior). Initial `wbi-grm-mutex-prefix` failed pre-execution validation because all module mutex call sites were counted; selecting the call within the actual callback body fixes that ambiguity without permitting other imports.

The original callback instruction evidence is already retained in E0046's hash-matched `plan-cec107b24672bfa5-0`; it was reused with local relocation/kernel-window checks, without another large analysis import.

## Additional captured object-reference scan

`wbi_grm_scan --reference-offset0` scans for the cached object pointer0x68a96220 rather than the embedded list link. It finds exactly two aligned references in all644 decoded WBI sections:

| Physical reference | Observation |
| --- | --- |
| `0x067609f0` | Existing allocator-trace-like record, with name data nearby |
| `0x088ffff4` | Words nearby include physical0x202e0000, size0x02000000 and object pointer0x68a96220 |

Report: `artifacts/analysis/wbi-grm-object-references/report.json`. Neither reference is established as the184-byte user-space client object. The latter also contains unrelated header/sentinel-looking values; its8KiB-aligned backing prefix is zero, not an identified kernel thread context. No such context is selected from this candidate, and no user-object constructor state is inferred from a matching pointer. Default offset20 scan and its six-node reciprocal check are retained.

## Validation and next work

Full suite **348 passing tests**, `artifacts/execution/wbi-grm-mutex-suite.txt`. Status image regenerated, visually checked; capability counts unchanged. Selected original pointer/code identities and repeated prefix boundary agree. No physical device operation occurs.

Next: establish the required kernel callback-thread context or a fully evidenced mutex contract before callback completion; independently trace the original user-space object constructor/lifetime after E0050's operator-new boundary. Do not set the aligned-stack word to zero, invent a task pointer, skip locking, or treat a raw captured pointer reference as an initialized user object.

