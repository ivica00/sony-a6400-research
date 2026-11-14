# E0161: Ownership During Descriptor Table Installation and Restoration

Date: 2026-11-08. Continuation of E0160. No camera access.

## Implementation

`tools/native_camera/uvc_ptp_descriptor_lease.{c,h}` introduces a separate ownership transaction. Before calling, the caller must stop the controller, retire callbacks, hold topology locked, and prepare the appropriate native address-limit contract. Those preconditions are neither implemented nor proven by this helper. The helper itself does not disable USB, register drivers, or claim quiescence.

Install accepts the 12-byte original save argument ABI and two ops pointers (native save/free in future integration). It accepts only the intended single HS/FS candidate without extra/dual policy additions, verifies its own tree, and rejects repeated active installation.

Before the native save call it saves the original PC Remote root, flags, and bytes 84/85. Then it sets `gc+6c` to zero: the original save failure branch thus cannot reach the previous PC Remote table via `free_desc_tbl`. After save it separately records the installed root. Success requires a non-null native copy distinct from the old table and caller template, plus a passing E0160 validator.

On native error with null root it restores the original root/flags/mode and returns the original error. Success with null root returns `-5` and also restores the snapshot. Unexpected alias, invalid copy, or error leaving an unexpected root transitions to `QUARANTINED`. Source object remains retained; no blind free call.

Restore works only for `INSTALLED` state and the exact recorded active root. It also checks the identity of the free operation. It frees only the new native copy, confirms native free zeroed `gc+6c`, then restores the original root/flags/mode and clears the ownership record. Repeating restore after success is idempotent. Foreign root returns `-116` without freeing. A free that violates the null-root contract transitions to quarantine and is not repeated; this avoids a possible double free.

`a6400_descriptor_source_releasable` returns 1 only for `EMPTY` state. Thus a future module can prevent freeing the template while a transaction is active or unknown. Module-unload protection is not yet wired to this result.

## Verification Boundaries and Real Original Entry

`tools.research.build_uvc_ptp_descriptor_lease` builds a real standalone ARM ELF together with the descriptor validator. Source/header/ELF hashes and input template/copy fixture hashes are pinned in manifests.

In transaction tests save/free are EXPLICIT RECORD DOUBLES. They install a verified independent descriptor fixture and return configured errors; these are not native allocator or physical controller acknowledgements. The compiled ownership helper and validator actually execute, and writes are guarded.

73 checks pass. They cover two consecutive cycles, error/null-success recovery, protection of the old table, held-source state, double install, repeated restore, stale/source aliases, invalid copy, foreign active root, changed free callback, and invalid free contract.

An additional run enters from the real ownership helper into ORIGINAL a6400 `save_desc_tbl` `602bc550`. Execution stops at `602bc598` BEFORE `__copy_from_user`, with no fabricated copy/allocator return. At that point the original save argument pointer, saved old root in ownership object, `gc+6c=0`, and `INSTALLING` state are confirmed. Full native save does not return and installation is not declared successful. Thread address-limit and memory are explicit offline fixtures.

## Artifacts

- `artifacts/native/uvc-ptp-lease-input-e0161/`: 573 previous descriptor checks, owned template, and independent copy fixture with hashes.
- `artifacts/native/uvc-ptp-descriptor-lease-e0161/manifest.json`: 73 ownership checks and all source/ELF/input hashes.
- `descriptor-lease.elf`: offline ARM executable artifact, NOT a kernel module.

```
python -m tools.research.build_uvc_ptp_descriptor_lease --input-dir artifacts/native/uvc-ptp-lease-input-e0161 --output-dir artifacts/native/uvc-ptp-descriptor-lease-e0161
```

## Integration Next Steps

Must wire real controller quiesce and lock, native save/free wrapper with proper address limit, UVC shadow registration, EP0 hook, and reconnect. Only then is it permitted to claim the ownership helper restores physical PC Remote. Must prove source/module lifetime while native callbacks are active and recovery from quarantine; no automatic physical recovery code in this step.

Original PTP driver has not yet been enabled/disabled in a shared physical configuration. Native JPEG/DMM producer and sensor UVC video remain open. Full project runtime was not changed so the previous 605 tests were not repeated. No camera uploads, modules, feeder processes, USB changes, SD, or persistent writes. Simultaneous physical UVC+PTP remains unconfirmed.
