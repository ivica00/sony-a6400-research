# E0167 — Public USB Table and Application Stop Call

Date: 2026-11-08. Offline continuation of E0166; no camera access and no changes to the E0164 module.

## Executed Bodies and Sources

`tools/research/probe_uvc_ptp_public_api.py` executes the original `usbif_initialize` prefix, the public stop adapter, `CUsbSvc::stop`, and `UsbIfWrapper::doStop`. There are no host replacements of their branches or function tables.

| Source | SHA-256 |
|---|---|
| a6400 libInfraUsbCmn.so | 5338bafbb545ebc223fac15c9253a41ac9fe49c01fe32c73af40c3fb50eec0a6 |
| a6400 libUsbControl.so | 70cd5742fde9eea78c60905e4015531b4c3ab2668d2cb85c934531f451f1211f |

The initializer prefix 0xd7d9..0xd86c allocates context 0xc4 and service 0x128, sets `context+0x3c=service`, and populates 15 public API pointers. The test stops before the remaining initialization. The allocator, service constructor, memset, and trace/log services are explicit replacements. Successful complete initialization, registration, or object lifetime are not proven.

Important actually written slots:

| Context Offset | Original Function (Thumb) |
|---|---|
| +0x08 | 0xd551, public start adapter |
| +0x0c | 0xd37d, public stop adapter |
| +0x3c | `CUsbSvc` pointer, not a function |

The complete table is retained in the test manifest. These are local ELF addresses, not the addresses of the library currently loaded on the camera.

## Actual Stop Chain

On explicit fixture objects and handle 13, the following sequence was executed:

`libUsbControl::UsbIfWrapper::doStop` (0x13325) → context slot+0x0c → original public adapter (0xd37d) → original `CUsbSvc::stop` (0x9e01) → boundary before `stop_gadget` (PLT 0x81ac).

The public adapter creates the original 12-byte completion payload: service, user completion callback, DID. It then passes `service/DID/payload/12` and its own completion adapter `0xd471` to `CUsbSvc::stop`. `CUsbSvc::stop` changes state 3 to 4 and directly forwards `service/payload/12/0xd471` to `stop_gadget`. No request queue or lock service is called in this executed chain.

For `doStop`, the main application singleton cell at relative `0x1eac4` is explicitly set by the fixture. The library is mapped at a separate base; original PIC code loads the cell, calls `slot+0x0c`, and computes its own callback at relative `0x12de5`. The exact completion address and payload contents were verified. The completion callback, payload freeing, and physical stop were not executed.

This check extends E0166 from the public service to the actual application library. It **does not prove** that a higher caller runs concurrently or that there is no external protection. Adding a mutex only around our kernel entry and declaring all original calls covered is not justified.

## PLT and Higher Caller

The new shared `tools/research/arm_plt.py` decodes actual ARM `add/add/ldr` words and relocations, including rotated immediate values. `libUsbControl` uses the `ADD immediate 20 ROR 20` (`=0x14000`) form, whereas earlier code was studied on a different form. Constant PLT entry spacing or summing Capstone's first immediate operand without rotation are not valid procedures.

Exact target resolution in the application library identifies:

- 0x99f8: `UsbIfWrapper::doSyncStartStop`;
- 0x9fac: `osal_dynamic_id`;
- 0x9904: `osal_rcv_msg_tmo`;
- 0x9e04 / 0xa1ac: `doStart` / `doStop`;
- 0x97c8: `usbif_initialize`.

Static inspection of `doSyncStartStop` 0x13341 shows creation of a temporary OSAL ID (0x29/0xca), selection of `doStart`/`doStop`, and waiting for a response. That body has not yet been executed in a test; waiting for a response by itself is not proof of mutual exclusion. That layer, callback 0x12de5, and all callers remain the next boundary.

## Checks and Status

22 new checks pass in `artifacts/analysis/uvc-ptp-public-api-e0167/manifest.json`, with hashes of the probe and both libraries. The previous queue probe again passes all 35 checks after switching to the shared PLT resolver. Both probes have execution and write boundaries, explicit fixture objects, and service replacements; there is no physical USB test.

The production C module was not modified. The last full project regression remains 605 tests from E0164. Shared protection of all USB entries, physical enumeration of the PTP/UVC combination, configuration recovery after abort, and a real sensor UVC stream are not proven. E0164 remains `physical_test_ready:false`.
