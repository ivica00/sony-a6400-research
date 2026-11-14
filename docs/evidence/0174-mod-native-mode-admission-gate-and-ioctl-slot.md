# E0174 — MOD Atomic Mode Change Guard and Original ioctl Entry

Date: 2026-11-08. Offline implementation. No transfer or writes to the camera. E0164 kernel module was not modified.

## Implementation

The new `tools/native_camera/uvc_ptp_mode_gate.{c,h}` implements a **MOD access rule**, not a replacement of Sony's decisions. A single atomic word holds the count of active original entries or exclusive ownership of a MOD transaction. CAS `0→HELD` eliminates the gap between checking active entries and acquiring the transaction.

| Operation | Contract |
|---|---|
| `mode_enter` | Increments the count of active entries if MOD does not hold a transaction. Rejects `HELD` and overflow. |
| `mode_leave` | Decrements the active count without touching `HELD`. Rejects zero and `HELD` state. |
| `mode_claim` | Acquires the transaction exclusively from state 0. |
| `mode_release` | Releases exclusively the exact `HELD` state. Does not clear other active entry counts. |

Enter/leave have a bounded number of CAS attempts and return busy on contention. The caller must not ignore a failed leave nor claim that the transaction was then released. Null inputs and double release are rejected. The structure must persist across all entries; the code does not grant an independent right to remove a hook or free memory.

## Build and Checks

`tools/research/build_uvc_ptp_mode_gate.py` builds a real ARMv7 softfp ELF without libc/imports and executes the compiled functions. Output: `artifacts/native/uvc-ptp-mode-gate-e0174/mode-gate.elf`. The manifest in the same folder contains hashes of the source/header/ELF and the exact build argument vector. Log: `artifacts/uvc-ptp-mode-gate-e0174.log`.

**28 checks pass**: 22 checks for MOD atomic functions and six checks for the original kernel entry. Two active original entries, both contention orders with MOD claim, preserving count on rejected release, overflow, and invalid `HELD+count` states were verified. These are sequential executions of ARM atomic instructions; they are not a physical multicore test or proof of the full Linux memory-model contract.

The build was initially rejected due to overlap of the GNU build-id section with the chosen offline text address; the final reproducible builder explicitly disables build-id. This does not change the bodies of the MOD functions or the native kernel.

## Proven Original Entry

SHA-verified kernel `12eeec829407595e28265f7d0db3b88c56f63a9f0fdd725c9c53c66a49643707` contains:

- `usb_gcore_module_init` at `0x604a580c`;
- original `LDR r1` at `0x604a590c` reads literal `0x604a5990 = 0x604e5078`;
- the next original `BL` at `0x604a5910` calls `cdev_init` at `0x601c241c`;
- `file_operations +0x20`, address **0x604e5098**, points to original `usb_gadgetcore_ioctl` **0x602b8844**;
- adjacent `open +0x2c` and `release +0x34` correspond to `0x602b8814` and `0x602b8284`.

This ties the entry candidate to the real `cdev_init` contract, not merely a randomly found word in the kernel image. No modification was made to that address. Live RAM contents and the feasibility of safe publication/removal of an intermediary have not been verified.

## Integration Conditions Remaining Open

The gate is `integrated:false`. All relevant original entries must actually pass through it; today's module-local gate does not do so. A call that has already loaded the old function pointer, module lifetime when publishing the wrapper, direct kernel exports, USB disconnect/suspend, and EP0 callbacks must not be assumed covered by this `file_operations` slot alone.

For the first test, safe publication/ownership of the intermediary for original USB mode changes and completion/drain of native gadget/EP0 callbacks remain, followed by a bounded activate/restore runner. The gate must not be enabled by blind RAM writes. OSAL acknowledgment evidence E0172 solves a separate callback profile; it is not automatically the EP0 contract.

The current read-only camera check E0173 (`artifacts/hardware/uvc-ptp-readiness-e0173/usb-current.json`) confirmed PC Remote `054c:0caa`. Mode was not switched. The production `.ko` remains E0164, unloaded and `physical_test_ready:false`. The last full project regression remains 605 tests; the targeted checks listed above were executed for the new isolated ARM part.
