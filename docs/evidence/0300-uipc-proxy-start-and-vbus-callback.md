# E0300 — Original UIPC proxy threads start and consume a VBUS notification

Date: 2026-11-10. Offline original-firmware execution only; no camera access.
**No emulator GUI frame.** OSD A/B remain unmapped. E0298's physical OSD
capture remains ground truth, not an emulator output.

## Finding and implementation

The old shared UIPC mapping was empty at its option header. In the retained
340M checkpoint, `libosal_uipc`'s `uipc_opt` points to `0x50330000`, whose first
32 bytes are zero. `uconf+32` counts 63 registrations, but `uconf+24` is zero:
no proxy array was allocated. The original `create_proxy_thread` path compares
the registration count against `[uipc_opt+0x10]`; zero prevents proxy creation.
This explains the previous `woken=[]` VBUS experiment's missing consumer.

Hash-checked REA/Ghidra 12.1.4 and original instructions establish:

* `osal_uipc.ko::k_uipc_init` writes option words
  `{0x100000,0x20000,0x40000,0x8000,4}`, byte `+0x15=1`, byte `+0x16=0`.
  ELF `.text` offset `0x207c` corresponds to provider entry `0x12168`;
  provider stores at `0x121cc..0x12204` confirm the values. Other bytes are
  **not** inferred from the decompiler.
* `libosal_uipc.so` proxy entry ELF `0x2030` / provider `0x12030` waits through
  ioctl `0x8000000d`, then executes the returned callback with
  `r0=message`, `r1=user_data`. The host never calls the callback.
* `__k_4u_wait_cb` returns `{callback,user_data,message,proxy_index}` through
  the second pointer in the ioctl argument. Index must be below four. The
  next wait completes the previous callback before receiving another. The
  transport binds each proxy index to its guest TID and rejects another TID.
* The actual kernel priority queries accept policies 0..5, with maxima
  `{0,159,159,0,-22,0}` and minima `{0,1,1,0,-22,0}`; other values return
  `-EINVAL`. In particular, the camera's RT maximum is **159**, not an
  assumed desktop value. Sixteen original ARM executions confirm these tables.

New CLI opt-in: `--uipc-pool-options kernel-e0300`. The default remains
`legacy-empty`. It initializes only the verified stores, services the two
priority queries, blocks/schedules empty callback waits, and delivers a bounded
async callback tuple. It rejects sync registrations, multiple callbacks on one
queue, null callbacks, and completion of a delivered callback. No RT-pool
allocator, sync-callback protocol, kernel boot or complete UIPC implementation
is claimed. Callback completion is deliberately still a boundary.

Old checkpoints cannot gain missed startup retroactively: requesting the new
policy with a legacy checkpoint is rejected. New-policy checkpoints persist it.
UIPC scripted injection now writes the authentic allocation header as well as
the body; the earlier injection allocated an address without writing its header.
The observed-gps filesystem policy also answers **F_OK only** for the two
observed directories; permission queries and other runtime paths remain unknown.

## Inputs, queries and receipts

* `libosal_uipc.so` SHA-256
  `b6ded35add9582413b401cf4db78ec2c9a201b632e78c2731d6bbb379249b3eb`.
* Kernel SHA-256
  `12eeec829407595e28265f7d0db3b88c56f63a9f0fdd725c9c53c66a49643707`.
* Every successful REA batch retains the complete inventoried module identity,
  profile, query and instruction evidence in its manifest. Batches under
  `artifacts/analysis/e0300-uipc-*`: registration, start, proxy, kernel-wait,
  pool, init-exact, kernel-init and finish. Exact queries include
  `osal_reg_msg_queue_cb`, `u_osal_reg_msg_queue_cb`, provider `0x11b18`,
  `0x12030`, `0x122e8`, `0x1210c`, `__k_4u_wait_cb`, `__k_4u_connect`,
  `__k_uipc_cdev_mmap`, `k_uipc_init`, `finish_callback`, `__k_user_msg_cb`.
