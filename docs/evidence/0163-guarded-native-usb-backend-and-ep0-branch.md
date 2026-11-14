# E0163: Native USB Backend and Real EP0 Branch in Offline Check

Date: 2026-11-08. Continuation of E0162. No physical camera access.

## Implemented Kernel Wrappers

`tools/native_camera/uvc_ptp_native_backend.{c,h}` provides the real ops table implementation for the shared session, bound to the verified a6400 kernel:

| Operation | Native path |
|---|---|
| Disconnect | gadget ops `pullup(0)`, `setup_disconnect` `602b9464` |
| Controller stop/state | `usb_gcw_stop` `602bd834`, `get_gcw_state` `602bd450` |
| Controller start | `usb_gcw_start` `602bd7f8` |
| EP0 enable/setup | `602b05fc`, `602b2b40`, native EP0 descriptor `604e4e24` |
| Driver register/unregister | `602b8610` / `602b8560` |
| Descriptor save/free | `602bc550` / `602bc3e4` |

Backend reads actual singleton `gc` from `6051b17c`, verifies selected original instructions of critical functions and the four original descriptor `BL` sites. This is a partial live instruction guard, not a full live kernel hash. Offline test still SHA-verifies the entire original kernel.

Caller must still ensure serialization of native USB mode changes and lifetime of source/session/backend objects. Backend is not a finished kernel module, does not install its own unload guard, and was not run on camera alone.

## Stop and Restore

`setup_disconnect` has no reliable C integer status; wrapper treats it as void. After it, requires `config74=0`, zero owned descriptor/bridge users, `STOP` completed, and no active driver record. Native registry walk is bounded to 64 nodes. Then confirms stop return and GCW state 1.

Resume checks stopped state and mode 0/1, confirms start result and new state 2/3, validates EP0 out/in owner pointers, executes two native enable calls with result check, arms SETUP and `pullup(1)`, then active flag. Void arm call is not proof of physical TRB processing or Windows attach.

Register/unregister are allowed only for UVC config 1 / interface 1/2 while controller is stopped. Temporarily clears flags bit 2 and fully restores previous value. Registry is read before/after operations: register must add one exact descriptor, unregister must remove it. Original PTP 0 is not passed to those operations.

Native unregister RETURNS `int`, specifically 0 or -16 in original code. Wrapper preserves it. Bridge previously ignored unregister result, so session ops was extended with `check_error` callback: native guard/unregister/free error holds session/source before descriptor free or declaring releasable state.

Save wrapper sets real current-thread address limit to `KERNEL_DS` and restores it even on native error. Requires `gc+6c=0`, preparing the ownership lease. Free allows only the recorded installed copy, distinct from original and source. No blind freeing of an unknown table.

## EP0 Wiring

Four original `BL` sites: `958c` (device), `95ac` (qualifier), `95cc` (config/other), `95e0` (string), all in the `602bxxxx` page. Backend pre-verifies all original instructions and signed ARM `BL` range/alignment before any write. Changes/readback tracked via hook mask. Executes native instruction-cache flush with ARM barriers. Unbind checks all sites before restoring; rejects unknown foreign patch instead of overwriting it and verifies original readback.

Dispatch verifies `gc` and exact native EP0 request buffer, tracks its in-flight users, and calls unified descriptor reply with capacity 512. That capacity is tied to original `g_bind` allocation at `602b844c..847c`: cache allocation, explicit 512-byte trace argument, and storing into `request[0]`. No assumption is made from JPEG or video DMA capacity.

## What Is Verified vs Test Double

Builder now has `--native-backend`, links backend with session/bridge/lease/adapter/descriptor code, and places offline ELF at `5f800000` for realistic `BL` reach. No unresolved imports.

Compiled backend ACTUALLY executes fingerprint checks, target pointer calls, flag/address-limit guards, registry readback, branch calculation, write/restore/readback of four instructions, and session integration.

In offline memory, patched `BL` instruction at `602b95cc` -> compiled `descriptor_dispatch` -> unified reply -> ORIGINAL Sony serializer/memcpy -> return to `602b95d0` with valid 173-byte output actually executed. Those serializers were not replaced with a host implementation.

However, kernel/hardware effects of target operations (pullup, stop/state, native register/save/free/EP0 enable/setup, and cache-flush effect) are EXPLICIT boundary DOUBLES. They mimic registry/allocation results to test the MOD wrapper, not proving real allocator, MMIO, cache, or physical USB acknowledgement. Writability of the kernel hook page is also an explicit offline fixture. Execution does not end with physical enumeration or sensor stream.

Tests include registering only UVC while preserving PTP sentinel, exact `KERNEL_DS` and its restore, hidden original root, conflict/code guards, no-partial-write bind preflight, real patched-BL output, restoring all four original instructions, freeing only the new copy, save error rollback, and unregister error that blocks descriptor free. 147 cumulative checks pass (previous 120 and 27 native-backend checks). Full project runtime was not changed; previous 605 tests from E0162 were not repeated after these isolated ARM checks.

Artifacts: `artifacts/native/uvc-ptp-native-backend-e0163/manifest.json`, offline linked ELF, and `artifacts/uvc-ptp-native-backend-e0163-build.log`. Original contracts: `artifacts/analysis/uvc-native-backend-contract-e0163/original-native-contract.txt`.

```
python -m tools.research.build_uvc_ptp_descriptor_lease --native-backend --input-dir artifacts/native/uvc-ptp-lease-input-e0161 --output-dir artifacts/native/uvc-ptp-native-backend-e0163
```

## Remaining

Must build real kernel-module entry/exit and lifetime protection, link exact verified reference wire 1/2 + endpoint 82 MOD and allocator, solve serialization with native USB mode worker, freshly verify target, and execute a bounded physical register/EP0/restore experiment before transferring frames. Host Sony UVC detection with PID 0caa and native JPEG/DMM producer remain open.

No camera uploads, modules, feeder processes, USB mode change, SD, or persistent writes. This is not proof of physical UVC+PTP operation.
