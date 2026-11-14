# E0160: Native Descriptor Copy and Ownership

Date: 2026-11-08. Continuation of E0159. No physical camera access.

## Important Integration Contract Correction

Original Sony `save_desc_tbl` at `602bc550` does not set `gc+6c` to the caller's descriptor object. It allocates an 88-byte root, copies it, and then deep-copies speed/config groups and language/string objects. At `602bc5c8` it immediately writes the new root into `gc+6c`. An example of nested ownership write is `602bc770`: the new language array pointer goes into native `root+3c`.

Therefore the `gc->desc_tbl == caller_template` requirement from the earlier shared reply candidate would not be valid after a real `save_desc_tbl`. E0159 proved offline serialization over a caller-owned object, not compatibility with a native installed copy. This step explicitly fixes that boundary.

## Implementation

Added `a6400_uvc_ptp_validate_native_copy(template, native_table)`:

- Template must be a previously verified, stable HS/FS/string tree.
- Native root may be at a different address; speed fields/counts and contents of VID/PID/bcdDevice/string-index metadata must match.
- Bounded traversal confirms the same count of configuration/interface/alternate objects, same classes and interface numbers, native endpoint bytes, and VC/VS payloads. Allows different actual allocation pointers.
- Language, string indices/lengths, and all payload bytes must equal the template. Unknown SS config or extra copy/companion block is rejected.

Unified descriptor reply uses this check and then serializes the actually active native root from `gc+6c` using original Sony functions. It does not overwrite `gc` to the template, does not introduce a replacement gadgetcore, and does not bypass original copy management.

The validator is not a readability check for arbitrary addresses. The caller must prove the graph comes from a matching native allocator/save call and prevent its modification or freeing during validation and serialization. No new live mutex or finished register/stop/unregister path.

## Offline Proof

Builder creates an explicit independent relocation graph fixture: every config, interface array, alternate, endpoint array, class payload, language, string entry, and string payload gets a different address. This is not emulation of a successful native allocator call or proof of its return values.

The real compiled validator accepts this graph. Real Sony device, config, string, qualifier, and other-speed serializers through our reply path for both speeds produce the exact same bytes as the template. Neither template nor copy fixture is modified. Invalid count/pointer-null, wire number, VC cross-reference, video address 81 colliding with PTP, FS packet size, serial content, and LANGID are rejected before replying without output writes.

573 cumulative checks pass (previous 511 and 62 new). Results: `artifacts/native/uvc-ptp-native-copy-e0160/manifest.json`. All original firmware identities, code/write guards, and explicit fixture markers remain active. Full runtime suite was not repeated: the new part is not wired into the active module.

## Mandatory Cleanup and Return

Original `free_desc_tbl` at `602bc3e4` frees native nested objects, finally frees root at `602bc540`, and writes zero to `gc+6c` at `602bc548`. `save_desc_tbl` failure path at `602bcda8` also calls this helper. Saved SHA-pinned original windows: `artifacts/analysis/uvc-descriptor-ownership-e0160/original-ownership-contract.txt`.

New integration must therefore:

1. Stop and retire descriptor users before modification.
2. Save the original PC Remote root/state as separate ownership.
3. Protect that root before the save call because save can modify `gc+6c` and on error call cleanup. Do not assume old state remains unchanged.
4. Confirm the real installed root and contents before connecting USB.
5. On rollback after quiescence, free only the newly installed native copy with the original helper, then restore the old PC Remote root/state. Do not free caller template or an unknown/foreign table.

Historical legacy shim comments on the current root as a static bundle and in the restore path only zeroes `gc+6c`. That is not a valid model for the new shared mod after native save copying and must not be taken as proof of freeing the copy. Legacy shim was not modified or re-run on camera in this step.

## Boundary

Full native save/allocate/free lifecycle has not yet been executed in these checks. No integrated shared module, physical enumeration, Windows binding, UVC sensor frames, or simultaneous PTP control. No uploads, USB mode change, active modules, SD, or persistent writes.