* Failed Windows-child REA launch and unprivileged WSL access remain retained;
  the established native WSL route succeeded with execution approval. An
  ambiguous `u_uipc_init` query failed; the exact-address batch replaces it.
* `artifacts/analysis/e0300-original-sched-probe.py` and `.json` retain the
  exact hash-checked ARM experiment; `e0300-sched-priority.txt` retains bytes.

## Bounded replay

Exact repeatable command/policies are retained in
`artifacts/analysis/e0300-run-i.py` (run from root with
`python -m artifacts.analysis.e0300-run-i`). It uses phase **i**, no boot-event
stimuli, deterministic experimental entropy, existing preset/GRM/media and
device policies, captured E0044 pools, observed-gps, and the display observer.
These existing experimental assumptions are retained, not newly validated.
Each slice has a 60-second limit; no timeout or budget exit is success.

1. Preliminary phase **s** runs established the priority-query boundary at
   3,124,466 instructions and the original proxy wait at 3,211,571. Phase s
   later waits for a phase command; it is not the GUI startup experiment.
2. Fresh phase **i** reached 62,650,718 instructions (timeout), then
   82,446,392 (F_OK `/setting` boundary). Receipts/checkpoints `e0300-i`, `i2`.
3. With the observed directory existence query serviced, the no-input replay
   reached **91,139,021**, 31 threads, and stopped at a pending message for a
   sync-registered callback on queue `0x009c015b`, flags 1. Receipt `e0300-i3`.
4. Separate resume from `boot-e0300-i2.ckpt`:

   ```powershell
   python -m artifacts.analysis.e0300-run-i --load-checkpoint artifacts/checkpoints/boot-e0300-i2.ckpt --instructions 30000000 --uipc-inject-queue 0x12002da --uipc-inject-payload 00000000010000000000000000000000 --save-checkpoint artifacts/checkpoints/boot-e0300-vbus.ckpt --report artifacts/execution/e0300-vbus.json
   ```

   The verified buspwr body wakes `[1001,1002,1003,1008]`. Proxy 0 receives
   callback `0x5b783dcd`, user_data `0x22078`, message `0x5033296c` (handle
   4103, queue `0x012002da`). Original firmware returns from that callback,
   issuing `FREE_MSG` for the same message and queue, then calls WAIT_CB again.
   At **83,341,353**, the model stops with
   `uipc_callback_completion_not_implemented`, PC `0x5029b07c`, ioctl
   `0x8000000d`, proxy 0. This is actual guest callback execution, not proof
   of a USB connection/FSM transition. The injected notification is early in
   initialization; no physical timing equivalence is claimed.

   The final identity-checked replay (`e0300-vbus-identity-checked.json` and
   matching log) reproduced the same delivery and completion boundary.

## Validation and next boundary

Focused checks: 57 tests pass, including untouched header bytes, geometry
rejection, empty wait, tuple delivery, failed output copy without dequeue,
sync rejection, and completion boundary. Full-suite receipt is
`artifacts/analysis/e0300-venv-full-suite-identity-checked.log`:
**782 tests OK**, 21.595 s. The earlier verified run also passed (20.857 s).
Earlier failed test receipts remain: temporary-directory access restrictions
and an updated injection test initially missing the richer writer contract.

Next decode queue state and `finish_callback` ownership/refcounts, then the
sync-registered queue `0x009c015b`. The original VBUS callback itself frees its
message: do not simply decrement/free it again or drop the completion guard.
`CONNECT` still returns the historical zero fourth word, although original
kernel allocates a dynamic callback-control queue; that contract also remains
incomplete. Preserve these limits before further USB/OSD progress. SMAPH-S30
rasterization remains an independent blocked contract. No OSD/UI/rendering
compatibility claim, camera mutation or new physical experiment.
