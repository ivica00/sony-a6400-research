# E0166 — Original USB Message Queue and Separate Direct Stop

Date: 2026-11-08. No camera access or production module change. Continuation of E0165.

## Proven Launch Path

New `tools/research/probe_uvc_ptp_service_queue.py` executes original Thumb bodies in original a6400 `libInfraUsbCmn.so`, SHA-256 `5338bafbb545ebc223fac15c9253a41ac9fe49c01fe32c73af40c3fb50eec0a6`.

Original `CUsbSvc::start_gadget` (`0x9ed9`) builds a 32-byte message and submits it via `CUsb::request` (`0x848b`). Confirmed message fields: `object+0`, `callback+8`, `user+12`, byte `argument+16`, `completion+20`. Callback is original `CUsbSvc::createGadget` at `0xbbc5`, obtained via real ELF relocation; not a fabricated test callback.

`CUsb::request` locks `this+0x40`, executes original `que_push` (`0x8433`), signals `this+0x58`, and unlocks. Ring uses `buffer+0x14`, byte `head+0x18`, `tail+0x19`, and `capacity+0x1a`; slot is 32 bytes. Original push copies all 32 bytes and increments tail with wraparound. Full queue returns 12 without modifying contents.

Original `CUsb::proc_service` (`0x8529`) under the same lock calls original `que_pop` (`0x8501`), increments head, and unlocks **before** calling the callback from `slot+8`. At the callback boundary `r0` points to the real slot in the fixture ring, and the recorded state of the mutex stub is unlocked.

This is proof of original instruction sequence and queue operation on explicit data. It is not proof of real thread scheduling, worker thread count, or ability to safely inject a MOD message into a physically active service. `createGadget` was not executed; the experiment stops there.

## Stop Does Not Have to Go Through That Queue

Original public `CUsbSvc::stop` (`0x9e01`) checks handle at `this+0x9c` (gadget) or `this+0xa0` (host) and state `this+0x98`. For gadget handle and state 3 it sets state 4 and **directly** calls `stop_gadget` via PLT `0x81ac`. In this body there is no queue request and no worker-thread identity check. The experiment checks arguments, preserved queue indices, wrong handle (11), and wrong state (6), and stops before `stop_gadget`.

This does not prove that a real external caller runs concurrently with the worker. It proves that the queue implementation and mutex `this+0x40` alone are insufficient as a universal contract for all entry points. Moreover, the mutex is unlocked before the `createGadget` callback. Holding it across our transaction would mean changing the original contract, with unproven consequences.

## Exact PLT Resolution

The probe computes GOT for nine used targets from the actual ARM add/add/ldr instructions of the PLT entry and links it with `.rel.plt`. It does not assume fixed entry stride. This automatically verifies `request`, `que_push/pop`, `pthread lock/unlock`, `condition signal`, `getpid`, `cancellation`, and `stop_gadget`. E0165's wrong label `port_init` for `0x7b10` is corrected in that document itself: the real target is `request`.

## Checks

**35 checks pass**: 9 PLT targets, original message, queue and worker, empty/full queue and wraparound, and direct stop and negative inputs. Results and hash of the probe itself are in `artifacts/analysis/uvc-ptp-service-queue-e0166/manifest.json`; run log is `artifacts/analysis/uvc-ptp-service-queue-e0166.log`.

Pthread, logging, `getpid`, and cancellation are explicit service stubs; GC/object, ring, stack, and indices are explicit fixture data. Guard rejects unexpected execution and writes outside allowed fixture regions. No hardware service, module loader, original `createGadget`, or `stop_gadget` was executed.

Production code was not changed so all project tests were not repeated; previous 605 passing tests from E0164 remain the latest full regression. E0164 candidate remains `physical_test_ready:false`. Next must trace external callers of `CUsbSvc::stop/start` and their lifetimes, or prove shared protection of all kernel entry points. Sensor UVC stream with simultaneous PTP control remains unconfirmed on camera.
