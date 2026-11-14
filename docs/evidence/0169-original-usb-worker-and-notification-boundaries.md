# E0169 — Original Main Loop and Final Notification Path

Date: 2026-11-08. Offline continuation of E0168; no camera access and no changes to the production C module.

`tools/research/probe_uvc_ptp_worker.py` executes the original Thumb entry 0x10175, `UsbControl::Main` 0x112c5, `ProcessMsg` 0x10ed5, the callback registration prefix, the body of the registered callback up to the message builder, and `EventListner` up to handing off to the UFW service. Source: a6400 `libUsbControl.so` SHA-256 `70cd5742fde9eea78c60905e4015531b4c3ab2668d2cb85c934531f451f1211f`.

## Main Loop

The original entry calls `Init` and then `Main` with the same object. Original `Main` uses `MsgReceiver` at `this+0x70`, receives the source and `ObjMsg`, and synchronously calls `ProcessMsg`. Upon return, it destroys and deletes the message before the next receive. `ProcessMsg` on fixture category `0x6103` and message ID `0xa2000` calls `SetCmpTarget` and `DispatchEvent`, and then returns 0. Exit ID `0xffff0000` returns -1, with final message cleanup and exiting `Main`.

The test executes two consecutive messages and then exit. It verifies the sequence `receive → target → dispatch → destructor → delete` before the next receive. Original `Main`/`ProcessMsg` decisions were not replaced. Receive, `ObjMsg` getters, `Init`, `SetCmpTarget`, `DispatchEvent`, destructor, and delete are explicit service replacements. FSM callbacks were not executed; this is not proof that all configuration changes physically arrive through a single thread.

## Registration and Notification

The original `doInitialize` prefix `0x131c1..0x131d8` passes arguments to `osal_reg_msg_queue_cb`:

| Argument | Value in Original Code/Fixture |
|---|---|
| r0 | 0x00e942cd |
| r1 | wrapper+0x20 |
| r2 | original Thumb callback 0x131a5 |
| r3 | 0 |

It stops before the remaining initialization. Actual registration, interpretation of all OSAL arguments, and the callback thread are not proven.

Original callback `0x131a5` loads the first two words of the received message and forwards them to the builder at `0x13055`. On explicit message `{1, -5}`, `r0=1` and `r1=-5` were verified at the boundary before the builder. The builder was not executed in this test, so `ObjMsg` construction, successful sending, and freeing of the input message are not proven.

Separately, original `UsbIfWrapper::EventListner` `0x12d29` adjusts `this` to `wrapper+8` and passes the same `ObjMsg` to `UFW::MsgSender::SendEvt` via Thumb PLT entry `0x9808`. At that boundary the test stops: successful sending, target queue, and delivery are not assumed.

This registered OSAL notification callback is **not the same** as the direct USB completion callback `0x12de5` from E0168. The first path creates a notification for the application; the second sends status to the temporary queue on which `doSyncStartStop` waits. Their exact thread distribution has not yet been confirmed by execution.

## Resolver and Checks

`arm_plt.py` now also recognizes the exact Thumb interworking prefix `bx pc; mov r8,r8` (bytes `78 47 c0 46`) and links its entry with the proven ARM stub and ELF relocation. This correctly resolves tail calls that previously had no result, without guessing spacing.

**18 new checks pass**; manifest is `artifacts/analysis/uvc-ptp-worker-e0169/manifest.json`, log `artifacts/uvc-ptp-worker-e0169.log`. After the resolver change, the 22 completion checks of E0168 and 35 queue checks of E0166 also pass again. Physical access was not used. The last full project regression remains 605 passing tests from E0164; the production module was not modified.

## Next Boundary

Trace the original OSAL callback dispatcher for `osal_reg_msg_queue_cb` and its relationship to the USB completion caller. Transaction protection requires verifiable executor identities and callback duration, rather than concluding that every notification is automatically serialized by the main loop. The shared module remains unloaded and physically untested; concurrent sensor UVC and PTP remain incomplete.
