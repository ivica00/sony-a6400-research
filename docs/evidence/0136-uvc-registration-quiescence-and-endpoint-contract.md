# E0136: UVC registration, quiescence lifecycle and endpoint contract

Date: 2026-11-07. Work resolved the safe driver registration lifecycle, transmission quiescence/stop contract upon removal, bulk endpoint descriptor construction, and gadgetcore request ABI. Physical UVC remains off. Normal feature 0x23 debugger PID 1793 remains operational.

## Safe dual registration and rollback

Reference `usbg_video.ko` constructs a single compound function driver descriptor specifying two interfaces (`interface_count = 2`, control interface 0 and streaming interface 1). In contrast, the a6400 kernel gadget core (`usb_gadgetcore_register_driver` at `0x602b8610`) requires a 1-to-1 mapping between registered function driver descriptors and individual USB interface numbers (`descriptor.interface_number`), expecting callbacks at offsets `+0x10` (START) and `+0x14` (STOP).

To bridge this architectural divergence safely without kernel binary patching:
1. The bridge allocates and manages two shadow descriptors (`shadow[0]` for interface 0, `shadow[1]` for interface 1).
2. `a6400_uvc_bridge_register(b, reg_fn, unreg_fn)` provides transactional registration:
   - Registers `shadow[0]` via `reg_fn`.
   - Attempts registration of `shadow[1]` via `reg_fn`.
   - If secondary registration fails, it automatically unregisters `shadow[0]` via `unreg_fn` (atomic rollback), leaving the bridge inactive (`b->active == 0`) and returning the error.
   - Upon successful dual registration, it activates the bridge (`registered_mask == 3`).

## Proactive transmission quiescence and safe teardown

A critical kernel finding on the a6400: `usb_gadgetcore_unregister_driver` (`0x602b8560`) solely unlinks the driver node from the gadget core list and invokes `kfree()`. It does **not** invoke the driver's `STOP` callback (`+0x14`), does not cancel queued endpoint transfers, and does not flush hardware DMA buffers.

If a driver is removed or closed while streaming is active (`b->started == 1`):
- Direct unregistration without stopping causes DMA transfers to continue into freed or unmapped buffers, causing a kernel panic or memory corruption.
- Furthermore, `a6400_uvc_bridge_retire()` rejects retirement with `-EBUSY` (`-16`) if `b->started` or `b->in_flight` is non-zero.

To prevent this hardware hazard:
- `a6400_uvc_bridge_quiesce(b)` inspects `b->started`. If active, it explicitly invokes the reference driver's `STOP` callback (`core_cb_stop` at reference descriptor offset `+0x1c`), which dequeues and frees pending endpoint requests, invokes `usbg_cmn_clear_ep_list`, and clears `b->started` to 0.
- `a6400_uvc_bridge_unregister(b, unreg_fn)` guarantees the complete shutdown sequence:
  1. Executes `a6400_uvc_bridge_quiesce(b)` to stop the stream and drain in-flight calls.
  2. Unregisters `shadow[1]` via `unreg_fn`.
  3. Unregisters `shadow[0]` via `unreg_fn`.
  4. Calls `a6400_uvc_bridge_retire(b, 0)`, returning the context cleanly to unallocated state.

Unicorn test controls in `tools.research.uvc_callback_bridge_probe` verify:
- Registration success on both shadows.
- Rollback unregistering `shadow[0]` when `shadow[1]` registration fails.
- Idle quiescence as a safe no-op.
- Active quiescence triggering `core_cb_stop` with argument translation.
- Automatic quiescence during unregister before releasing descriptors.
All 42 contract controls pass.

## Bulk endpoint descriptor construction (USB2 profile)

Investigation of reference endpoint configuration in `libInfraUsbCmn.so` (offsets `0x1ccc0` and `0x1ccd4`) and kernel endpoint enablement (`ep_ctrl_enable_ep`, a6400 `0x602ba6ec`, ZV-E10 `0x602bec90`):
- Both high-speed (HS) and full-speed (FS) reference streaming endpoints specify transfer type `bmAttributes = 2` (BULK transfer).
- Constructed USB wire descriptors match standard bulk endpoint format (`07 05 81 02 ...`).
- 20 original endpoint construction controls in `tools.research.uvc_endpoint_descriptor_probe` pass across both kernels.

## Request queueing and completion ABI

Tracing of kernel request wrappers (`gcore_queue` at a6400 `0x602b8004` and `gcore_complete` at a6400 `0x602b8084`):
- Both a6400 and ZV-E10 share identical 52-byte request structures and completion callbacks.
- 30 original request-ABI controls in `tools.research.uvc_request_abi_probe` pass.

## Verification results

- Offline compiled ARM bridge candidate: `artifacts/native/uvc-callback-bridge-checked-e0136/uvc_callback_bridge.elf` (no unresolved externals).
- 42 bridge/dispatch contract controls pass in `artifacts/analysis/uvc-bridge-checked-controls-e0136`.
- 20 bulk endpoint controls pass in `artifacts/analysis/uvc-bulk-endpoint-e0136`.
- 30 request ABI controls pass in `artifacts/analysis/uvc-request-abi-e0136`.
- All 599 emulator unittest tests pass in 16.946s.
- Manifests set `camera_access: false`, `deployable: false`. Physical camera writes and module installations remain prohibited pending integration.
