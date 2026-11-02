# Evidence Record 0025: Original Boot Launch Dispatch and Application-Stage Thread Boundary

## Result

The original `bootin.elf` event handler has now been executed in bounded windows up to its external-call boundaries. Events `0x940031` through `0x940037` select seven separate `im.elf` launch commands. Event `0x940038` returns the unsupported-event value `0xfffffc06` in this handler. These are process-launch requests, not evidence that injecting the same phase identifiers into one process recreates camera boot.

A process run with **`im.elf i` and no injected queue messages** reaches `libssp`'s guarded four-byte entropy read after **41,782,766 instructions**, with 473 supplied syscall responses and zero entropy bytes supplied. The `a` process reaches original application-thread diagnostic markers but stalls in a futex retry loop; it produces no framebuffer transactions. No camera UI or authentic full boot is demonstrated.

## Inputs and bounded methods

Preserved SHA-256 identities:

| Input | SHA-256 |
| --- | --- |
| `bootin.elf` | `44788cd57d3befcb5552006d73e7b5a3d92847a5710c084c696564673e09aad7` |
| `im.elf` | `866729eb0bc1e6f5aba04d8bf8e45491985afe89a078ccb106a1ce2476865225` |
| `ld-linux.so.3` | `7c215cee6c4175079d69cb1433c6be90189e793f6e44f068ed6ac97621dd7a2c` |

Filesystem/kernel identities are unchanged from E0024. The static image namespace, process-entry values and existing IPC/scheduler assumptions remain experimental. The supplied argument is supported by original bootin instructions; the process's full camera launch environment and prior stage state remain unknown.

```powershell
.\venv\Scripts\python.exe -m tools.research.boot_event_trace
.\venv\Scripts\python.exe -m tools.research.experiment_ui_boot --argument i --stimulus none --urandom-open --instructions 45000000 --timeout-us 240000000 --report artifacts/execution/package-h-argv-i.json
.\venv\Scripts\python.exe -m tools.research.experiment_ui_boot --argument a --stimulus none --urandom-open --instructions 3000000 --timeout-us 60000000 --report artifacts/execution/package-h-argv-a-futex-corrected.json
.\venv\Scripts\python.exe -m tools.research.experiment_ui_boot --argument a --stimulus none --urandom-open --watch-word 0x7feffd0c --instructions 3000000 --timeout-us 60000000 --report artifacts/execution/package-h-argv-a-stack-watch.json
```

`boot_event_trace` verifies the input hash, maps the original ELF using the production mapper, supplies a constructed message and stack, then starts the original Thumb handler at `0x98fd`. It stops **before** `system`'s PLT entry or the outgoing-message helper. No host command, child process or guest message is emitted. The independent cases establish dispatch behavior, not a normal event order or its prerequisites.

## Original dispatch observations

| Event | Original requested command | Executed original instructions before call boundary |
| --- | --- | --- |
| `0x940031` | `im.elf s &` | 12 |
| `0x940032` | `im.elf g &` | 14 |
| `0x940033` | `im.elf r &` | 18 |
| `0x940034` | `im.elf u &` | 21 |
| `0x940035` | `im.elf l &` | 24 |
| `0x940036` | `im.elf i &` | 27 |
| `0x940037` | `im.elf a &` | 30 |
| `0x940038` | No launch; normal return `0xfffffc06` | 53 |

Three additional original-handler cases reach the outgoing helper `0x8e18`:

- Incoming `0x940002` selects destination `0x94020a`, outgoing event `0x940001`, value 0.
- Incoming `0x9400f3` or `0x9400f4` selects destination `0x94016a`, preserves that event ID, and uses value 0.

A second bounded window starts at `0x8e37`, immediately after an explicitly assumed successful allocation. Original instructions construct a 16-byte body with a four-byte prefix. For the `0x9400f3` case the five words become `[0x94020a, 0x9400f3, 0, 0, 0]`, stopping at `0x8e48` before `osal_snd_msg`. The prefix is set by the original helper; its wider kernel meaning is not established by this window alone. This is more specific evidence than the earlier runner's 64-byte zero-filled injections, but does not justify replacing its whole sequence with a guessed boot scenario.

