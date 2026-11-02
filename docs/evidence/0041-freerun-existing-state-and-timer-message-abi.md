# Evidence 0041: Preserved freerun state and timer message ABI

## Original freerun setup

Targeted literal/reference analysis of the preserved kernel identifies a small setup routine at **0x6011fdec**, with literals naming **0xf2403100** and **0x1031**. It reads the existing control word before deciding whether to program the timer. This is a reference-derived identity, not a recovered function symbol or proof that the routine ran during the selected application experiment.

`tools.research.freerun_boot_trace` executes the original window with a guarded register observation page:

- **No supplied control state:** stops at **PC 0x6011fdf0**, four-byte read **0xf2403100**, before any stores. Mapped host zeroes are not accepted as hardware state.
- **Explicit control 0:** 12 original instructions return normally and request stores `0` to `0xf2403100`, `0x11` to `0xf2403104`, then `0x1031` to `0xf2403100`.
- **Explicit control 0x1031:** six original instructions return normally with **no stores**. The existing selected mode is preserved.

The two values are constructed branch controls, not observed reset state. No counter value, register effect, timer frequency, elapsed time or hardware reset success is supplied. In particular, this code does not establish a fresh zero epoch: a matching existing mode bypasses programming entirely.

Kernel SHA-256 remains **12eeec829407595e28265f7d0db3b88c56f63a9f0fdd725c9c53c66a49643707**, checked against the preserved baseline. Two runs yield identical `artifacts/execution/freerun-boot-trace-first.json` and `freerun-boot-trace.json`, SHA-256 **f07fe67176bb2fa6d7de35c447e5aeca1e34932aad95536c42520a960854b04a**. Execution is bounded to 100 instructions and one second; unsupported accesses/control flow and faults remain explicit stops.

## Timer registration and body layout

The planner and targeted native-WSL REA batches resolve these original functions:

1. `utimer_open_interface` registers **0x00910042** with `utimer_kif_counter`; it also registers alarm and delay queues 0x00910040/41, with original rollback on registration failure.
2. `osal_reg_sync_msg_queue_cb` stores the client callback/private value and installs `__default_cb` as its transport wrapper.
3. `osal_snd_sync_direct` checks the message pointer/length and prepares a payload after the **16-byte** transport area. Its direct and copied-body paths remain subject to live callback/queue/lock/allocation state, which has not been executed in this experiment.
4. `__default_cb` unlocks the queue, invokes the stored client callback on the payload, then locks again and returns transport status zero. The transport's wrapper pointer and the wrapper's +12 adjustment lead to the original caller's **message +16** body (or its copied equivalent).
5. `utimer_kif_counter` reads the body's first word: **0 selects `utimer_get_syscnt`; 1 selects `utimer_get_schedclock`; other values store -1024** at body +4. Successful selected reads store a 64-bit result at body +8 and status zero at body +4.

Thus the previously observed 32-byte DMM request has total length at offset 0, selector at **16**, status at **20**, counter at **24**. Its zero selector selects the system counter. A transport success alone is not a populated counter response. These are static ABI/registration findings checked against retained original instruction listings, **not successful execution of OSAL registration, locks or either clock getter**. No timer response is added to the guest.

## Scripted workflow evidence

Plans under `artifacts/analysis/`: `utimer-dispatch-registration`, `utimer-counter-dispatch`, `utimer-sync-transport`, `utimer-default-callback`. Generated function/target lists were inspected before their WSL batches were executed.

Successful retained batches under `artifacts/tools/rea/`:

- `plan-572a96ff76a7b038-0`: timer registration, two new queries.
- `plan-8257c2de1805fc97-0`: dispatcher plus both getters, **four retained results reused and two new queries**.
- `plan-4aa2796539527487-0`: transport and registration wrapper, four new queries.
- `plan-1a3932b9340ad891-0`: default callback, two new queries.

Each manifest retains target SHA-256, completed status and unchanged-source checks. `utimer.ko` identity is the E0040 input; OSAL module identity is recorded in its batch manifests. Ghidra prototypes, including parameter widths, are not silently treated as authoritative ABI declarations. Queue values above are original caller constants; body layout comes from the connected pointer operations.

## Checks and remaining boundary

All **331 tests pass** (`artifacts/execution/freerun-boot-suite.txt`), including three new constructed checks for unknown control rejection, programming only under an explicit different-mode control, and preserving the already selected mode without stores. No device/camera/update operation occurred.

```powershell
.\venv\Scripts\python.exe -m tools.research.freerun_boot_trace
.\venv\Scripts\python.exe -m unittest discover -s tests -v
```

Remaining timer work: identify initial control/counter state and register/clock effects, then establish original scheduling/registration state before supplying counter replies. Logging still independently requires identified `/setting/ulogio.bin` or its producer, on the unpreserved setting partition. The application remains at E0034's **42,465,243 instructions**, allocator assertion/SIGABRT request, without stream mmap, fb0 request or original GUI. Status visualization is refreshed without increasing capability counts.
