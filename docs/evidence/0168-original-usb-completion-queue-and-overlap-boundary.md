# E0168 — Original USB Completion Queue and Overlap Boundary

Date: 2026-11-08. Offline continuation of E0167. No camera access or kernel module changes.

`tools/research/probe_uvc_ptp_completion.py` executes the original Thumb instructions of `UsbIfWrapper::doSyncStartStop` (0x13341) and the completion callback (0x12de5) from a6400 `libUsbControl.so`, SHA-256 `70cd5742fde9eea78c60905e4015531b4c3ab2668d2cb85c934531f451f1211f`.

## Clean Completion and Errors

For the stop operation, the original code:

1. Creates an OSAL ID by calling `osal_dynamic_id(0x29, 0xca, &global_queue)`.
2. Calls `doStop`; its success here only means the request was accepted.
3. Waits on `osal_rcv_msg_tmo(global_queue, &message, 0xffffffff)`.
4. Returns the first 32-bit status from the response, frees the message, destroys the ID by calling `osal_dynamic_id(0x49, 0, queue)`, and clears `global_queue`.

In the test, status -5 from the response remains -5. If receive returns 7, the code returns 7, destroys the ID, and does not free the unreceived message. If `doStop` immediately returns 6, the code does not wait: it destroys the ID, clears the global, and returns 6. OSAL services and `doStop` are explicit replacements; it is not claimed that a physical stop was performed.

## Completion Uses a Shared Cell

The queue cell is located at relative address `0x1eabc`. For event `0x10001`, callback `0x12de5` reads that cell, requests a 4-byte message via `osal_valloc_msg_wait(queue, &message, 4, 1)`, writes the status from `r2`, and calls `osal_snd_msg(queue, message)`. Unknown events are ignored. Allocation failure aborts sending.

In this stop completion path there is no tag for a specific transaction, no worker thread check, no comparison against an expected ID, and no guard that `queue` is non-zero. After cleanup, the original callback attempts allocation for ID 0. In the fixture, allocation explicitly succeeds so `send(0)` is observed; the real OSAL response to an invalid ID was neither executed nor proven.

A test with two explicit stacks stops the first original synchronous call at the boundary before `doStop` with ID `0x444`. The second original call reaches the same boundary and overwrites the cell with ID `0x555`. The original completion then allocates and sends the response toward `0x555`. This proves that the bodies themselves do not distinguish those two transactions, not that physical callers allow such overlap.

## Consequence for Shared Mode

It is not sufficient to lock only the start of our ioctl call or only the write to the `CUsb` queue. Proof of ownership is required from the start of the change until the final callback, including rejecting new changes while the previous one has not finished and safe handling of late completion. We must not remove or reuse the completion queue while the original callback can still use it. The original public stop and kernel disconnect path remain part of the same contract.

The next step is to verify the original calling context of `doSyncStartStop` in the main `UsbControl` message handling and its relationship to the completion callback. Start completion additionally cleans up descriptor/string resources; that branch was not executed in E0168.

## Result and Limitations

**22 checks pass**, including six actually resolved PLT targets. Report: `artifacts/analysis/uvc-ptp-completion-e0168/manifest.json`; log: `artifacts/uvc-ptp-completion-e0168.log`.

Original decision and wait bodies were executed with execution and write boundaries. OSAL ID, allocation, receive/send/free, and `doStop` are explicit service replacements. The scheduler, actual messages, callback duration, and camera recovery are not proven. Production code was not modified; the last full regression remains 605 tests from E0164. The module remains unloaded and `physical_test_ready:false`; sensor UVC with concurrent PTP control remains incomplete.