Correction to E0021/E0022: phase labels and static library names did not establish that all listed plugins initialized. In particular, `0x940038` is not recognized by the bounded bootin handler, and the observed phase commands describe distinct argument-selected processes. Prior reports remain historical experiments under their recorded assumptions.

## Argument-selected process observations

The runner now accepts repeatable `--argument` values and `--stimulus none`. The latter enqueues no messages. Existing defaults retain the earlier experiment.

- `i`: flags word at `0x14ee8` is observed as `0x200003`; the process opens `libObj.so` through its original startup path, without injected events, and reaches `read(4, 0x536a9188, 4)` at `0x5008b1c4`. `entropy_state_not_supplied` preserves the stop before any bytes. The run was captured before the futex errno correction described below; its report remains a record of that configuration.
- `a`: flags word is observed as `0x400003` in the corrected bounded run. Its `THREAD_APP` produces `094_a_thread`, `094_6`, `094_7`, and begin/end diagnostic markers naming `appFw.so`, `libVssApp.so`, and `gui.so`. There are only 13 successful opens (initial libraries and UIPC), with no corresponding new plugin file opens. Those markers do **not** establish executed plugin initialization or rendering.
- A 45-million-instruction `a` exploration under the earlier errno behavior exhausts its budget with 1,700,509 syscall responses; it is not success. Subsequent diagnostics use a smaller three-million-instruction bound. The large original report remains preserved; `package-h-argv-summary.json` provides compact summaries and report hashes.

## Futex correction and remaining context concern

The new path exposed a concrete error in `GuestThreads.handle_futex_wait`: mismatched values returned `0xffffffea` (`-EINVAL`, 22) while the comment and contract claimed `-EAGAIN`. It now returns **`0xfffffff5` (`-EAGAIN`, 11)**. The [Linux FUTEX_WAIT specification](https://man7.org/linux/man-pages/man2/FUTEX_WAIT.2const.html) requires an immediate EAGAIN on mismatch. The existing test expectation was corrected; a new check ensures mismatch neither alters the word nor blocks/queues the thread. This is an ABI correction, not a forced success response.

The correction alone does not resolve `a`'s retry loop. A three-million-instruction run still ends at its budget with 20,509 syscall responses. The passively watched word `0x7feffd0c` ends as `0x5032018c`. Its last observed CPU write occurs at interpreter PC `0x40007534`, instruction 2,492,220, with the harness reporting TID 1004 and SP `0x7feffd18`. Earlier uses include the parent-stack thread barrier. The source of this context/stack ownership inconsistency remains unproven; no word, register or control-flow patch is applied to bypass it. A passive watch records at most 128 writes and does not modify execution.

## Verification and next boundary

Constructed fixtures test normal return, unexpected control flow, instruction exhaustion and unmapped access in the bounded handler tool. The full suite is captured in `artifacts/tests/package-h-boot-producers-suite.txt`. E0024's first entropy-read baseline and the no-response baseline are rechecked separately after the ABI change; outcomes are appended below.

No identified runtime entropy pool or read transcript was found in the examined input inventory. This is not a claim about every preserved artifact or the physical camera. The `i` path still requires a justified entropy-state/replay contract. The `a` path requires thread/context and subsystem-execution verification. Correct phase delivery order, prior-process state, real IPC service responses, `/etc` state and display submission remain open. Increasing budgets, trusting marker strings or substituting random bytes would not establish a camera UI.


Verification completion: all **220 tests pass**, including the existing suite with its corrected futex errno expectation. An earlier suite run concurrent with a long probe hit the existing mmap fixture's timeout; the subsequent isolated full run passes without weakening that assertion. E0024's opted-in baseline still matches status, 41,955,226 instructions, 601 responses, boundary and final 32 instructions (`package-h-futex-comparison.json`); the default no-response probe remains at 1,183 instructions. The captured pre-correction `i` run contains no mismatched-futex response, so that specific errno correction was not exercised on its path. New status accounting counts seven bounded command-dispatch checks, not seven booted processes. The bounded protocol is [Experiment 0003](../experiments/0003-boot-dispatch-and-argv.md).
