# E0156: Original Setup Pointer Through Bridge and Modified UVC Handler

Date: 2026-11-08. Continuation of E0155. No physical loading.

## Request Lifetime Decision

Instead of wiring a copying setup adapter, a separate, precisely bounded MOD of the reference UVC driver was chosen that directly understands wire interfaces 1/2. This avoids creating a new setup buffer or extra pointer that native EP0 completion could use after expiry. The original setup pointer, request contents, and existing native lifetime remain unchanged. This does not prove native EP0 completion/teardown in a shared physical configuration.

## Two Explicit MOD Instructions

Original reference `usbg_video.ko` is pinned to SHA-256 `d385a051bf01b0e5ea37412623ae85cfe3cda76ab0d11e61d111994ca9fbf4fb`.

| Offset in `.text` | Original | MOD | Effect |
|---|---|---|---|
| 116c | `7e20e0e3`, `mvn r2,#7e` | `7d20e0e3`, `mvn r2,#7d` | video request tag 81->82 |
| 13e8 | `ff5015e2`, `ands r5,r5,#ff` | `015055e2`, `subs r5,r5,#1` | VC wire1->native0, VS wire2->native1 |

The classifier instruction executes only after the original check that `wIndex` high-byte/entity ID is zero. Thus `SUBS` does not alter the original entity path; for `entity!=0` the original branch goes to `16f8` before the MOD instruction. PTP wire0 must be rejected by the bridge before the UVC callback. Calling the MOD handler directly for unsupported interfaces is not a valid contract.

Builder verifies the entire original hash and both original instructions. In the final object exactly three bytes differ, file offsets `11a0`, `141c`, and `141e`. No other changes, including relocations.

`artifacts/native/uvc-ptp-adapter-e0156/reference-wire12-endpoint82.offline.o` SHA-256 `e2244462fa4c604689113603953781b4ee25569b054d8bdc29b36d1af89c2da8`. This is an offline object, not a complete/deployable UVC+PTP module.

## Bridge Fix

`tools/native_camera/uvc_callback_bridge.c` now for interface-recipient compares only `setup[4]`, i.e., `wIndex` low byte, with the shadow interface number. `setup[5]` is the UVC entity ID and must not cause false rejection. Original a6400 dispatcher also uses `ldrb` at `request+4`, at `602ba010`. Bridge does not overwrite the setup pointer or setup data. Other registration, callback snapshot, in-flight, and START/STOP logic remain unchanged.

Registration of shadow interfaces 1/2 already works through the existing descriptor ABI when reference interfaces vector contains 1/2. Offline checks verified class requests for both interfaces/entity 0 and 2, rejection of PTP wire0 and wrong shadow, START of VS, ignoring foreign VC STOP, and quiesce on unregister. Registration/unregistration in those checks use explicit recorders, not physical gadgetcore ack.

## Original Path, Not Just Record Callback

Extended `tools.research.uvc_callback_bridge_probe` accepts optional `--reference-wire-object`. It verifies MOD hash against manifest, original SHA, and equality of all bytes except the three listed.

Four separate CPU runs execute:

1. Original a6400 dispatcher slice at `602ba05c`.
2. Compiled MOD bridge and its original request pointer.
3. Real MOD reference `core_cb_class` at `.text+17b0`.
4. Real reference classifier at `+1390` with the listed MOD instruction.

VC wire1/entity0 stops at `+1410`; VS wire2/entity0 at `+16a4`; entity2 for both stops at `+16f8`. In all four cases helper `r6` is the original setup pointer, and all eight request bytes remain identical to the original request.

Stopping occurs before allocator, queueing, and completion. No fabricated successful return of native callback; these four runs intentionally do not finish the callback. Earlier lifecycle/rollback tests still have clearly marked record callbacks. They do not represent a physical shared lifecycle.

## Results

- 65 ARM adapter/MOD checks pass; includes the earlier 55 and ten new ones.
- 91 bridge/dispatch checks pass; includes earlier checks and twenty checks of four real reference-entry paths.
- Full project suite: 605 tests pass in 19.125 s.

Artifacts:

- `artifacts/native/uvc-ptp-adapter-e0156/manifest.json`.
- `artifacts/native/uvc-callback-bridge-e0156/manifest.json`.
- `artifacts/analysis/uvc-callback-reference-e0156-final/manifest.json`.

## Boundary and Next Steps

The copying adapter from E0155 remains isolated and is not needed for this direct wire approach. The extra lifetime problem it would have introduced is resolved, but native control transfer and full shared-device lifecycle are not yet finished. Still needed: wire descriptor bundle, reference MOD, endpoint82 selector, and shadow1/2 into shared gadgetcore registration alongside original PTP driver, confirm EP0 full reply/IAD/FS and rollback, and bind native JPEG producer and DMA ownership. Original PTP driver was not replaced with host code.

In this step there was no camera access or writes to SD/persistent storage. Physical UVC+PTP enumeration, sensor UVC frame transfer, and real PTP settings changes remain unconfirmed.
